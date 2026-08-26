"""Stage 1 — government provider base + registry tests."""

from __future__ import annotations

import time
import unittest
from typing import Any, List

from app.services.providers import (
    ChainRunResult,
    ExtractedEvidence,
    GovernmentInformationProvider,
    ProviderContext,
    ProviderPhaseStatus,
    ProviderRegistry,
    ProviderRunResult,
    SchemeCandidate,
    extracted_evidence_is_usable,
    merge_provider_ingested,
)


class _StubProvider(GovernmentInformationProvider):
    def __init__(
        self,
        name: str,
        *,
        priority: int = 100,
        supports: bool = True,
        status: ProviderPhaseStatus = ProviderPhaseStatus.INSUFFICIENT,
        evidence_ready: bool = False,
        ingested: int = 0,
    ):
        self.name = name
        self.priority = priority
        self._supports = supports
        self._status = status
        self._evidence_ready = evidence_ready
        self._ingested = ingested
        self.calls = 0

    def supports(self, query: str, *, context: ProviderContext) -> bool:
        return self._supports

    def run(self, context: ProviderContext, *, service: Any = None) -> ProviderRunResult:
        self.calls += 1
        if self._ingested:
            merge_provider_ingested(
                context,
                [{"source_url": f"https://example.gov.in/{self.name}.html", "status": "ok"}],
            )
        return ProviderRunResult(
            provider=self.name,
            status=self._status,
            evidence_ready=self._evidence_ready,
            ingested_count=self._ingested,
            accepted_url=f"https://example.gov.in/{self.name}.html" if self._evidence_ready else None,
        )


class TestExtractedEvidenceUsable(unittest.TestCase):
    def test_rejects_url_only(self):
        ev = ExtractedEvidence(
            ok=True,
            content="https://www.example.gov.in/schemes/foo",
            source_url="https://www.example.gov.in/schemes/foo",
        )
        self.assertFalse(extracted_evidence_is_usable(ev))

    def test_accepts_section_text(self):
        ev = ExtractedEvidence(
            ok=True,
            sections={"eligibility": "Women entrepreneurs with family income below 1.5 lakh may apply."},
            source_url="https://www.example.gov.in/schemes/foo",
            text_chars=70,
        )
        self.assertTrue(extracted_evidence_is_usable(ev))

    def test_rejects_empty_ok_flag(self):
        ev = ExtractedEvidence(ok=False, content="Some text that is long enough to pass length checks.")
        self.assertFalse(extracted_evidence_is_usable(ev))


class TestProviderRegistry(unittest.TestCase):
    def _ctx(self) -> ProviderContext:
        return ProviderContext(
            query="Who is eligible for a government scheme?",
            search_query="government scheme eligibility",
            live_request_id="test-rid",
            overall_deadline=time.time() + 60,
            per_source_timeout=25.0,
        )

    def test_runs_in_priority_order(self):
        p_low = _StubProvider("registry", priority=300)
        p_mid = _StubProvider("indiagov", priority=200)
        p_high = _StubProvider("myscheme", priority=100)
        reg = ProviderRegistry([p_mid, p_high, p_low])
        self.assertEqual(reg.provider_names, ["myscheme", "indiagov", "registry"])
        reg.run_chain(self._ctx())
        self.assertEqual(p_high.calls, 1)
        self.assertEqual(p_mid.calls, 1)
        self.assertEqual(p_low.calls, 1)

    def test_short_circuits_on_sufficient_provider(self):
        p1 = _StubProvider("myscheme", priority=100, status=ProviderPhaseStatus.SUFFICIENT, evidence_ready=True)
        p2 = _StubProvider("indiagov", priority=200)
        out = ProviderRegistry([p1, p2]).run_chain(self._ctx())
        self.assertIsInstance(out, ChainRunResult)
        self.assertTrue(out.evidence_ready)
        self.assertEqual(out.final_provider, "myscheme")
        self.assertEqual(p1.calls, 1)
        self.assertEqual(p2.calls, 0)

    def test_skips_unsupported_provider(self):
        p_skip = _StubProvider("datagov", priority=150, supports=False)
        p_run = _StubProvider("registry", priority=300)
        out = ProviderRegistry([p_skip, p_run]).run_chain(self._ctx())
        self.assertFalse(out.evidence_ready)
        self.assertEqual(p_skip.calls, 0)
        self.assertEqual(p_run.calls, 1)
        self.assertEqual(out.provider_results[0].status, ProviderPhaseStatus.SKIPPED)

    def test_merges_ingested_without_duplicates(self):
        ctx = self._ctx()
        ctx.ingested = [{"source_url": "https://example.gov.in/existing.html", "status": "ok"}]
        p = _StubProvider("myscheme", priority=100, ingested=1)
        # Stub always adds same URL pattern — second merge via duplicate provider call
        merge_provider_ingested(
            ctx,
            [{"source_url": "https://example.gov.in/existing.html", "status": "ok"}],
        )
        ProviderRegistry([p]).run_chain(ctx)
        urls = [i.get("source_url") for i in ctx.ingested]
        self.assertEqual(urls.count("https://example.gov.in/existing.html"), 1)
        self.assertEqual(len(ctx.ingested), 2)

    def test_provider_error_does_not_crash_chain(self):
        class _BoomProvider(GovernmentInformationProvider):
            name = "boom"
            priority = 100

            def run(self, context: ProviderContext, *, service: Any = None) -> ProviderRunResult:
                raise TimeoutError("simulated")

        p2 = _StubProvider("registry", priority=200)
        out = ProviderRegistry([_BoomProvider(), p2]).run_chain(self._ctx())
        self.assertFalse(out.evidence_ready)
        self.assertEqual(out.provider_results[0].status, ProviderPhaseStatus.ERROR)
        self.assertEqual(p2.calls, 1)


class TestGovernmentInformationProviderDefaults(unittest.TestCase):
    def test_default_granular_methods_are_safe(self):
        class _Minimal(GovernmentInformationProvider):
            name = "minimal"
            priority = 1

            def run(self, context: ProviderContext, *, service: Any = None) -> ProviderRunResult:
                cand = SchemeCandidate(url="https://example.gov.in/x")
                self.discover("q", context=context)
                self.resolve_identity(cand, "q", context=context)
                self.acquire(cand, context=context)
                self.extract(cand, query="q", context=context)
                self.discover_documents(cand, context=context)
                return ProviderRunResult(provider=self.name, status=ProviderPhaseStatus.INSUFFICIENT)

        out = ProviderRegistry([_Minimal()]).run_chain(
            ProviderContext(
                query="q",
                search_query="q",
                live_request_id="rid",
                overall_deadline=time.time() + 10,
                per_source_timeout=5,
            )
        )
        self.assertFalse(out.evidence_ready)


if __name__ == "__main__":
    unittest.main()
