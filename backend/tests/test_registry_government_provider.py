"""Stage 3 — registry government provider tests."""

from __future__ import annotations

import time
import unittest
from unittest.mock import MagicMock, patch

from app.services.providers import (
    MySchemeProvider,
    ProviderContext,
    ProviderPhaseStatus,
    ProviderRegistry,
    RegistryGovernmentProvider,
)


class TestRegistryGovernmentProvider(unittest.TestCase):
    def _ctx(self, *, myscheme_used: bool = True) -> ProviderContext:
        return ProviderContext(
            query="PM-KISAN eligibility benefits",
            search_query="PM-KISAN eligibility benefits",
            live_request_id="reg-test",
            overall_deadline=time.time() + 120,
            per_source_timeout=25.0,
            extra={"myscheme_phase_used": myscheme_used, "all_ranked": [], "pdfs_used": 0},
        )

    def test_supports_always_true_in_chain(self):
        p = RegistryGovernmentProvider()
        self.assertTrue(p.supports("anything", context=self._ctx()))

    def test_run_requires_service(self):
        out = RegistryGovernmentProvider().run(self._ctx(), service=None)
        self.assertEqual(out.status, ProviderPhaseStatus.ERROR)

    @patch("app.services.live_gov_retrieval_service.discover_seed_urls")
    def test_run_no_seeds_after_myscheme(self, mock_seeds):
        mock_seeds.return_value = []
        svc = MagicMock()
        ctx = self._ctx(myscheme_used=True)
        out = RegistryGovernmentProvider().run(ctx, service=svc)
        self.assertFalse(out.evidence_ready)
        svc.discover_candidate_pages.assert_not_called()

    @patch("app.services.live_gov_retrieval_service.select_best_candidates")
    @patch("app.services.live_gov_retrieval_service.discover_seed_urls")
    def test_run_sufficient_via_fallback_seeds(self, mock_seeds, mock_select):
        mock_seeds.return_value = [{"url": "https://pmkisan.gov.in/page", "scheme_name": "PM-KISAN"}]
        ranked = [
            {
                "url": "https://pmkisan.gov.in/benefits.pdf",
                "kind": "pdf",
                "content": b"%PDF-1.4 PM-KISAN benefits eligibility",
                "scheme_name": "PM-KISAN",
            }
        ]
        mock_select.return_value = ranked
        svc = MagicMock()
        svc.discover_candidate_pages.return_value = ranked
        svc._ingest_ranked_until_sufficient.return_value = {
            "evidence_ready": True,
            "accepted_url": ranked[0]["url"],
            "candidates_tried": 1,
            "pdfs_used": 1,
        }

        def _ingest(ranked_in, *, ingested, **kwargs):
            ingested.append({"source_url": ranked[0]["url"], "status": "ok"})
            return svc._ingest_ranked_until_sufficient.return_value

        svc._ingest_ranked_until_sufficient.side_effect = _ingest
        out = RegistryGovernmentProvider().run(self._ctx(), service=svc)
        self.assertEqual(out.status, ProviderPhaseStatus.SUFFICIENT)
        self.assertTrue(out.evidence_ready)
        self.assertEqual(svc._ingest_ranked_until_sufficient.call_args.kwargs.get("phase"), "fallback")

    @patch("app.services.live_gov_retrieval_service.select_best_candidates")
    @patch("app.services.live_gov_retrieval_service.discover_seed_urls")
    def test_legacy_discovery_when_myscheme_not_used(self, mock_seeds, mock_select):
        mock_seeds.return_value = []
        ranked = [{"url": "https://pmkisan.gov.in/x", "kind": "html"}]
        mock_select.return_value = ranked
        svc = MagicMock()
        svc.discover_candidate_pages.return_value = ranked
        svc._ingest_ranked_until_sufficient.return_value = {"evidence_ready": False, "candidates_tried": 1}
        RegistryGovernmentProvider().run(self._ctx(myscheme_used=False), service=svc)
        svc.discover_candidate_pages.assert_called_once()
        self.assertIsNone(svc.discover_candidate_pages.call_args.kwargs.get("seeds"))


class TestProviderChainIntegration(unittest.TestCase):
    def _ctx(self) -> ProviderContext:
        return ProviderContext(
            query="Udyogini eligibility",
            search_query="Udyogini eligibility",
            live_request_id="chain-int",
            overall_deadline=time.time() + 120,
            per_source_timeout=25.0,
            extra={"wall_start": time.time(), "all_ranked": [], "pdfs_used": 0},
        )

    @patch("app.services.live_gov_retrieval_service.discover_seed_urls")
    def test_myscheme_sufficient_skips_registry(self, mock_seeds):
        mock_seeds.side_effect = lambda q, **kw: (
            [{"url": "https://www.myscheme.gov.in/schemes/us", "kind": "scheme_page"}]
            if kw.get("phase") == "myscheme"
            else [{"url": "https://pmkisan.gov.in/x"}]
        )
        svc = MagicMock()
        ranked_ms = [{"url": "https://www.myscheme.gov.in/schemes/us", "kind": "scheme_page"}]
        svc.discover_candidate_pages.return_value = ranked_ms
        svc._ingest_ranked_until_sufficient.return_value = {
            "evidence_ready": True,
            "accepted_url": ranked_ms[0]["url"],
        }
        with patch(
            "app.services.live_gov_retrieval_service.select_best_candidates",
            return_value=ranked_ms,
        ):
            reg = ProviderRegistry([MySchemeProvider(), RegistryGovernmentProvider()])
            chain = reg.run_chain(self._ctx(), service=svc)
        self.assertTrue(chain.evidence_ready)
        self.assertEqual(chain.final_provider, "myscheme")
        self.assertEqual(len(chain.provider_results), 1)

    @patch("app.services.live_gov_retrieval_service.discover_seed_urls")
    def test_myscheme_insufficient_calls_registry(self, mock_seeds):
        def seeds_side(q, **kw):
            if kw.get("phase") == "myscheme":
                return [{"url": "https://www.myscheme.gov.in/schemes/us"}]
            return [{"url": "https://pmkisan.gov.in/page", "scheme_name": "PM-KISAN"}]

        mock_seeds.side_effect = seeds_side
        svc = MagicMock()
        ms_ranked = [{"url": "https://www.myscheme.gov.in/schemes/us", "kind": "scheme_page"}]
        fb_ranked = [{"url": "https://pmkisan.gov.in/b.pdf", "kind": "pdf", "content": b"%PDF"}]

        def discover_side(q, **kwargs):
            if kwargs.get("seeds") and all(
                "myscheme.gov.in" in (s.get("url") or "") for s in kwargs["seeds"]
            ):
                return ms_ranked
            return fb_ranked

        svc.discover_candidate_pages.side_effect = discover_side

        def ingest_side(ranked, *, ingested, phase, **kwargs):
            ingested.append({"source_url": ranked[0]["url"], "status": "ok", "phase": phase})
            if phase == "fallback":
                return {"evidence_ready": True, "accepted_url": ranked[0]["url"]}
            return {"evidence_ready": False, "candidates_tried": 1}

        svc._ingest_ranked_until_sufficient.side_effect = ingest_side

        def select_side(cands, q, **kw):
            return cands

        with patch(
            "app.services.live_gov_retrieval_service.select_best_candidates",
            side_effect=select_side,
        ):
            chain = ProviderRegistry(
                [MySchemeProvider(), RegistryGovernmentProvider()]
            ).run_chain(self._ctx(), service=svc)
        self.assertTrue(chain.evidence_ready)
        self.assertEqual(chain.final_provider, "registry_government")
        self.assertEqual(len(chain.provider_results), 2)

    @patch("app.services.live_gov_retrieval_service.discover_seed_urls")
    def test_both_fail_preserves_insufficient_chain(self, mock_seeds):
        mock_seeds.return_value = []
        svc = MagicMock()
        chain = ProviderRegistry(
            [MySchemeProvider(), RegistryGovernmentProvider()]
        ).run_chain(self._ctx(), service=svc)
        self.assertFalse(chain.evidence_ready)
        self.assertIsNone(chain.final_provider)

    def test_cross_scheme_identity_rejected(self):
        from app.services.providers.myscheme_provider import _dict_to_candidate

        p = RegistryGovernmentProvider()
        ctx = self._ctx()
        wrong = _dict_to_candidate(
            {
                "url": "https://www.myscheme.gov.in/schemes/pmkisan",
                "scheme_id": "pmkisan",
                "scheme_name": "PM-KISAN",
            }
        )
        ident = p.resolve_identity(wrong, "Udyogini eligibility", context=ctx)
        self.assertFalse(ident.accepted)

    @patch("app.services.providers.live_integration.search_via_provider_registry")
    def test_search_government_sources_uses_registry_when_enabled(self, mock_via):
        from app.services.live_gov_retrieval_service import LiveGovRetrievalService

        mock_via.return_value = {
            "status": "LIVE_DOCUMENT_INGESTED",
            "evidence_ready": True,
            "ingested": [{"source_url": "https://www.myscheme.gov.in/schemes/us"}],
            "provider_registry": True,
            "final_provider": "myscheme",
            "live_request_id": "x",
            "latency_ms": 1,
        }

        db = MagicMock()
        svc = LiveGovRetrievalService(db)
        out = svc.search_government_sources("What is PM-KISAN?")
        mock_via.assert_called_once()
        self.assertTrue(out.get("provider_registry"))

    @patch("app.services.providers.live_integration.search_via_provider_registry")
    def test_legacy_path_when_registry_disabled(self, mock_via_registry):
        from app.core.config import settings
        from app.services.live_gov_retrieval_service import LiveGovRetrievalService

        settings.LIVE_GOV_PROVIDER_REGISTRY_ENABLED = False
        try:
            db = MagicMock()
            svc = LiveGovRetrievalService(db)
            with patch.object(svc, "discover_candidate_pages", return_value=[]):
                with patch(
                    "app.services.live_gov_retrieval_service.discover_seed_urls",
                    return_value=[],
                ):
                    svc.search_government_sources("What is PM-KISAN?")
            mock_via_registry.assert_not_called()
        finally:
            settings.LIVE_GOV_PROVIDER_REGISTRY_ENABLED = True


if __name__ == "__main__":
    unittest.main()
