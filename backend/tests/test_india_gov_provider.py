"""Stage 4 — India.gov.in provider tests."""

from __future__ import annotations

import time
import unittest
from unittest.mock import MagicMock, patch

from app.core.config import settings
from app.services.providers import (
    IndiaGovProvider,
    MySchemeProvider,
    ProviderContext,
    ProviderPhaseStatus,
    ProviderRegistry,
    RegistryGovernmentProvider,
    build_default_registry,
    extracted_evidence_is_usable,
)
from app.services.providers.india_gov_provider import (
    _looks_like_search_shell,
    build_india_gov_seeds_for_query,
    is_india_gov_url,
)
from app.services.providers.myscheme_provider import _dict_to_candidate


class TestIndiaGovHelpers(unittest.TestCase):
    def test_is_india_gov_url(self):
        self.assertTrue(is_india_gov_url("https://www.india.gov.in/spotlight/foo"))
        self.assertFalse(is_india_gov_url("https://pmkisan.gov.in/"))

    def test_search_shell_rejected(self):
        shell = b"<html><body><form name='keys'>Search results</form></body></html>"
        self.assertTrue(
            _looks_like_search_shell("https://www.india.gov.in/search/node?keys=foo", shell)
        )

    def test_url_only_not_usable(self):
        from app.services.providers.base import ExtractedEvidence

        ev = ExtractedEvidence(
            ok=True,
            content="https://www.india.gov.in/schemes/foo",
            source_url="https://www.india.gov.in/schemes/foo",
        )
        self.assertFalse(extracted_evidence_is_usable(ev))

    @patch("app.services.live_gov_retrieval_service.verify_source", return_value=True)
    def test_build_seeds_includes_registry_search_and_catalog(self, _verify):
        with patch(
            "app.services.live_gov_retrieval_service.match_catalog_schemes",
            return_value=[
                {
                    "name": "Ayushman Bharat",
                    "urls": ["https://www.india.gov.in/spotlight/ayushman-bharat"],
                }
            ],
        ):
            seeds = build_india_gov_seeds_for_query(
                "Ayushman Bharat benefits",
                verify_fn=lambda u: True,
                limit=6,
            )
        urls = [s["url"] for s in seeds]
        self.assertTrue(any("india.gov.in" in u for u in urls))
        self.assertTrue(any("/search/node" in u for u in urls))


class TestIndiaGovProvider(unittest.TestCase):
    def _ctx(self) -> ProviderContext:
        return ProviderContext(
            query="PM-KISAN eligibility",
            search_query="PM-KISAN eligibility",
            live_request_id="in-test",
            overall_deadline=time.time() + 120,
            per_source_timeout=25.0,
            extra={"all_ranked": [], "pdfs_used": 0, "myscheme_phase_used": True},
        )

    def test_provider_order(self):
        reg = build_default_registry()
        self.assertEqual(
            reg.provider_names,
            ["myscheme", "india_gov", "data_gov", "registry_government"],
        )

    def test_cross_scheme_rejected(self):
        p = IndiaGovProvider()
        wrong = _dict_to_candidate(
            {
                "url": "https://www.india.gov.in/spotlight/udyogini",
                "scheme_name": "Udyogini Scheme",
                "scheme_id": "udyogini",
            }
        )
        ident = p.resolve_identity(wrong, "PM-KISAN eligibility", context=self._ctx())
        self.assertFalse(ident.accepted)

    def test_correct_scheme_accepted(self):
        p = IndiaGovProvider()
        right = _dict_to_candidate(
            {
                "url": "https://www.india.gov.in/spotlight/pm-kisan",
                "scheme_name": "PM-KISAN",
                "scheme_id": "pmkisan",
            }
        )
        ident = p.resolve_identity(right, "PM-KISAN eligibility", context=self._ctx())
        self.assertTrue(ident.accepted)

    def test_extract_rejects_search_shell(self):
        p = IndiaGovProvider()
        shell = _dict_to_candidate(
            {
                "url": "https://www.india.gov.in/search/node?keys=foo",
                "content": b"<html><form name='keys'>Search results</form></html>",
            }
        )
        ev = p.extract(shell, query="PM-KISAN", context=self._ctx())
        self.assertFalse(ev.ok)
        self.assertEqual(ev.reason, "search_shell_or_empty")

    @patch("app.services.providers.india_gov_provider.build_india_gov_seeds_for_query")
    def test_run_sufficient(self, mock_seeds):
        mock_seeds.return_value = [{"url": "https://www.india.gov.in/spotlight/pm-kisan", "source": "india_gov"}]
        ranked = [
            {
                "url": "https://www.india.gov.in/spotlight/pm-kisan",
                "kind": "html",
                "content": (
                    b"<html><body><h2>Benefits</h2><p>PM-KISAN provides income support "
                    b"to eligible landholding farmer families across India.</p>"
                    b"<h2>Eligibility</h2><p>Landholding farmers may apply subject to rules.</p>"
                    b"</body></html>"
                ),
                "scheme_name": "PM-KISAN",
            }
        ]
        svc = MagicMock()
        svc.discover_candidate_pages.return_value = ranked
        svc._ingest_ranked_until_sufficient.return_value = {
            "evidence_ready": True,
            "accepted_url": ranked[0]["url"],
            "candidates_tried": 1,
        }
        with patch(
            "app.services.live_gov_retrieval_service.select_best_candidates",
            return_value=ranked,
        ):
            out = IndiaGovProvider().run(self._ctx(), service=svc)
        self.assertEqual(out.status, ProviderPhaseStatus.SUFFICIENT)
        self.assertTrue(out.evidence_ready)
        self.assertEqual(svc._ingest_ranked_until_sufficient.call_args.kwargs.get("phase"), "india_gov")

    @patch("app.services.providers.india_gov_provider.build_india_gov_seeds_for_query")
    def test_pdf_url_preserved_in_candidate(self, mock_seeds):
        mock_seeds.return_value = [{"url": "https://www.india.gov.in/", "source": "india_gov"}]
        pdf_url = "https://www.india.gov.in/sites/default/files/scheme-guidelines.pdf"
        ranked = [
            {
                "url": pdf_url,
                "kind": "pdf",
                "content": b"%PDF-1.4 PM-KISAN eligibility guidelines for farmers",
                "scheme_name": "PM-KISAN",
            }
        ]
        svc = MagicMock()
        svc.discover_candidate_pages.return_value = ranked

        def _ingest(ranked_in, *, ingested, **kwargs):
            ingested.append({"source_url": pdf_url, "status": "ok"})
            return {"evidence_ready": True, "accepted_url": pdf_url, "pdfs_used": 1}

        svc._ingest_ranked_until_sufficient.side_effect = _ingest
        with patch(
            "app.services.live_gov_retrieval_service.select_best_candidates",
            return_value=ranked,
        ):
            out = IndiaGovProvider().run(self._ctx(), service=svc)
        self.assertTrue(out.evidence_ready)
        self.assertEqual(out.accepted_url, pdf_url)

    @patch("app.services.providers.india_gov_provider.build_india_gov_seeds_for_query")
    def test_sha256_duplicate_reuses_existing(self, mock_seeds):
        mock_seeds.return_value = [{"url": "https://www.india.gov.in/", "source": "india_gov"}]
        pdf_url = "https://www.india.gov.in/sites/default/files/pm-kisan.pdf"
        ranked = [{"url": pdf_url, "kind": "pdf", "content": b"%PDF", "scheme_name": "PM-KISAN"}]
        svc = MagicMock()
        svc.discover_candidate_pages.return_value = ranked

        def _ingest(ranked_in, *, ingested, **kwargs):
            ingested.append({"source_url": pdf_url, "status": "ok", "reason": "duplicate"})
            return {"evidence_ready": True, "accepted_url": pdf_url, "via": "duplicate"}

        svc._ingest_ranked_until_sufficient.side_effect = _ingest
        with patch(
            "app.services.live_gov_retrieval_service.select_best_candidates",
            return_value=ranked,
        ):
            out = IndiaGovProvider().run(self._ctx(), service=svc)
        self.assertTrue(out.evidence_ready)
        self.assertEqual(out.accepted_url, pdf_url)
        self.assertGreaterEqual(out.ingested_count, 1)

    @patch("app.services.providers.india_gov_provider.build_india_gov_seeds_for_query")
    def test_captcha_blocked_does_not_bypass(self, mock_seeds):
        mock_seeds.return_value = [{"url": "https://www.india.gov.in/", "source": "india_gov"}]
        svc = MagicMock()
        svc.discover_candidate_pages.return_value = [
            {
                "url": "https://www.india.gov.in/spotlight/pm-kisan",
                "content": b"",
                "acquisition_health": {"status": "captcha_blocked"},
            }
        ]
        svc._ingest_ranked_until_sufficient.return_value = {
            "evidence_ready": False,
            "candidates_tried": 1,
        }
        with patch(
            "app.services.live_gov_retrieval_service.select_best_candidates",
            side_effect=lambda c, q, **kw: c,
        ):
            out = IndiaGovProvider().run(self._ctx(), service=svc)
        self.assertFalse(out.evidence_ready)
        self.assertNotEqual(out.status, ProviderPhaseStatus.SUFFICIENT)


class TestIndiaGovChainIntegration(unittest.TestCase):
    def _ctx(self) -> ProviderContext:
        return ProviderContext(
            query="PM-KISAN benefits",
            search_query="PM-KISAN benefits",
            live_request_id="chain-in",
            overall_deadline=time.time() + 120,
            per_source_timeout=25.0,
            extra={"wall_start": time.time(), "all_ranked": [], "pdfs_used": 0},
        )

    @patch("app.services.live_gov_retrieval_service.discover_seed_urls")
    @patch("app.services.providers.india_gov_provider.build_india_gov_seeds_for_query")
    def test_myscheme_sufficient_skips_india_gov(self, mock_in_seeds, mock_disc_seeds):
        mock_disc_seeds.return_value = [{"url": "https://www.myscheme.gov.in/schemes/pm-kisan"}]
        mock_in_seeds.return_value = [{"url": "https://www.india.gov.in/"}]
        svc = MagicMock()
        ms = [{"url": "https://www.myscheme.gov.in/schemes/pm-kisan", "kind": "scheme_page"}]
        svc.discover_candidate_pages.return_value = ms
        svc._ingest_ranked_until_sufficient.return_value = {
            "evidence_ready": True,
            "accepted_url": ms[0]["url"],
        }
        with patch(
            "app.services.live_gov_retrieval_service.select_best_candidates",
            return_value=ms,
        ):
            chain = build_default_registry().run_chain(self._ctx(), service=svc)
        self.assertTrue(chain.evidence_ready)
        self.assertEqual(chain.final_provider, "myscheme")
        self.assertEqual(len(chain.provider_results), 1)
        mock_in_seeds.assert_not_called()

    @patch("app.services.live_gov_retrieval_service.discover_seed_urls")
    @patch("app.services.providers.india_gov_provider.build_india_gov_seeds_for_query")
    def test_myscheme_insufficient_calls_india_gov(self, mock_in_seeds, mock_disc_seeds):
        mock_disc_seeds.side_effect = lambda q, **kw: (
            [{"url": "https://www.myscheme.gov.in/schemes/pm-kisan"}]
            if kw.get("phase") == "myscheme"
            else [{"url": "https://pmkisan.gov.in/x"}]
        )
        mock_in_seeds.return_value = [{"url": "https://www.india.gov.in/spotlight/pm-kisan"}]
        svc = MagicMock()
        ms = [{"url": "https://www.myscheme.gov.in/schemes/pm-kisan"}]
        ig = [
            {
                "url": "https://www.india.gov.in/spotlight/pm-kisan",
                "content": b"<p>PM-KISAN benefits for eligible farmers across India.</p>" * 5,
            }
        ]

        def discover_side(q, **kwargs):
            seeds = kwargs.get("seeds") or []
            if seeds and all("myscheme" in (s.get("url") or "") for s in seeds):
                return ms
            if seeds and all("india.gov.in" in (s.get("url") or "") for s in seeds):
                return ig
            return []

        svc.discover_candidate_pages.side_effect = discover_side

        def ingest_side(ranked, *, ingested, phase, **kwargs):
            ingested.append({"source_url": ranked[0]["url"], "phase": phase})
            if phase == "india_gov":
                return {"evidence_ready": True, "accepted_url": ranked[0]["url"]}
            return {"evidence_ready": False}

        svc._ingest_ranked_until_sufficient.side_effect = ingest_side

        with patch(
            "app.services.live_gov_retrieval_service.select_best_candidates",
            side_effect=lambda c, q, **kw: c,
        ):
            chain = build_default_registry().run_chain(self._ctx(), service=svc)
        self.assertTrue(chain.evidence_ready)
        self.assertEqual(chain.final_provider, "india_gov")
        self.assertEqual(len(chain.provider_results), 2)

    @patch("app.services.live_gov_retrieval_service.discover_seed_urls")
    @patch("app.services.providers.india_gov_provider.build_india_gov_seeds_for_query")
    def test_india_gov_sufficient_skips_registry(self, mock_in_seeds, mock_disc_seeds):
        mock_disc_seeds.return_value = []
        mock_in_seeds.return_value = [{"url": "https://www.india.gov.in/"}]
        svc = MagicMock()
        ig = [{"url": "https://www.india.gov.in/spotlight/x", "content": b"<p>benefits</p>" * 20}]
        svc.discover_candidate_pages.return_value = ig
        svc._ingest_ranked_until_sufficient.return_value = {
            "evidence_ready": True,
            "accepted_url": ig[0]["url"],
        }
        with patch(
            "app.services.live_gov_retrieval_service.select_best_candidates",
            return_value=ig,
        ):
            with patch.object(MySchemeProvider, "run") as mock_ms:
                mock_ms.return_value = MagicMock(
                    provider="myscheme",
                    status=ProviderPhaseStatus.INSUFFICIENT,
                    evidence_ready=False,
                    ingested_count=0,
                    failure_codes=[],
                    meta={"outcome": "failed"},
                )
                chain = ProviderRegistry(
                    [MySchemeProvider(), IndiaGovProvider(), RegistryGovernmentProvider()]
                ).run_chain(self._ctx(), service=svc)
        self.assertTrue(chain.evidence_ready)
        self.assertEqual(chain.final_provider, "india_gov")
        self.assertEqual(len(chain.provider_results), 2)

    @patch("app.services.live_gov_retrieval_service.discover_seed_urls")
    @patch("app.services.providers.india_gov_provider.build_india_gov_seeds_for_query")
    def test_india_gov_failed_registry_called(self, mock_in_seeds, mock_disc_seeds):
        mock_in_seeds.return_value = []
        mock_disc_seeds.return_value = [{"url": "https://pmkisan.gov.in/page"}]
        svc = MagicMock()
        fb = [{"url": "https://pmkisan.gov.in/b.pdf", "kind": "pdf", "content": b"%PDF"}]

        def discover_side(q, **kwargs):
            if kwargs.get("seeds"):
                return fb
            return []

        svc.discover_candidate_pages.side_effect = discover_side

        def ingest_side(ranked, *, ingested, phase, **kwargs):
            ingested.append({"source_url": ranked[0]["url"], "phase": phase})
            if phase == "fallback":
                return {"evidence_ready": True, "accepted_url": ranked[0]["url"]}
            return {"evidence_ready": False}

        svc._ingest_ranked_until_sufficient.side_effect = ingest_side

        with patch(
            "app.services.live_gov_retrieval_service.select_best_candidates",
            side_effect=lambda c, q, **kw: c,
        ):
            with patch.object(MySchemeProvider, "run") as mock_ms:
                mock_ms.return_value = MagicMock(
                    provider="myscheme",
                    status=ProviderPhaseStatus.INSUFFICIENT,
                    evidence_ready=False,
                    ingested_count=0,
                    failure_codes=[],
                    meta={"outcome": "failed"},
                )
                chain = build_default_registry().run_chain(self._ctx(), service=svc)
        self.assertTrue(chain.evidence_ready)
        self.assertEqual(chain.final_provider, "registry_government")
        self.assertEqual(len(chain.provider_results), 4)

    def test_disabled_provider_skipped(self):
        settings.INDIAGOV_PROVIDER_ENABLED = False
        try:
            p = IndiaGovProvider()
            self.assertFalse(p.supports("PM-KISAN", context=self._ctx()))
        finally:
            settings.INDIAGOV_PROVIDER_ENABLED = True

    @patch("app.services.live_gov_retrieval_service.discover_seed_urls")
    @patch("app.services.providers.india_gov_provider.build_india_gov_seeds_for_query")
    def test_india_gov_insufficient_registry_called(self, mock_in_seeds, mock_disc_seeds):
        mock_in_seeds.return_value = [{"url": "https://www.india.gov.in/"}]
        mock_disc_seeds.return_value = [{"url": "https://pmkisan.gov.in/page"}]
        svc = MagicMock()
        ig = [{"url": "https://www.india.gov.in/search/node?keys=x", "content": b"search results"}]
        fb = [{"url": "https://pmkisan.gov.in/b.pdf", "kind": "pdf", "content": b"%PDF PM-KISAN"}]

        def discover_side(q, **kwargs):
            seeds = kwargs.get("seeds") or []
            if seeds and all("india.gov.in" in (s.get("url") or "") for s in seeds):
                return ig
            if seeds:
                return fb
            return []

        svc.discover_candidate_pages.side_effect = discover_side

        def ingest_side(ranked, *, ingested, phase, **kwargs):
            if phase == "fallback":
                ingested.append({"source_url": ranked[0]["url"], "status": "ok"})
                return {"evidence_ready": True, "accepted_url": ranked[0]["url"]}
            return {"evidence_ready": False}

        svc._ingest_ranked_until_sufficient.side_effect = ingest_side

        with patch(
            "app.services.live_gov_retrieval_service.select_best_candidates",
            side_effect=lambda c, q, **kw: c,
        ):
            with patch.object(MySchemeProvider, "run") as mock_ms:
                mock_ms.return_value = MagicMock(
                    provider="myscheme",
                    status=ProviderPhaseStatus.INSUFFICIENT,
                    evidence_ready=False,
                    ingested_count=0,
                    failure_codes=[],
                    meta={"outcome": "failed"},
                )
                chain = build_default_registry().run_chain(self._ctx(), service=svc)
        self.assertTrue(chain.evidence_ready)
        self.assertEqual(chain.final_provider, "registry_government")
        self.assertEqual(len(chain.provider_results), 4)


class TestIndiaGovSecurityAndLanguage(unittest.TestCase):
    def test_untrusted_redirect_rejected_in_seeds(self):
        seeds = build_india_gov_seeds_for_query(
            "PM-KISAN",
            verify_fn=lambda u: "evil.com" not in u and is_india_gov_url(u),
            limit=6,
        )
        urls = [s["url"] for s in seeds]
        self.assertFalse(any("evil.com" in u for u in urls))

    def test_kannada_query_supported(self):
        p = IndiaGovProvider()
        ctx = ProviderContext(
            query="ಪಿಎಂ ಕಿಸಾನ್ ಅರ್ಹತೆ",
            search_query="ಪಿಎಂ ಕಿಸಾನ್ ಅರ್ಹತೆ pm-kisan eligibility",
            live_request_id="kn",
            overall_deadline=time.time() + 60,
            per_source_timeout=25.0,
            extra={},
        )
        self.assertTrue(p.supports("ಪಿಎಂ ಕಿಸಾನ್ ಅರ್ಹತೆ", context=ctx))

    def test_hindi_query_supported(self):
        p = IndiaGovProvider()
        ctx = ProviderContext(
            query="पीएम किसान पात्रता",
            search_query="पीएम किसान पात्रता pm-kisan eligibility",
            live_request_id="hi",
            overall_deadline=time.time() + 60,
            per_source_timeout=25.0,
            extra={},
        )
        self.assertTrue(p.supports("पीएम किसान पात्रता", context=ctx))

    def test_english_query_supported(self):
        p = IndiaGovProvider()
        ctx = ProviderContext(
            query="PM-KISAN eligibility",
            search_query="PM-KISAN eligibility",
            live_request_id="en",
            overall_deadline=time.time() + 60,
            per_source_timeout=25.0,
            extra={},
        )
        self.assertTrue(p.supports("PM-KISAN eligibility", context=ctx))


if __name__ == "__main__":
    unittest.main()
