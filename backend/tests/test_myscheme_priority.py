"""myScheme-first live priority + sufficiency-aware fallback tests."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from app.services.gov_source_registry import load_registry
from app.services.live_gov_retrieval_service import (
    LIVE_DOCUMENT_INGESTED,
    NO_TRUSTED_INFORMATION_FOUND,
    LiveGovRetrievalService,
    discover_seed_urls,
    looks_like_gov_scheme_query,
    verify_source,
)
from app.services.myscheme_service import (
    build_myscheme_seeds_for_query,
    is_myscheme_url,
    verify_linked_url,
)
from app.services.language_service import resolve_response_language


class TestMySchemeSeedPriority(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        load_registry(force_reload=True)

    def test_myscheme_phase_seeds_are_myscheme_only(self):
        seeds = discover_seed_urls("What is PMJJBY eligibility?", phase="myscheme")
        self.assertTrue(seeds)
        for s in seeds:
            self.assertTrue(is_myscheme_url(s["url"]), s["url"])

    def test_all_phase_puts_myscheme_before_non_myscheme(self):
        seeds = discover_seed_urls(
            "details about Pradhan Mantri Jeevan Jyoti Bima Yojana",
            phase="all",
        )
        self.assertTrue(seeds)
        first_myscheme = next(
            (i for i, s in enumerate(seeds) if is_myscheme_url(s["url"])),
            None,
        )
        self.assertIsNotNone(first_myscheme)
        # First seed should be myScheme when scheme query
        self.assertTrue(is_myscheme_url(seeds[0]["url"]), seeds[0]["url"])

    def test_fallback_phase_excludes_myscheme_hosts(self):
        ms = discover_seed_urls("What are PM-KISAN benefits?", phase="myscheme")
        already = [s["url"] for s in ms]
        fb = discover_seed_urls(
            "What are PM-KISAN benefits?",
            phase="fallback",
            already=already,
        )
        for s in fb:
            self.assertFalse(is_myscheme_url(s["url"]), s["url"])

    def test_non_scheme_query_no_myscheme_seeds(self):
        # Avoid catalog keyword collisions (e.g. \"rice\" → Anna Bhagya).
        q = "how to braid hair at home"
        self.assertFalse(looks_like_gov_scheme_query(q))
        seeds = build_myscheme_seeds_for_query(q, verify_fn=verify_source)
        self.assertEqual(seeds, [])


class TestMySchemePriorityRouting(unittest.TestCase):
    def test_myscheme_sufficient_skips_registry_discovery(self):
        db = MagicMock()
        svc = LiveGovRetrievalService(db)
        ms_cand = {
            "url": "https://www.myscheme.gov.in/schemes/pmjjby",
            "kind": "html",
            "content": (
                b"<html><body><h2>Details</h2><p>PMJJBY provides life insurance cover "
                b"for eligible bank account holders under the notified government scheme.</p>"
                b"<h2>Benefits</h2><p>Risk cover of Rs 2 lakh on death due to any reason "
                b"as notified in the official scheme guidelines.</p>"
                b"<h2>Eligibility</h2><p>Individuals aged 18 to 50 years with a savings "
                b"bank account who consent to auto-debit may enroll.</p>"
                b"<h2>Documents Required</h2><p>Aadhaar and bank account details.</p>"
                b"</body></html>"
            ),
            "content_type": "text/html",
            "scheme_name": "pmjjby",
            "source": "myscheme",
        }
        calls = {"n": 0}

        def discover_side_effect(query, **kwargs):
            calls["n"] += 1
            seeds = kwargs.get("seeds")
            if seeds is not None and all(
                is_myscheme_url((s.get("url") or "")) for s in seeds
            ):
                return [ms_cand]
            # Registry/fallback must not be reached when myScheme is sufficient
            raise AssertionError("fallback discover_candidate_pages must not run")

        with patch.object(svc, "discover_candidate_pages", side_effect=discover_side_effect):
            with patch.object(
                svc,
                "ingest_verified_document",
                return_value={
                    "status": "ok",
                    "document_id": "ms1",
                    "source_url": ms_cand["url"],
                    "chunk_count": 2,
                },
            ):
                with patch.object(svc, "refresh_indexes", return_value={"chunk_count": 2}):
                    with patch.object(svc, "_probe_evidence_ready", return_value=True):
                        out = svc.search_government_sources(
                            "What is PMJJBY eligibility and benefits?"
                        )
        self.assertTrue(out.get("evidence_ready"))
        self.assertTrue(out.get("myscheme_priority"))
        self.assertEqual(out.get("status"), LIVE_DOCUMENT_INGESTED)
        self.assertEqual(calls["n"], 1)

    def test_myscheme_partial_continues_to_fallback(self):
        db = MagicMock()
        svc = LiveGovRetrievalService(db)
        ms_cand = {
            "url": "https://www.myscheme.gov.in/schemes/pm-kisan",
            "kind": "html",
            "content": (
                b"<html><body><h2>Details</h2><p>PM-KISAN provides income support "
                b"to landholding farmer families as notified by the Government of India.</p>"
                b"<h2>Benefits</h2><p>Financial assistance is transferred in installments "
                b"to eligible farmer beneficiaries subject to scheme rules.</p>"
                b"</body></html>"
            ),
            "content_type": "text/html",
            "scheme_name": "PM-KISAN",
            "source": "myscheme",
        }
        fb_cand = {
            "url": "https://pmkisan.gov.in/pm-kisan-eligibility-benefits-documents.pdf",
            "kind": "pdf",
            "content": b"%PDF-1.4 eligibility benefits documents procedure",
            "content_type": "application/pdf",
            "scheme_name": "PM-KISAN",
            "link_text": "PM-KISAN eligibility benefits documents",
        }
        phases = []

        def discover_side_effect(query, **kwargs):
            seeds = kwargs.get("seeds")
            if seeds is not None and seeds and all(
                is_myscheme_url((s.get("url") or "")) for s in seeds
            ):
                phases.append("myscheme")
                return [ms_cand]
            phases.append("fallback")
            return [fb_cand]

        probe_vals = [False, True]  # myScheme insufficient, then combined PASS

        with patch.object(svc, "discover_candidate_pages", side_effect=discover_side_effect):
            with patch.object(
                svc,
                "ingest_verified_document",
                side_effect=[
                    {
                        "status": "ok",
                        "document_id": "ms1",
                        "source_url": ms_cand["url"],
                        "chunk_count": 1,
                    },
                    {
                        "status": "ok",
                        "document_id": "fb1",
                        "source_url": fb_cand["url"],
                        "chunk_count": 2,
                    },
                ],
            ):
                with patch.object(svc, "refresh_indexes", return_value={"chunk_count": 3}):
                    with patch.object(
                        svc, "_probe_evidence_ready", side_effect=probe_vals
                    ):
                        out = svc.search_government_sources(
                            "PM-KISAN eligibility benefits and documents"
                        )
        self.assertIn("myscheme", phases)
        self.assertIn("fallback", phases)
        self.assertTrue(out.get("evidence_ready"))
        self.assertGreaterEqual(len(out.get("ingested") or []), 2)

    def test_myscheme_unavailable_falls_back(self):
        db = MagicMock()
        svc = LiveGovRetrievalService(db)
        fb_cand = {
            "url": "https://pmkisan.gov.in/benefits.pdf",
            "kind": "pdf",
            "content": b"%PDF-1.4 PM-KISAN benefits eligibility",
            "content_type": "application/pdf",
            "scheme_name": "PM-KISAN",
        }

        def discover_side_effect(query, **kwargs):
            seeds = kwargs.get("seeds")
            if seeds is not None and seeds and all(
                is_myscheme_url((s.get("url") or "")) for s in seeds
            ):
                return []  # myScheme empty / unavailable
            return [fb_cand]

        with patch.object(svc, "discover_candidate_pages", side_effect=discover_side_effect):
            with patch.object(
                svc,
                "ingest_verified_document",
                return_value={
                    "status": "ok",
                    "document_id": "fb1",
                    "source_url": fb_cand["url"],
                    "chunk_count": 2,
                },
            ):
                with patch.object(svc, "refresh_indexes", return_value={"chunk_count": 2}):
                    with patch.object(svc, "_probe_evidence_ready", return_value=True):
                        out = svc.search_government_sources("What are PM-KISAN benefits?")
        self.assertTrue(out.get("evidence_ready"))
        self.assertEqual(out.get("accepted_url"), fb_cand["url"])

    def test_external_myscheme_link_not_auto_trusted(self):
        self.assertFalse(
            verify_linked_url(
                "https://evil.example.com/doc.pdf",
                verify_fn=verify_source,
            )
        )
        self.assertTrue(
            verify_source("https://www.myscheme.gov.in/schemes/pmjjby")
        )


class TestMySchemeLanguageContract(unittest.TestCase):
    def test_kannada_response_language_independent_of_live_search(self):
        d = resolve_response_language(
            "PM-KISAN \u0caf\u0ccb\u0c9c\u0ca8\u0cc6 \u0cac\u0c97\u0ccd\u0c97\u0cc6 \u0cae\u0cbe\u0cb9\u0cbf\u0ca4\u0cbf \u0ca8\u0cc0\u0ca1\u0cbf",
            conversation_language="EN",
        )
        self.assertEqual(d.response_language, "KN")

    def test_hindi_response_language(self):
        d = resolve_response_language(
            "\u092a\u0940\u090f\u092e \u0915\u093f\u0938\u093e\u0928 \u0915\u0947 \u0932\u093f\u090f \u0915\u094c\u0928 \u092a\u093e\u0924\u094d\u0930 \u0939\u0948?",
            conversation_language="EN",
        )
        self.assertEqual(d.response_language, "HI")

    def test_voice_transliteration_still_scheme_query(self):
        self.assertTrue(looks_like_gov_scheme_query("pm kisan yojane yenu"))
        seeds = build_myscheme_seeds_for_query(
            "pm kisan yojane yenu", verify_fn=verify_source
        )
        self.assertTrue(any(is_myscheme_url(s["url"]) for s in seeds))


class TestMySchemeKnowledgeFirstContract(unittest.TestCase):
    def test_empty_status_constant_unchanged(self):
        self.assertEqual(NO_TRUSTED_INFORMATION_FOUND, "NO_TRUSTED_INFORMATION_FOUND")


if __name__ == "__main__":
    unittest.main()
