"""Stage 5 — data.gov.in provider tests."""

from __future__ import annotations

import json
import time
import unittest
from unittest.mock import MagicMock, patch

from app.core.config import settings
from app.services.providers import (
    DataGovProvider,
    IndiaGovProvider,
    MySchemeProvider,
    ProviderContext,
    ProviderPhaseStatus,
    ProviderRegistry,
    RegistryGovernmentProvider,
    build_default_registry,
    extracted_evidence_is_usable,
)
from app.services.providers.data_gov_provider import (
    _candidates_from_ckan_json,
    build_data_gov_seeds_for_query,
    dataset_relevant_to_query,
    is_data_gov_url,
    package_data_gov_evidence,
)
from app.services.providers.myscheme_provider import _dict_to_candidate

PMKISAN_CKAN = {
    "success": True,
    "result": {
        "count": 2,
        "results": [
            {
                "name": "pm-kisan-eligibility-guidelines",
                "title": "PM-KISAN Eligibility and Benefits Guidelines",
                "notes": (
                    "Eligibility criteria for PM-KISAN: landholding farmer families across India. "
                    "Benefits include income support of Rs 6000 per year in three instalments. "
                    "Application procedure through PM-KISAN portal."
                ),
                "organization": {"title": "Ministry of Agriculture and Farmers Welfare"},
                "tags": [{"name": "agriculture"}, {"name": "pm-kisan"}],
                "resources": [
                    {
                        "url": "https://data.gov.in/files/pm-kisan-guidelines.pdf",
                        "format": "PDF",
                        "description": "Official PM-KISAN guidelines document",
                    }
                ],
            },
            {
                "name": "pm-kisan-beneficiary-statistics",
                "title": "PM-KISAN Beneficiary Statistics Year-wise",
                "notes": (
                    "State-wise and year-wise beneficiary count statistics for PM-KISAN programme. "
                    "Total beneficiaries registered district-wise monthly statistics."
                ),
                "organization": {"title": "Ministry of Agriculture"},
                "tags": [{"name": "statistics"}, {"name": "pm-kisan"}],
                "resources": [],
            },
        ],
    },
}


class TestDataGovHelpers(unittest.TestCase):
    def test_is_data_gov_url(self):
        self.assertTrue(is_data_gov_url("https://data.gov.in/catalog/dataset/pm-kisan"))
        self.assertFalse(is_data_gov_url("https://www.india.gov.in/"))

    def test_url_only_not_usable(self):
        from app.services.providers.base import ExtractedEvidence

        ev = ExtractedEvidence(
            ok=True,
            content="https://data.gov.in/catalog/dataset/pm-kisan",
            source_url="https://data.gov.in/catalog/dataset/pm-kisan",
        )
        self.assertFalse(extracted_evidence_is_usable(ev))

    @patch("app.services.live_gov_retrieval_service.verify_source", return_value=True)
    def test_build_seeds_includes_registry_and_search(self, _verify):
        seeds = build_data_gov_seeds_for_query(
            "PM-KISAN eligibility",
            verify_fn=lambda u: True,
            limit=6,
        )
        urls = [s["url"] for s in seeds]
        self.assertTrue(any("data.gov.in" in u for u in urls))
        self.assertTrue(any("catalog/datasets" in u or "package_search" in u for u in urls))

    def test_relevant_dataset_accepted(self):
        record = {
            "title": "PM-KISAN Eligibility Guidelines",
            "notes": (
                "Eligibility: landholding farmer families. Benefits include Rs 6000 annual "
                "income support. Documents required include land records and Aadhaar."
            ),
            "url": "https://data.gov.in/catalog/dataset/pm-kisan-eligibility",
        }
        ok, reason = dataset_relevant_to_query(record, "PM-KISAN eligibility")
        self.assertTrue(ok, reason)

    def test_irrelevant_stats_dataset_rejected_for_eligibility(self):
        record = {
            "title": "PM-KISAN Beneficiary Statistics",
            "notes": (
                "Year-wise state-wise beneficiary count statistics. Total beneficiaries "
                "registered district-wise monthly statistics only."
            ),
            "url": "https://data.gov.in/catalog/dataset/pm-kisan-stats",
        }
        ok, reason = dataset_relevant_to_query(record, "Who is eligible for PM-KISAN?")
        self.assertFalse(ok)
        self.assertIn("stats", reason.lower())

    def test_wrong_scheme_rejected(self):
        record = {
            "title": "Udyogini Scheme Guidelines",
            "scheme_id": "udyogini",
            "notes": "Eligibility for women entrepreneurs under Udyogini scheme.",
            "url": "https://data.gov.in/catalog/dataset/udyogini",
        }
        ok, _ = dataset_relevant_to_query(record, "PM-KISAN eligibility")
        self.assertFalse(ok)

    def test_structured_extraction_and_metadata(self):
        record = {
            "title": "PM-KISAN Dataset",
            "notes": "Eligibility and benefits for PM-KISAN farmers.",
            "organization": "Ministry of Agriculture",
            "state": "All India",
            "tags": ["agriculture", "pm-kisan"],
            "url": "https://data.gov.in/catalog/dataset/pm-kisan",
            "metadata": {"dataset_id": "pm-kisan", "source": "data_gov"},
        }
        packed = package_data_gov_evidence(record)
        self.assertIn("PM-KISAN Dataset", packed)
        self.assertIn("Ministry of Agriculture", packed)
        self.assertIn("eligibility", packed.lower())

    def test_ckan_json_parsing(self):
        cands = _candidates_from_ckan_json(
            json.dumps(PMKISAN_CKAN).encode(),
            "PM-KISAN eligibility",
            verify_fn=lambda u: True,
        )
        self.assertEqual(len(cands), 1)
        self.assertIn("pm-kisan-eligibility", cands[0]["url"])
        self.assertIn("metadata", cands[0])


class TestDataGovProvider(unittest.TestCase):
    def _ctx(self) -> ProviderContext:
        return ProviderContext(
            query="PM-KISAN eligibility",
            search_query="PM-KISAN eligibility",
            live_request_id="dg-test",
            overall_deadline=time.time() + 120,
            per_source_timeout=25.0,
            extra={"all_ranked": [], "pdfs_used": 0, "myscheme_phase_used": True},
        )

    def test_provider_registration_and_priority(self):
        reg = build_default_registry()
        self.assertEqual(
            reg.provider_names,
            ["myscheme", "india_gov", "data_gov", "registry_government"],
        )
        p = DataGovProvider()
        self.assertEqual(p.name, "data_gov")
        self.assertEqual(p.priority, 175)

    def test_cross_scheme_identity_rejected(self):
        wrong = _dict_to_candidate(
            {
                "url": "https://data.gov.in/catalog/dataset/udyogini",
                "scheme_name": "Udyogini Scheme",
                "scheme_id": "udyogini",
            }
        )
        ident = DataGovProvider().resolve_identity(wrong, "PM-KISAN eligibility", context=self._ctx())
        self.assertFalse(ident.accepted)

    def test_correct_scheme_identity_accepted(self):
        right = _dict_to_candidate(
            {
                "url": "https://data.gov.in/catalog/dataset/pm-kisan",
                "scheme_name": "PM-KISAN",
                "scheme_id": "pmkisan",
            }
        )
        ident = DataGovProvider().resolve_identity(right, "PM-KISAN eligibility", context=self._ctx())
        self.assertTrue(ident.accepted)

    @patch("app.services.providers.data_gov_provider.build_data_gov_seeds_for_query")
    def test_run_sufficient(self, mock_seeds):
        mock_seeds.return_value = [{"url": "https://data.gov.in/", "source": "data_gov"}]
        ranked = [
            {
                "url": "https://data.gov.in/catalog/dataset/pm-kisan-eligibility",
                "kind": "dataset",
                "content": package_data_gov_evidence(
                    {
                        "title": "PM-KISAN Eligibility",
                        "notes": "Eligibility for landholding farmers. Benefits Rs 6000.",
                        "url": "https://data.gov.in/catalog/dataset/pm-kisan-eligibility",
                    }
                ).encode(),
                "scheme_name": "PM-KISAN",
            }
        ]
        svc = MagicMock()
        svc.discover_candidate_pages.return_value = [
            {
                "url": "https://data.gov.in/api/3/action/package_search?q=pm-kisan",
                "kind": "public_api",
                "content": json.dumps(PMKISAN_CKAN).encode(),
            }
        ]
        svc._ingest_ranked_until_sufficient.return_value = {
            "evidence_ready": True,
            "accepted_url": ranked[0]["url"],
            "candidates_tried": 1,
        }
        with patch(
            "app.services.providers.data_gov_provider.discover_data_gov_candidates",
            return_value=ranked,
        ):
            out = DataGovProvider().run(self._ctx(), service=svc)
        self.assertEqual(out.status, ProviderPhaseStatus.SUFFICIENT)
        self.assertEqual(svc._ingest_ranked_until_sufficient.call_args.kwargs.get("phase"), "data_gov")

    @patch("app.services.providers.data_gov_provider.build_data_gov_seeds_for_query")
    def test_pdf_url_preserved(self, mock_seeds):
        mock_seeds.return_value = [{"url": "https://data.gov.in/", "source": "data_gov"}]
        pdf_url = "https://data.gov.in/files/pm-kisan-guidelines.pdf"
        ranked = [{"url": pdf_url, "kind": "pdf", "content": b"%PDF PM-KISAN eligibility", "scheme_name": "PM-KISAN"}]
        svc = MagicMock()

        def _ingest(ranked_in, *, ingested, **kwargs):
            ingested.append({"source_url": pdf_url, "status": "ok"})
            return {"evidence_ready": True, "accepted_url": pdf_url, "pdfs_used": 1}

        svc._ingest_ranked_until_sufficient.side_effect = _ingest
        with patch(
            "app.services.providers.data_gov_provider.discover_data_gov_candidates",
            return_value=ranked,
        ):
            out = DataGovProvider().run(self._ctx(), service=svc)
        self.assertTrue(out.evidence_ready)
        self.assertEqual(out.accepted_url, pdf_url)

    @patch("app.services.providers.data_gov_provider.build_data_gov_seeds_for_query")
    def test_sha256_duplicate_handling(self, mock_seeds):
        mock_seeds.return_value = [{"url": "https://data.gov.in/", "source": "data_gov"}]
        pdf_url = "https://data.gov.in/files/pm-kisan.pdf"
        ranked = [{"url": pdf_url, "kind": "pdf", "content": b"%PDF", "scheme_name": "PM-KISAN"}]
        svc = MagicMock()

        def _ingest(ranked_in, *, ingested, **kwargs):
            ingested.append({"source_url": pdf_url, "status": "ok", "reason": "duplicate"})
            return {"evidence_ready": True, "accepted_url": pdf_url}

        svc._ingest_ranked_until_sufficient.side_effect = _ingest
        with patch(
            "app.services.providers.data_gov_provider.discover_data_gov_candidates",
            return_value=ranked,
        ):
            out = DataGovProvider().run(self._ctx(), service=svc)
        self.assertTrue(out.evidence_ready)
        self.assertGreaterEqual(out.ingested_count, 1)

    @patch("app.services.providers.data_gov_provider.build_data_gov_seeds_for_query")
    def test_captcha_blocked_no_bypass(self, mock_seeds):
        mock_seeds.return_value = [{"url": "https://data.gov.in/", "source": "data_gov"}]
        svc = MagicMock()
        with patch(
            "app.services.providers.data_gov_provider.discover_data_gov_candidates",
            return_value=[],
        ):
            out = DataGovProvider().run(self._ctx(), service=svc)
        self.assertFalse(out.evidence_ready)


class TestDataGovChainIntegration(unittest.TestCase):
    def _ctx(self) -> ProviderContext:
        return ProviderContext(
            query="PM-KISAN benefits",
            search_query="PM-KISAN benefits",
            live_request_id="chain-dg",
            overall_deadline=time.time() + 120,
            per_source_timeout=25.0,
            extra={"wall_start": time.time(), "all_ranked": [], "pdfs_used": 0},
        )

    @patch("app.services.live_gov_retrieval_service.discover_seed_urls")
    @patch("app.services.providers.india_gov_provider.build_india_gov_seeds_for_query")
    @patch("app.services.providers.data_gov_provider.build_data_gov_seeds_for_query")
    def test_myscheme_sufficient_skips_all_downstream(
        self, mock_dg_seeds, mock_in_seeds, mock_disc_seeds
    ):
        mock_disc_seeds.return_value = [{"url": "https://www.myscheme.gov.in/schemes/pm-kisan"}]
        mock_in_seeds.return_value = [{"url": "https://www.india.gov.in/"}]
        mock_dg_seeds.return_value = [{"url": "https://data.gov.in/"}]
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
        mock_dg_seeds.assert_not_called()

    @patch("app.services.providers.data_gov_provider.build_data_gov_seeds_for_query")
    def test_india_gov_sufficient_skips_data_gov(self, mock_dg_seeds):
        mock_dg_seeds.return_value = [{"url": "https://data.gov.in/"}]
        svc = MagicMock()
        with patch.object(MySchemeProvider, "run") as mock_ms, patch.object(
            IndiaGovProvider, "run"
        ) as mock_ig:
            mock_ms.return_value = MagicMock(
                provider="myscheme",
                status=ProviderPhaseStatus.INSUFFICIENT,
                evidence_ready=False,
                ingested_count=0,
                failure_codes=[],
                meta={"outcome": "failed"},
            )
            mock_ig.return_value = MagicMock(
                provider="india_gov",
                status=ProviderPhaseStatus.SUFFICIENT,
                evidence_ready=True,
                ingested_count=0,
                accepted_url="https://www.india.gov.in/spotlight/pm-kisan",
                failure_codes=[],
                meta={"outcome": "sufficient"},
            )
            chain = build_default_registry().run_chain(self._ctx(), service=svc)
        self.assertEqual(chain.final_provider, "india_gov")
        self.assertEqual(len(chain.provider_results), 2)
        mock_dg_seeds.assert_not_called()

    @patch("app.services.live_gov_retrieval_service.discover_seed_urls")
    @patch("app.services.providers.india_gov_provider.build_india_gov_seeds_for_query")
    @patch("app.services.providers.data_gov_provider.build_data_gov_seeds_for_query")
    def test_data_gov_called_after_myscheme_and_india_fail(
        self, mock_dg_seeds, mock_in_seeds, mock_disc_seeds
    ):
        mock_dg_seeds.return_value = [{"url": "https://data.gov.in/catalog/datasets?search=pm-kisan"}]
        mock_in_seeds.return_value = [{"url": "https://www.india.gov.in/"}]
        mock_disc_seeds.return_value = [{"url": "https://pmkisan.gov.in/page"}]
        svc = MagicMock()
        dg_ranked = [
            {
                "url": "https://data.gov.in/catalog/dataset/pm-kisan-eligibility",
                "kind": "dataset",
                "content": b"<html>PM-KISAN eligibility benefits for farmers</html>" * 5,
            }
        ]

        def ingest_side(ranked, *, ingested, phase, **kwargs):
            ingested.append({"source_url": ranked[0]["url"], "phase": phase})
            if phase == "data_gov":
                return {"evidence_ready": True, "accepted_url": ranked[0]["url"]}
            return {"evidence_ready": False}

        svc._ingest_ranked_until_sufficient.side_effect = ingest_side

        with patch.object(MySchemeProvider, "run") as mock_ms, patch.object(
            IndiaGovProvider, "run"
        ) as mock_ig, patch(
            "app.services.providers.data_gov_provider.discover_data_gov_candidates",
            return_value=dg_ranked,
        ):
            mock_ms.return_value = MagicMock(
                provider="myscheme",
                status=ProviderPhaseStatus.INSUFFICIENT,
                evidence_ready=False,
                ingested_count=0,
                failure_codes=[],
                meta={"outcome": "failed"},
            )
            mock_ig.return_value = MagicMock(
                provider="india_gov",
                status=ProviderPhaseStatus.INSUFFICIENT,
                evidence_ready=False,
                ingested_count=0,
                failure_codes=[],
                meta={"outcome": "failed"},
            )
            chain = build_default_registry().run_chain(self._ctx(), service=svc)
        self.assertTrue(chain.evidence_ready)
        self.assertEqual(chain.final_provider, "data_gov")
        self.assertEqual(len(chain.provider_results), 3)

    @patch("app.services.live_gov_retrieval_service.discover_seed_urls")
    @patch("app.services.providers.data_gov_provider.build_data_gov_seeds_for_query")
    def test_data_gov_sufficient_skips_registry(self, mock_dg_seeds, mock_disc_seeds):
        mock_dg_seeds.return_value = [{"url": "https://data.gov.in/"}]
        mock_disc_seeds.return_value = [{"url": "https://pmkisan.gov.in/page"}]
        svc = MagicMock()
        dg = [{"url": "https://data.gov.in/catalog/dataset/pm-kisan", "kind": "dataset"}]
        with patch(
            "app.services.providers.data_gov_provider.discover_data_gov_candidates",
            return_value=dg,
        ):
            svc._ingest_ranked_until_sufficient.return_value = {
                "evidence_ready": True,
                "accepted_url": dg[0]["url"],
            }
            with patch.object(MySchemeProvider, "run") as mock_ms, patch.object(
                IndiaGovProvider, "run"
            ) as mock_ig:
                mock_ms.return_value = MagicMock(
                    provider="myscheme",
                    status=ProviderPhaseStatus.INSUFFICIENT,
                    evidence_ready=False,
                    ingested_count=0,
                    failure_codes=[],
                    meta={"outcome": "failed"},
                )
                mock_ig.return_value = MagicMock(
                    provider="india_gov",
                    status=ProviderPhaseStatus.INSUFFICIENT,
                    evidence_ready=False,
                    ingested_count=0,
                    failure_codes=[],
                    meta={"outcome": "failed"},
                )
                chain = build_default_registry().run_chain(self._ctx(), service=svc)
        self.assertTrue(chain.evidence_ready)
        self.assertEqual(chain.final_provider, "data_gov")
        self.assertEqual(len(chain.provider_results), 3)

    @patch("app.services.live_gov_retrieval_service.discover_seed_urls")
    @patch("app.services.providers.data_gov_provider.build_data_gov_seeds_for_query")
    def test_data_gov_insufficient_continues_to_registry(self, mock_dg_seeds, mock_disc_seeds):
        mock_dg_seeds.return_value = [{"url": "https://data.gov.in/"}]
        mock_disc_seeds.return_value = [{"url": "https://pmkisan.gov.in/page"}]
        svc = MagicMock()
        fb = [{"url": "https://pmkisan.gov.in/b.pdf", "kind": "pdf", "content": b"%PDF PM-KISAN"}]

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
            with patch.object(MySchemeProvider, "run") as mock_ms, patch.object(
                IndiaGovProvider, "run"
            ) as mock_ig, patch(
                "app.services.providers.data_gov_provider.discover_data_gov_candidates",
                return_value=[],
            ):
                mock_ms.return_value = MagicMock(
                    provider="myscheme",
                    status=ProviderPhaseStatus.INSUFFICIENT,
                    evidence_ready=False,
                    ingested_count=0,
                    failure_codes=[],
                    meta={"outcome": "failed"},
                )
                mock_ig.return_value = MagicMock(
                    provider="india_gov",
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
        settings.DATAGOV_PROVIDER_ENABLED = False
        try:
            self.assertFalse(DataGovProvider().supports("PM-KISAN", context=self._ctx()))
        finally:
            settings.DATAGOV_PROVIDER_ENABLED = True


class TestDataGovSecurityAndLanguage(unittest.TestCase):
    def test_ssrf_untrusted_domain_rejected_in_seeds(self):
        seeds = build_data_gov_seeds_for_query(
            "PM-KISAN",
            verify_fn=lambda u: "evil.com" not in u and is_data_gov_url(u),
            limit=6,
        )
        urls = [s["url"] for s in seeds]
        self.assertFalse(any("evil.com" in u for u in urls))

    def test_redirect_verification_via_verify_source(self):
        from app.services.live_gov_retrieval_service import verify_source

        self.assertFalse(verify_source("https://evil.com/dataset"))

    def test_kannada_query_supported(self):
        p = DataGovProvider()
        ctx = ProviderContext(
            query="ಉದ್ಯೋಗಿನಿ ಯೋಜನೆ ಬಗ್ಗೆ ಮಾಹಿತಿ",
            search_query="ಉದ್ಯೋಗಿನಿ ಯೋಜನೆ udyogini scheme",
            live_request_id="kn",
            overall_deadline=time.time() + 60,
            per_source_timeout=25.0,
            extra={},
        )
        self.assertTrue(p.supports("ಉದ್ಯೋಗಿನಿ ಯೋಜನೆ", context=ctx))

    def test_hindi_query_supported(self):
        p = DataGovProvider()
        ctx = ProviderContext(
            query="उद्योगिनी योजना के बारे में जानकारी",
            search_query="उद्योगिनी yojana udyogini scheme",
            live_request_id="hi",
            overall_deadline=time.time() + 60,
            per_source_timeout=25.0,
            extra={},
        )
        self.assertTrue(p.supports("उद्योगिनी योजना", context=ctx))

    def test_english_query_supported(self):
        p = DataGovProvider()
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
