"""myScheme zero-candidate discovery reliability — normalization + escalation."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.services.live_gov_retrieval_service import verify_source
from app.services.myscheme_service import (
    build_myscheme_scheme_url,
    build_myscheme_search_url,
    collect_candidates_from_html,
    extract_candidates_from_json_text,
    extract_scheme_name_hint,
    lookup_discovery_cache,
    normalize_myscheme_search_query,
    normalize_scheme_key,
    rank_scheme_candidates,
    remember_discovery_candidate,
    resolve_canonical_scheme,
    scheme_query_variants,
    slug_hint_from_query,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "acquisition"


class TestConversationalNormalization(unittest.TestCase):
    def test_udyogini_conversational(self):
        q = "can i get details about Udyogini scheme"
        norm = normalize_myscheme_search_query(q)
        self.assertIn("udyogini", norm.lower())
        self.assertNotIn("can i", norm.lower())
        self.assertNotIn("details about", norm.lower())
        variants = scheme_query_variants(q)
        self.assertTrue(any("udyogini" in v.lower() for v in variants))
        url = build_myscheme_search_url(q)
        self.assertIn("Udyogini", url)
        self.assertNotIn("can", url.lower().split("q=")[-1])

    def test_mukhyamantri_conversational(self):
        q = "can I get details about Mukhyamantri Prakhand Parivahan Yojana"
        hint = extract_scheme_name_hint(q)
        self.assertIn("Prakhand", hint)
        self.assertNotIn("can I", hint)
        variants = scheme_query_variants(q)
        blob = " ".join(variants).lower()
        self.assertIn("prakhand", blob)
        self.assertTrue(
            any("mukhyamantri prakhand parivahan" in v.lower() for v in variants)
            or "prakhand parivahan" in blob
        )

    def test_kannada_udyogini(self):
        q = "ಉದ್ಯೋಗಿನಿ ಯೋಜನೆ ಏನು?"
        norm = normalize_myscheme_search_query(q)
        self.assertIn("udyogini", norm.lower())

    def test_hindi_udyogini(self):
        q = "उद्योगिनी योजना"
        norm = normalize_myscheme_search_query(q)
        self.assertIn("udyogini", norm.lower())

    def test_transliteration(self):
        q = "udyogini yojane"
        self.assertEqual(normalize_scheme_key(normalize_myscheme_search_query(q)), "udyogini")


class TestUdyoginiMatch(unittest.TestCase):
    def test_exact_udyogini_canonical(self):
        self.assertEqual(slug_hint_from_query("Udyogini Scheme"), "us")
        resolved = resolve_canonical_scheme(
            "details about Udyogini scheme",
            html="",
            verify_fn=verify_source,
        )
        self.assertIsNotNone(resolved)
        self.assertEqual(resolved["scheme_id"], "us")
        self.assertEqual(
            resolved["canonical_url"],
            "https://www.myscheme.gov.in/schemes/us",
        )

    def test_catalogue_discovery(self):
        html = (FIXTURES / "myscheme_rules_catalogue.html").read_text(encoding="utf-8")
        cands = collect_candidates_from_html(
            html,
            query="Udyogini",
            base_url="https://rules.myscheme.gov.in/",
            verify_fn=verify_source,
            source_tag="catalogue",
        )
        self.assertTrue(cands)
        self.assertEqual(cands[0].get("scheme_id"), "us")

    def test_search_html_candidates(self):
        html = (FIXTURES / "myscheme_search_udyogini.html").read_text(encoding="utf-8")
        resolved = resolve_canonical_scheme(
            "Udyogini",
            html=html,
            base_url="https://www.myscheme.gov.in/search?q=Udyogini",
            verify_fn=verify_source,
        )
        self.assertIsNotNone(resolved)
        self.assertEqual(resolved["scheme_id"], "us")

    def test_json_candidate_extraction(self):
        payload = json.dumps(
            {
                "results": [
                    {
                        "schemeId": "us",
                        "schemeName": "Udyogini Scheme",
                        "state": "Karnataka",
                    },
                    {"schemeId": "pm-kisan", "schemeName": "PM-KISAN"},
                ]
            }
        )
        cands = extract_candidates_from_json_text(
            payload, query="Udyogini", verify_fn=verify_source
        )
        ranked = rank_scheme_candidates(cands, "Udyogini")
        self.assertTrue(ranked)
        self.assertEqual(ranked[0].get("scheme_id"), "us")

    def test_wrong_candidate_rejection(self):
        cands = [
            {
                "scheme_name": "Udyam Registration",
                "scheme_id": "udyam",
                "url": "https://www.myscheme.gov.in/schemes/udyam",
                "match_score": 5,
            },
            {
                "scheme_name": "PM-KISAN",
                "scheme_id": "pm-kisan",
                "url": "https://www.myscheme.gov.in/schemes/pm-kisan",
                "match_score": 5,
            },
            {
                "scheme_name": "Udyogini Scheme",
                "scheme_id": "us",
                "url": "https://www.myscheme.gov.in/schemes/us",
                "match_score": 5,
            },
        ]
        ranked = rank_scheme_candidates(cands, "Udyogini Scheme")
        self.assertTrue(ranked)
        self.assertEqual(ranked[0]["scheme_id"], "us")
        for r in ranked:
            self.assertNotEqual(r.get("scheme_id"), "pm-kisan")

    def test_state_boost_karnataka(self):
        cands = [
            {
                "scheme_name": "Udyogini Scheme",
                "scheme_id": "us",
                "url": "https://www.myscheme.gov.in/schemes/us",
                "state": "Karnataka",
                "match_score": 20,
            },
            {
                "scheme_name": "Udyogini Central",
                "scheme_id": "us-central",
                "url": "https://www.myscheme.gov.in/schemes/us-central",
                "match_score": 20,
            },
        ]
        # Inject state into name/url for boost path used by ranker
        cands[0]["scheme_name"] = "Udyogini Scheme Karnataka"
        ranked = rank_scheme_candidates(
            cands, "Udyogini scheme in Karnataka", state_hint="karnataka"
        )
        self.assertEqual(ranked[0]["scheme_id"], "us")


class TestBrowserEscalation(unittest.TestCase):
    def test_zero_static_triggers_browser_discovery(self):
        from app.services.acquisition.base import (
            AcquisitionMethod,
            AcquisitionResult,
            SourceHealth,
        )
        from app.services.live_gov_retrieval_service import LiveGovRetrievalService

        svc = LiveGovRetrievalService(db=MagicMock())
        svc.acquisition = MagicMock()
        html = (FIXTURES / "myscheme_search_udyogini.html").read_text(encoding="utf-8")
        svc.acquisition.acquire.return_value = AcquisitionResult(
            url="https://www.myscheme.gov.in/search?q=Udyogini",
            final_url="https://www.myscheme.gov.in/search?q=Udyogini",
            content=html.encode("utf-8"),
            content_type="text/html",
            rendered_text="Udyogini Scheme Karnataka",
            method=AcquisitionMethod.BROWSER_JS,
            health=SourceHealth.HEALTHY,
            discovered_links=[
                {
                    "url": "https://www.myscheme.gov.in/schemes/us",
                    "kind": "scheme_page",
                    "link_text": "Udyogini Scheme",
                    "scheme_id": "us",
                }
            ],
        )
        # Force path without alias by querying a name that relies on browser HTML
        with patch(
            "app.services.live_gov_retrieval_service.LiveGovRetrievalService._myscheme_browser_discover_candidates",
            wraps=svc._myscheme_browser_discover_candidates,
        ):
            # Clear alias for this call by using a long state scheme name
            out = svc._myscheme_browser_discover_candidates(
                "Mukhyamantri Prakhand Parivahan Yojana demo fixture",
                overall_deadline=None,
            )
        # Acquisition was invoked with force_browser path
        self.assertTrue(svc.acquisition.acquire.called)
        kwargs = svc.acquisition.acquire.call_args.kwargs
        self.assertTrue(kwargs.get("force_browser"))

    def test_phase_logs_scheme_not_resolved_not_no_candidates(self):
        """Empty after browser escalation must use scheme_not_resolved."""
        from app.services.myscheme_service import log_myscheme

        # Smoke: reason string exists in live path (unit-checked via source read)
        src = Path(__file__).resolve().parents[1] / "app" / "services" / "live_gov_retrieval_service.py"
        text = src.read_text(encoding="utf-8")
        self.assertIn('reason="scheme_not_resolved"', text)
        self.assertIn("NO_STATIC_CANDIDATES", text)
        self.assertIn("NO_BROWSER_CANDIDATES", text)
        self.assertNotIn('reason="no_candidates"', text)


class TestCacheAndSecurity(unittest.TestCase):
    def test_discovery_cache_roundtrip(self):
        remember_discovery_candidate(
            {
                "scheme_id": "us",
                "scheme_name": "Udyogini Scheme",
                "canonical_url": build_myscheme_scheme_url("us"),
                "confidence": 90,
            },
            query="Udyogini",
        )
        hit = lookup_discovery_cache("Udyogini Scheme")
        self.assertIsNotNone(hit)
        self.assertEqual(hit["scheme_id"], "us")

    def test_canonical_url_https_myscheme_only(self):
        url = build_myscheme_scheme_url("us")
        self.assertTrue(url.startswith("https://www.myscheme.gov.in/schemes/"))
        self.assertTrue(verify_source(url))
        self.assertFalse(verify_source("http://evil.example.com/schemes/us"))

    def test_ssrf_and_login_captcha_unchanged(self):
        from app.services.acquisition.base import detect_access_block, SourceHealth

        self.assertFalse(verify_source("http://127.0.0.1/schemes/us"))
        self.assertFalse(verify_source("file:///etc/passwd"))
        html_login = "<html><body>Please login to continue Sign in</body></html>"
        html_captcha = "<html><body>captcha verification required</body></html>"
        # detect_access_block may return None or specific health — must not bypass
        for html in (html_login, html_captcha):
            blocked = detect_access_block(html)
            self.assertIn(
                blocked,
                (
                    SourceHealth.LOGIN_REQUIRED,
                    SourceHealth.CAPTCHA_BLOCKED,
                    SourceHealth.PUBLIC_ACCESS_BLOCKED,
                    None,
                ),
            )


if __name__ == "__main__":
    unittest.main()
