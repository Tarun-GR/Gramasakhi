"""Stage 2 — MyScheme thin provider adapter tests."""

from __future__ import annotations

import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.services.providers import (
    MySchemeProvider,
    ProviderContext,
    ProviderPhaseStatus,
    ProviderRegistry,
    SchemeCandidate,
    extracted_evidence_is_usable,
)
from app.services.providers.myscheme_provider import _dict_to_candidate

FIXTURE = (
    Path(__file__).resolve().parent / "fixtures" / "acquisition" / "myscheme_scheme_udyogini.html"
)


class TestMySchemeProviderSupports(unittest.TestCase):
    def _ctx(self, query: str) -> ProviderContext:
        return ProviderContext(
            query=query,
            search_query=query,
            live_request_id="ms-test",
            overall_deadline=time.time() + 120,
            per_source_timeout=25.0,
        )

    def test_supports_scheme_query(self):
        p = MySchemeProvider()
        self.assertTrue(p.supports("Who is eligible for PM-KISAN?", context=self._ctx("PM-KISAN eligibility")))

    def test_rejects_non_scheme_query(self):
        p = MySchemeProvider()
        self.assertFalse(p.supports("What is the weather today?", context=self._ctx("weather")))


class TestMySchemeProviderDelegation(unittest.TestCase):
    def _ctx(self) -> ProviderContext:
        return ProviderContext(
            query="Can I get details about Udyogini Scheme?",
            search_query="Udyogini Scheme",
            live_request_id="ms-delegate",
            overall_deadline=time.time() + 120,
            per_source_timeout=25.0,
        )

    def test_run_requires_service(self):
        out = MySchemeProvider().run(self._ctx(), service=None)
        self.assertEqual(out.status, ProviderPhaseStatus.ERROR)
        self.assertIn("no_service", out.failure_codes)

    @patch("app.services.live_gov_retrieval_service.discover_seed_urls")
    def test_run_failed_when_no_seeds(self, mock_seeds):
        mock_seeds.return_value = []
        svc = MagicMock()
        out = MySchemeProvider().run(self._ctx(), service=svc)
        self.assertFalse(out.evidence_ready)
        self.assertEqual(out.meta.get("outcome"), "failed")
        svc.discover_candidate_pages.assert_not_called()

    @patch("app.services.live_gov_retrieval_service.select_best_candidates")
    @patch("app.services.live_gov_retrieval_service.discover_seed_urls")
    def test_run_sufficient_when_ingest_probe_passes(self, mock_seeds, mock_select):
        mock_seeds.return_value = [{"url": "https://www.myscheme.gov.in/schemes/us", "kind": "scheme_page"}]
        ranked = [
            {
                "url": "https://www.myscheme.gov.in/schemes/us",
                "kind": "scheme_page",
                "scheme_id": "us",
                "scheme_name": "Udyogini Scheme",
                "content": b"SECTION:\nEligibility\n\nCONTENT:\nWomen entrepreneurs.",
            }
        ]
        mock_select.return_value = ranked
        svc = MagicMock()
        svc.discover_candidate_pages.return_value = ranked
        svc._ingest_ranked_until_sufficient.return_value = {
            "evidence_ready": True,
            "accepted_url": "https://www.myscheme.gov.in/schemes/us",
            "index_stats": {"chunk_count": 3},
            "candidates_tried": 1,
            "pdfs_used": 0,
        }
        ctx = self._ctx()
        out = MySchemeProvider().run(ctx, service=svc)
        self.assertEqual(out.status, ProviderPhaseStatus.SUFFICIENT)
        self.assertTrue(out.evidence_ready)
        self.assertEqual(out.accepted_url, "https://www.myscheme.gov.in/schemes/us")
        svc._ingest_ranked_until_sufficient.assert_called_once()
        self.assertEqual(svc._ingest_ranked_until_sufficient.call_args.kwargs.get("phase"), "myscheme")

    @patch("app.services.live_gov_retrieval_service.select_best_candidates")
    @patch("app.services.live_gov_retrieval_service.discover_seed_urls")
    def test_run_partial_when_ingested_but_not_sufficient(self, mock_seeds, mock_select):
        mock_seeds.return_value = [{"url": "https://www.myscheme.gov.in/schemes/us"}]
        ranked = [{"url": "https://www.myscheme.gov.in/schemes/us", "kind": "scheme_page"}]
        mock_select.return_value = ranked
        svc = MagicMock()
        svc.discover_candidate_pages.return_value = ranked

        def _ingest(ranked_in, *, ingested, **kwargs):
            ingested.append({"source_url": "https://www.myscheme.gov.in/schemes/us", "status": "ok"})
            return {"evidence_ready": False, "candidates_tried": 1, "pdfs_used": 0}

        svc._ingest_ranked_until_sufficient.side_effect = _ingest
        out = MySchemeProvider().run(self._ctx(), service=svc)
        self.assertEqual(out.status, ProviderPhaseStatus.INSUFFICIENT)
        self.assertFalse(out.evidence_ready)
        self.assertEqual(out.meta.get("outcome"), "partial")
        self.assertGreaterEqual(out.ingested_count, 1)


class TestMySchemeProviderGranular(unittest.TestCase):
    def _ctx(self) -> ProviderContext:
        return ProviderContext(
            query="Udyogini eligibility",
            search_query="Udyogini eligibility",
            live_request_id="ms-granular",
            overall_deadline=time.time() + 120,
            per_source_timeout=25.0,
        )

    def test_resolve_identity_rejects_wrong_scheme(self):
        p = MySchemeProvider()
        cand = SchemeCandidate(
            url="https://www.myscheme.gov.in/schemes/pmsby",
            scheme_id="pmsby",
            scheme_name="Pradhan Mantri Suraksha Bima Yojana",
        )
        result = p.resolve_identity(cand, "Udyogini eligibility", context=self._ctx())
        self.assertFalse(result.accepted)
        self.assertEqual(result.reason, "SCHEME_IDENTITY_MISMATCH")

    def test_extract_rejects_url_only(self):
        p = MySchemeProvider()
        cand = SchemeCandidate(
            url="https://www.myscheme.gov.in/schemes/foo",
            content=b"",
        )
        ev = p.extract(cand, query="What is foo?", context=self._ctx())
        self.assertFalse(ev.ok)
        self.assertFalse(extracted_evidence_is_usable(ev))

    def test_extract_fixture_html(self):
        html = FIXTURE.read_text(encoding="utf-8")
        p = MySchemeProvider()
        cand = _dict_to_candidate(
            {
                "url": "https://www.myscheme.gov.in/schemes/us",
                "scheme_name": "Udyogini Scheme",
                "kind": "scheme_page",
                "content": html.encode("utf-8"),
            }
        )
        ev = p.extract(cand, query="Who is eligible for Udyogini?", context=self._ctx())
        self.assertTrue(ev.ok)
        self.assertTrue(extracted_evidence_is_usable(ev))
        self.assertIn("eligibility", " ".join(ev.sections.keys()).lower() + ev.content.lower())

    @patch("app.services.live_gov_retrieval_service.discover_seed_urls")
    def test_discover_delegates_to_live_service(self, mock_seeds):
        mock_seeds.return_value = [{"url": "https://www.myscheme.gov.in/search", "kind": "search"}]
        svc = MagicMock()
        svc.discover_candidate_pages.return_value = [
            {
                "url": "https://www.myscheme.gov.in/schemes/us",
                "kind": "scheme_page",
                "scheme_id": "us",
            }
        ]
        with patch(
            "app.services.live_gov_retrieval_service.select_best_candidates",
            return_value=svc.discover_candidate_pages.return_value,
        ):
            found = MySchemeProvider().discover("Udyogini", context=self._ctx(), service=svc)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].scheme_id, "us")
        svc.discover_candidate_pages.assert_called_once()


class TestMySchemeProviderRegistryIntegration(unittest.TestCase):
    @patch("app.services.live_gov_retrieval_service.discover_seed_urls")
    def test_registry_short_circuits_on_myscheme_sufficient(self, mock_seeds):
        mock_seeds.return_value = [{"url": "https://www.myscheme.gov.in/schemes/us"}]
        svc = MagicMock()
        svc.discover_candidate_pages.return_value = [
            {"url": "https://www.myscheme.gov.in/schemes/us", "kind": "scheme_page"}
        ]
        svc._ingest_ranked_until_sufficient.return_value = {
            "evidence_ready": True,
            "accepted_url": "https://www.myscheme.gov.in/schemes/us",
        }
        with patch(
            "app.services.live_gov_retrieval_service.select_best_candidates",
            return_value=svc.discover_candidate_pages.return_value,
        ):
            ctx = ProviderContext(
                query="Udyogini eligibility",
                search_query="Udyogini eligibility",
                live_request_id="reg-ms",
                overall_deadline=time.time() + 120,
                per_source_timeout=25.0,
            )
            reg = ProviderRegistry([MySchemeProvider()])
            chain = reg.run_chain(ctx, service=svc)
        self.assertTrue(chain.evidence_ready)
        self.assertEqual(chain.final_provider, "myscheme")


if __name__ == "__main__":
    unittest.main()
