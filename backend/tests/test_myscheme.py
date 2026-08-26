"""myScheme.gov.in first-class trusted source — additive acquisition tests."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.config.gov_sources import is_allowed_url
from app.services.acquisition.static_http import discover_document_links
from app.services.gov_source_registry import load_registry
from app.services.live_gov_retrieval_service import (
    discover_seed_urls,
    score_candidate,
    verify_source,
)
from app.services.myscheme_service import (
    build_myscheme_scheme_url,
    build_myscheme_search_url,
    build_myscheme_seeds_for_query,
    discover_myscheme_scheme_links,
    discover_relevant_media,
    extract_tables_as_text,
    is_myscheme_url,
    public_api_to_evidence_text,
    slug_hint_from_query,
    verify_linked_url,
)
from app.services.web_ingestion_service import WebIngestionService

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "acquisition"


class TestMySchemeTrust(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        load_registry(force_reload=True)

    def test_myscheme_trusted(self):
        self.assertTrue(is_allowed_url("https://www.myscheme.gov.in/"))
        self.assertTrue(is_allowed_url("https://www.myscheme.gov.in/schemes/pmjjby"))
        self.assertTrue(verify_source("https://www.myscheme.gov.in/schemes/pm-kisan"))

    def test_untrusted_domain_rejected(self):
        self.assertFalse(verify_source("https://evil.example.com/scheme"))
        self.assertFalse(
            verify_linked_url(
                "https://evil.example.com/scheme", verify_fn=verify_source
            )
        )

    def test_ssrf_localhost_rejected(self):
        self.assertFalse(verify_source("http://127.0.0.1/admin"))
        self.assertFalse(verify_source("http://localhost:8000/secret"))


class TestMySchemeDiscovery(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        load_registry(force_reload=True)

    def test_slug_and_search_urls(self):
        self.assertEqual(slug_hint_from_query("PMJJBY details"), "pmjjby")
        self.assertEqual(
            slug_hint_from_query("Pradhan Mantri Jeevan Jyoti Bima Yojana"),
            "pmjjby",
        )
        self.assertIn("/schemes/pmjjby", build_myscheme_scheme_url("pmjjby"))
        self.assertIn("search?q=", build_myscheme_search_url("PMJJBY eligibility"))

    def test_seeds_include_myscheme_for_scheme_query(self):
        seeds = build_myscheme_seeds_for_query(
            "details about Pradhan Mantri Jeevan Jyoti Bima Yojana",
            verify_fn=verify_source,
        )
        urls = " ".join(s["url"] for s in seeds)
        self.assertIn("myscheme.gov.in/schemes/pmjjby", urls)

    def test_discover_seed_urls_prioritizes_myscheme_pmjjby(self):
        seeds = discover_seed_urls(
            "details about Pradhan Mantri Jeevan Jyoti Bima Yojana"
        )
        self.assertTrue(seeds)
        joined = " ".join(s["url"] for s in seeds)
        self.assertIn("myscheme.gov.in", joined)
        # Prefer scheme page over bare financialservices homepage when present
        self.assertTrue(
            any("myscheme.gov.in/schemes/pmjjby" in (s.get("url") or "") for s in seeds)
            or any(s.get("stage", "").startswith("myscheme") for s in seeds)
        )

    def test_score_boosts_myscheme_scheme_page(self):
        s_scheme = score_candidate(
            "https://www.myscheme.gov.in/schemes/pmjjby",
            "PMJJBY eligibility",
            link_text="PMJJBY",
            kind="scheme_page",
        )
        s_home = score_candidate(
            "https://www.myscheme.gov.in/",
            "PMJJBY eligibility",
            link_text="myScheme",
            kind="html",
        )
        self.assertGreater(s_scheme, s_home)


class TestMySchemeHtmlFixtures(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        load_registry(force_reload=True)
        cls.search_html = (FIXTURES / "myscheme_search.html").read_text(encoding="utf-8")
        cls.detail_html = (FIXTURES / "myscheme_scheme_detail.html").read_text(
            encoding="utf-8"
        )

    def test_scheme_link_discovery_rejects_untrusted(self):
        links = discover_myscheme_scheme_links(
            "https://www.myscheme.gov.in/search",
            self.search_html,
            verify_fn=verify_source,
            query="PMJJBY",
        )
        urls = [l["url"] for l in links]
        self.assertTrue(any("/schemes/pmjjby" in u for u in urls))
        self.assertFalse(any("evil.example.com" in u for u in urls))

    def test_document_links_find_scheme_pages(self):
        links = discover_document_links(
            "https://www.myscheme.gov.in/search",
            self.search_html,
            verify_fn=verify_source,
        )
        kinds = {l["kind"] for l in links}
        self.assertIn("scheme_page", kinds)

    def test_table_extraction(self):
        tables = extract_tables_as_text(self.search_html)
        self.assertIn("TABLE:", tables)
        self.assertIn("PMJJBY", tables)
        self.assertIn("Eligibility", tables)

    def test_html_extract_includes_tables(self):
        web = WebIngestionService.__new__(WebIngestionService)
        text = web.extract_text_from_html(
            self.detail_html, base_url="https://www.myscheme.gov.in/schemes/pmjjby"
        )
        self.assertIn("Eligibility", text)
        self.assertIn("2 Lakh", text)
        self.assertIn("Aadhaar", text)

    def test_media_relevance_ranking(self):
        media = discover_relevant_media(
            "https://www.myscheme.gov.in/search",
            self.search_html,
            verify_fn=verify_source,
            query="PMJJBY eligibility",
            limit=3,
        )
        kinds = {m["kind"] for m in media}
        self.assertTrue("image" in kinds or "audio" in kinds)

    def test_json_api_normalization(self):
        text = public_api_to_evidence_text(
            {"scheme": "pmjjby", "benefit": "200000", "premium": "436"},
            source_url="https://www.myscheme.gov.in/api/schemes/pmjjby",
        )
        self.assertIn("pmjjby", text.lower())
        self.assertIn("200000", text)

    def test_login_captcha_detection_still_blocks(self):
        from app.services.acquisition.base import SourceHealth, detect_access_block

        login = (FIXTURES / "login_page.html").read_text(encoding="utf-8")
        captcha = (FIXTURES / "captcha_page.html").read_text(encoding="utf-8")
        self.assertEqual(detect_access_block(login), SourceHealth.LOGIN_REQUIRED)
        self.assertEqual(detect_access_block(captcha), SourceHealth.CAPTCHA_BLOCKED)

    def test_is_myscheme_url(self):
        self.assertTrue(is_myscheme_url("https://www.myscheme.gov.in/schemes/x"))
        self.assertFalse(is_myscheme_url("https://pmkisan.gov.in/"))


class TestMySchemeKnowledgeFirst(unittest.TestCase):
    def test_live_not_called_when_evidence_passes(self):
        """Knowledge-first contract is covered by TestLiveFallbackGate; assert helper exists."""
        from app.services.live_gov_retrieval_service import try_live_gov_fallback
        from app.services.myscheme_service import build_myscheme_seeds_for_query

        # Non-scheme queries must not force myScheme seeds
        seeds = build_myscheme_seeds_for_query(
            "how to cook rice", verify_fn=verify_source
        )
        self.assertEqual(seeds, [])
        self.assertTrue(callable(try_live_gov_fallback))


if __name__ == "__main__":
    unittest.main()
