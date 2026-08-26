"""H4 — Government retrieval & source reliability regression tests."""

from __future__ import annotations

import time
import unittest
from typing import Any
from unittest.mock import MagicMock, patch

from app.core.config import settings
from app.services.acquisition.browser_playwright import BrowserAcquisition
from app.services.acquisition.orchestrator import SourceAcquisitionOrchestrator
from app.services.myscheme_service import request_accepts_candidate
from app.services.providers import (
    ChainRunResult,
    GovernmentInformationProvider,
    ProviderContext,
    ProviderPhaseStatus,
    ProviderRegistry,
    ProviderRunResult,
)
from app.services.providers.data_gov_provider import discover_data_gov_candidates


class TestH4SchemeIdentityGate(unittest.TestCase):
    def test_search_url_rejected_for_named_scheme_query(self):
        search = {
            "url": "https://www.myscheme.gov.in/search?q=udyogini",
            "content": "PM-KISAN search results and unrelated listings.",
            "kind": "search",
        }
        self.assertFalse(request_accepts_candidate("Udyogini eligibility", search))

    def test_non_scheme_url_requires_content_identity_match(self):
        india_gov = {
            "url": "https://www.india.gov.in/spotlight/pm-kisan",
            "scheme_name": "PM-KISAN",
            "content": "PM-KISAN provides income support to eligible farmer families.",
            "kind": "html",
        }
        self.assertTrue(request_accepts_candidate("PM-KISAN benefits", india_gov))
        wrong = {
            **india_gov,
            "scheme_name": "Udyogini",
            "content": "Udyogini supports women entrepreneurs in Karnataka.",
        }
        self.assertFalse(request_accepts_candidate("PM-KISAN benefits", wrong))


class TestH4DataGovSourceContent(unittest.TestCase):
    def test_dataset_link_does_not_inherit_search_shell_content(self):
        search_html = (
            b"<html><body><h1>data.gov.in search</h1>"
            b'<a href="https://data.gov.in/catalog/dataset/pm-kisan-eligibility">'
            b"PM-KISAN Eligibility</a></body></html>"
        )
        raw = [
            {
                "url": "https://data.gov.in/catalog/datasets?q=pm-kisan",
                "content": search_html,
                "kind": "html",
            }
        ]
        svc = MagicMock()
        svc.discover_candidate_pages.return_value = raw
        ranked = discover_data_gov_candidates(
            svc,
            "PM-KISAN eligibility",
            seeds=[{"url": "https://data.gov.in/catalog/datasets?q=pm-kisan"}],
            overall_deadline=time.time() + 60,
            live_request_id="h4-test",
            verify_fn=lambda u: True,
        )
        dataset_pages = [c for c in ranked if c.get("kind") == "dataset_page"]
        self.assertTrue(dataset_pages)
        for row in dataset_pages:
            self.assertNotIn("content", row)
            self.assertIn("data.gov.in/catalog/dataset", row.get("url") or "")


class _FixedProvider(GovernmentInformationProvider):
    def __init__(
        self,
        name: str,
        *,
        priority: int,
        status: ProviderPhaseStatus,
        evidence_ready: bool,
        accepted_url: str | None,
    ):
        self.name = name
        self.priority = priority
        self._status = status
        self._evidence_ready = evidence_ready
        self._accepted_url = accepted_url

    def supports(self, query: str, *, context: ProviderContext) -> bool:
        return True

    def run(self, context: ProviderContext, *, service: Any = None) -> ProviderRunResult:
        return ProviderRunResult(
            provider=self.name,
            status=self._status,
            accepted_url=self._accepted_url,
            evidence_ready=self._evidence_ready,
        )


class TestH4ProviderRegistryAcceptedUrl(unittest.TestCase):
    def test_accepted_url_only_when_evidence_ready(self):
        registry = ProviderRegistry(
            [
                _FixedProvider(
                    "partial",
                    priority=1,
                    status=ProviderPhaseStatus.INSUFFICIENT,
                    evidence_ready=False,
                    accepted_url="https://gov.in/partial.html",
                ),
                _FixedProvider(
                    "sufficient",
                    priority=2,
                    status=ProviderPhaseStatus.SUFFICIENT,
                    evidence_ready=True,
                    accepted_url="https://gov.in/good.html",
                ),
            ]
        )
        ctx = ProviderContext(
            query="PM-KISAN eligibility",
            search_query="PM-KISAN eligibility",
            live_request_id="h4-test",
            overall_deadline=time.time() + 60,
            per_source_timeout=25.0,
        )
        result: ChainRunResult = registry.run_chain(ctx)
        self.assertEqual(result.accepted_url, "https://gov.in/good.html")
        self.assertTrue(result.evidence_ready)


class TestH4BrowserDeadlineBudget(unittest.TestCase):
    def test_browser_timeout_respects_remaining_deadline(self):
        browser = BrowserAcquisition(timeout_seconds=45.0)
        near_deadline = time.time() + 2.0
        timeout_ms = int(max(5.0, browser.timeout_seconds) * 1000)
        remaining_ms = int(max(1000, (near_deadline - time.time()) * 1000))
        capped = min(timeout_ms, remaining_ms)
        self.assertLessEqual(capped, 2000)

    def test_orchestrator_skips_browser_when_deadline_elapsed(self):
        orch = SourceAcquisitionOrchestrator(MagicMock())
        result = orch.acquire(
            "https://www.myscheme.gov.in/schemes/pm-kisan",
            verify_fn=lambda u: True,
            deadline_ts=time.time() - 1.0,
        )
        self.assertEqual(result.error, "source_timeout")


class TestH4LiveSecondPassAssistanceContext(unittest.TestCase):
    def setUp(self):
        self._orig = {
            "LIVE_GOV_FALLBACK_ENABLED": settings.LIVE_GOV_FALLBACK_ENABLED,
            "EVIDENCE_GATE_ENABLED": settings.EVIDENCE_GATE_ENABLED,
        }
        settings.LIVE_GOV_FALLBACK_ENABLED = True
        settings.EVIDENCE_GATE_ENABLED = True

    def tearDown(self):
        for k, v in self._orig.items():
            setattr(settings, k, v)

    def test_second_pass_receives_assistance_context(self):
        from app.services import rag as rag_service
        from app.services.evidence_validator import EvidenceValidator, ValidationResult

        assistance = MagicMock()
        assistance.detected_scheme = "PM-KISAN"
        good_doc = {
            "content": (
                "PM-KISAN provides income support of Rs 6000 per year to eligible "
                "landholding farmer families across India."
            ),
            "scheme_name": "PM-KISAN",
            "similarity_score": 0.9,
        }
        validate_calls = {"n": 0}
        original_gate = rag_service.answer_with_evidence_gate

        def fake_validate(self, query, docs):
            validate_calls["n"] += 1
            if validate_calls["n"] < 3:
                return ValidationResult(
                    ok=False,
                    confidence="low",
                    reason="insufficient_coverage",
                    signals={},
                )
            return ValidationResult(
                ok=True,
                confidence="high",
                reason="ok",
                evidence=list(docs),
                signals={},
            )

        live_result = {
            "ingested": [{"url": "https://gov.in/pm-kisan.pdf"}],
            "evidence_ready": True,
            "live_request_id": "rid-h4",
            "latency_ms": 10,
        }

        with patch.object(EvidenceValidator, "validate", fake_validate):
            with patch.object(rag_service, "hybrid_retrieve", return_value=[good_doc]):
                with patch.object(rag_service, "get_query_embedding", return_value=[0.1]):
                    with patch(
                        "app.services.multilingual_retrieval_service.build_retrieval_plan"
                    ) as plan_mock:
                        plan_mock.return_value = MagicMock(
                            validation_query="PM-KISAN eligibility",
                            retrieval_query="PM-KISAN eligibility",
                        )
                        with patch(
                            "app.services.live_gov_retrieval_service.try_live_gov_fallback",
                            return_value=live_result,
                        ):
                            with patch.object(
                                rag_service,
                                "answer_with_evidence_gate",
                                wraps=original_gate,
                            ) as gate_mock:
                                rag_service.answer_with_evidence_gate(
                                    MagicMock(),
                                    "PM-KISAN eligibility",
                                    assistance_context=assistance,
                                    enable_live_fallback=True,
                                    skip_llm=True,
                                )
        inner = [
            c
            for c in gate_mock.call_args_list
            if c.kwargs.get("enable_live_fallback") is False
        ]
        self.assertEqual(len(inner), 1)
        self.assertIs(inner[0].kwargs.get("assistance_context"), assistance)


if __name__ == "__main__":
    unittest.main()
