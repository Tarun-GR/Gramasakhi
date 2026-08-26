"""Universal myScheme discovery: shell detect, dynamic canonical resolve, sections."""

from __future__ import annotations

import unittest
from pathlib import Path

from app.config.gov_sources import is_allowed_url
from app.services.gov_source_registry import load_registry
from app.services.live_gov_retrieval_service import verify_source
from app.services.myscheme_service import (
    assess_myscheme_content_quality,
    build_myscheme_external_search_url,
    build_myscheme_scheme_url,
    build_myscheme_seeds_for_query,
    discover_myscheme_scheme_links,
    extract_scheme_id_from_url,
    extract_scheme_sections,
    is_myscheme_shell_html,
    is_myscheme_url,
    normalize_scheme_key,
    rank_scheme_candidates,
    resolve_canonical_scheme,
    scheme_query_variants,
    verify_linked_url,
)
from app.services.language_service import resolve_response_language
from app.services.acquisition.base import SourceHealth, detect_access_block

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "acquisition"


class TestShellDetection(unittest.TestCase):
    def test_search_javascript_shell(self):
        html = (FIXTURES / "myscheme_search_shell.html").read_text(encoding="utf-8")
        shell, reason = is_myscheme_shell_html(html)
        self.assertTrue(shell)
        self.assertIn(reason, {"STATIC_SHELL", "CONTENT_EMPTY", "NETWORK_ERROR"})

    def test_orchestrator_escalates_myscheme_shell(self):
        """Large myScheme Network Error HTML must not be accepted as static success."""
        from unittest.mock import MagicMock, patch

        from app.services.acquisition.base import (
            AcquisitionMethod,
            AcquisitionResult,
            SourceHealth,
        )
        from app.services.acquisition.orchestrator import SourceAcquisitionOrchestrator

        html = (FIXTURES / "myscheme_network_error.html").read_text(encoding="utf-8")
        html = html + ("<!-- pad -->\n" * 500)
        static = AcquisitionResult(
            url="https://www.myscheme.gov.in/search?q=udyogini",
            final_url="https://www.myscheme.gov.in/search?q=udyogini",
            content=html.encode("utf-8"),
            content_type="text/html",
            rendered_text="Something went wrong Please try again later Network Error "
            + ("x" * 400),
            method=AcquisitionMethod.STATIC_HTTP,
            health=SourceHealth.HEALTHY,
            discovered_links=[],
        )
        browser = AcquisitionResult(
            url=static.url,
            final_url=static.url,
            content=(FIXTURES / "myscheme_search_udyogini.html").read_bytes(),
            content_type="text/html",
            rendered_text="Udyogini Scheme Karnataka women entrepreneurship",
            method=AcquisitionMethod.BROWSER_JS,
            health=SourceHealth.HEALTHY,
            discovered_links=[
                {
                    "url": "https://www.myscheme.gov.in/schemes/us",
                    "kind": "scheme_page",
                    "link_text": "Udyogini Scheme",
                }
            ],
        )
        orch = SourceAcquisitionOrchestrator(MagicMock())
        with patch.object(orch.static, "fetch", return_value=static):
            with patch.object(orch.browser, "fetch", return_value=browser):
                with patch(
                    "app.services.acquisition.orchestrator.playwright_available",
                    return_value=True,
                ):
                    with patch(
                        "app.core.config.settings.LIVE_GOV_BROWSER_ENABLED",
                        True,
                    ):
                        out = orch.acquire(
                            static.url,
                            verify_fn=verify_source,
                            live_request_id="shell-test",
                            query="Udyogini",
                        )
        self.assertTrue(out.ok)
        self.assertEqual(out.method, AcquisitionMethod.BROWSER_JS)
        self.assertIn(b"Udyogini", out.content or b"")

    def test_network_error_page(self):
        html = (FIXTURES / "myscheme_network_error.html").read_text(encoding="utf-8")
        shell, reason = is_myscheme_shell_html(html)
        self.assertTrue(shell)
        self.assertEqual(reason, "NETWORK_ERROR")

    def test_real_scheme_page_not_shell(self):
        html = (FIXTURES / "myscheme_scheme_udyogini.html").read_text(encoding="utf-8")
        shell, reason = is_myscheme_shell_html(html)
        self.assertFalse(shell)
        self.assertEqual(reason, "CONTENT_OK")
        q = assess_myscheme_content_quality(html)
        self.assertFalse(q["is_shell"])
        self.assertGreaterEqual(q["section_count"], 3)


class TestDynamicCanonicalResolution(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        load_registry(force_reload=True)
        cls.search_html = (FIXTURES / "myscheme_search_udyogini.html").read_text(
            encoding="utf-8"
        )
        cls.rules_html = (FIXTURES / "myscheme_rules_catalogue.html").read_text(
            encoding="utf-8"
        )

    def test_exact_udyogini_match_not_pm_kisan(self):
        links = discover_myscheme_scheme_links(
            "https://www.myscheme.gov.in/search",
            self.search_html,
            verify_fn=verify_source,
            query="Udyogini scheme details",
            limit=5,
        )
        self.assertTrue(links)
        self.assertTrue(any(l.get("scheme_id") == "us" for l in links))
        top = rank_scheme_candidates(links, "Udyogini scheme details")[0]
        self.assertEqual(top.get("scheme_id"), "us")
        self.assertNotEqual(top.get("scheme_id"), "pm-kisan")

    def test_resolve_canonical_from_search(self):
        resolved = resolve_canonical_scheme(
            "Udyogini Scheme Karnataka",
            html=self.search_html,
            base_url="https://www.myscheme.gov.in/search",
            verify_fn=verify_source,
        )
        self.assertIsNotNone(resolved)
        self.assertEqual(resolved["scheme_id"], "us")
        self.assertEqual(
            resolved["canonical_url"],
            "https://www.myscheme.gov.in/schemes/us",
        )
        self.assertTrue(is_myscheme_url(resolved["url"]))

    def test_does_not_hardcode_only_udyogini(self):
        # PMJJBY still resolves from known alias without inventing Udyogini ID
        self.assertEqual(
            extract_scheme_id_from_url(build_myscheme_scheme_url("pmjjby")),
            "pmjjby",
        )

    def test_untrusted_link_rejected(self):
        self.assertFalse(
            verify_linked_url(
                "https://evil.example.com/udyogini",
                verify_fn=verify_source,
            )
        )

    def test_catalogue_discovery_twenty_schemes(self):
        links = discover_myscheme_scheme_links(
            "https://rules.myscheme.gov.in/",
            self.rules_html,
            verify_fn=verify_source,
            query="",
            limit=30,
        )
        ids = {l.get("scheme_id") for l in links}
        self.assertGreaterEqual(len(ids), 20)
        self.assertNotIn(None, ids)
        # Evil link must not appear
        self.assertFalse(any("evil.example.com" in (l.get("url") or "") for l in links))

        # Each of 20 names must resolve to a canonical myScheme URL
        samples = [
            ("Udyogini Scheme", "us"),
            ("PMJJBY", "pmjjby"),
            ("PM-KISAN", "pm-kisan"),
            ("PMFBY", "pmfby"),
            ("PMSBY", "pmsby"),
            ("MGNREGA", "mgnrega"),
            ("Ayushman Bharat PM-JAY", "ab-pmjay"),
            ("PMAY-G", "pmayg"),
            ("PM Ujjwala Yojana", "pmuy"),
            ("Jal Jeevan Mission", "jjm"),
            ("PMAY Urban", "pmay-u"),
            ("Anna Bhagya", "anna-bhagya"),
            ("Gruha Lakshmi", "gruha-lakshmi"),
            ("Gruha Jyothi", "gruha-jyothi"),
            ("Atal Pension Yojana", "apy"),
            ("PMMVY", "pmmvy"),
            ("Beti Bachao Beti Padhao", "bbbp"),
            ("DAY-NULM", "day-nulm"),
            ("National Pension System", "nps"),
            ("Sukanya Samriddhi", "sby"),
        ]
        self.assertEqual(len(samples), 20)
        for name, expect_id in samples:
            resolved = resolve_canonical_scheme(
                name,
                html=self.rules_html,
                base_url="https://rules.myscheme.gov.in/",
                verify_fn=verify_source,
            )
            self.assertIsNotNone(resolved, name)
            self.assertEqual(resolved["scheme_id"], expect_id, name)
            self.assertTrue(resolved["url"].endswith(f"/schemes/{expect_id}"))


class TestSeedsAndVariants(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        load_registry(force_reload=True)

    def test_seeds_include_search_external_and_catalogue(self):
        seeds = build_myscheme_seeds_for_query(
            "Udyogini scheme details",
            verify_fn=verify_source,
            limit=6,
        )
        urls = " ".join(s["url"] for s in seeds)
        self.assertIn("myscheme.gov.in/search", urls)
        self.assertIn("external/search", urls)
        self.assertIn("rules.myscheme.gov.in", urls)

    def test_rules_host_trusted(self):
        self.assertTrue(is_allowed_url("https://rules.myscheme.gov.in/"))
        self.assertTrue(verify_source("https://rules.myscheme.gov.in/"))

    def test_query_variants(self):
        vs = scheme_query_variants("Udyogini scheme details")
        self.assertTrue(any("Udyogini" in v for v in vs))

    def test_normalize_pm_kisan_forms(self):
        self.assertEqual(normalize_scheme_key("PM-KISAN"), normalize_scheme_key("PM KISAN"))
        self.assertEqual(normalize_scheme_key("PMKISAN"), normalize_scheme_key("pm-kisan"))

    def test_external_search_url(self):
        url = build_myscheme_external_search_url("Udyogini")
        self.assertIn("/external/search?", url)


class TestSectionExtraction(unittest.TestCase):
    def test_udyogini_sections(self):
        html = (FIXTURES / "myscheme_scheme_udyogini.html").read_text(encoding="utf-8")
        sections = extract_scheme_sections(html)
        for key in ("details", "benefits", "eligibility", "application", "documents"):
            self.assertIn(key, sections, key)
        self.assertIn("Aadhaar", sections["documents"])


class TestSecurityAndAccess(unittest.TestCase):
    def test_login_captcha_still_block(self):
        login = (FIXTURES / "login_page.html").read_text(encoding="utf-8")
        captcha = (FIXTURES / "captcha_page.html").read_text(encoding="utf-8")
        self.assertEqual(detect_access_block(login), SourceHealth.LOGIN_REQUIRED)
        self.assertEqual(detect_access_block(captcha), SourceHealth.CAPTCHA_BLOCKED)

    def test_ssrf_blocked(self):
        self.assertFalse(verify_source("http://127.0.0.1/admin"))


class TestMultilingualDiscoveryHints(unittest.TestCase):
    def test_kannada_response_language(self):
        d = resolve_response_language(
            "\u0c89\u0ca6\u0ccd\u0caf\u0ccb\u0c97\u0cbf\u0ca8\u0cbf \u0caf\u0ccb\u0c9c\u0ca8\u0cc6\u0caf \u0cb5\u0cbf\u0cb5\u0cb0\u0c97\u0cb3\u0cc1 \u0c8f\u0ca8\u0cc1?"
        )
        self.assertEqual(d.response_language, "KN")

    def test_hindi_response_language(self):
        d = resolve_response_language("\u0909\u0926\u094d\u092f\u094b\u0917\u093f\u0928\u0940 \u092f\u094b\u091c\u0928\u093e \u0915\u094d\u092f\u093e \u0939\u0948?")
        self.assertEqual(d.response_language, "HI")

    def test_transliteration_scheme_seeds(self):
        seeds = build_myscheme_seeds_for_query(
            "udyogini yojane details",
            verify_fn=verify_source,
        )
        self.assertTrue(seeds)


if __name__ == "__main__":
    unittest.main()
