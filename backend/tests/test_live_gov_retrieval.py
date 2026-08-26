"""Live government retrieval fallback — mocked HTTP, no live websites."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from app.config.gov_sources import is_allowed_url, source_category
from app.core.config import settings
from app.services import live_gov_retrieval_service as live
from app.services import rag as rag_service
from app.services.evidence_validator import SAFE_FALLBACK_ANSWER
from app.services.live_gov_retrieval_service import (
    LIVE_DOCUMENT_INGESTED,
    NO_TRUSTED_INFORMATION_FOUND,
    NO_VERIFIED_INFORMATION,
    LiveGovRetrievalService,
    score_candidate,
    select_best_candidates,
    try_live_gov_fallback,
    verify_source,
)
from app.services.web_ingestion_service import compute_hash


class TestTrustedSources(unittest.TestCase):
    def test_untrusted_rejected(self):
        self.assertFalse(verify_source("https://random-blog.com/document.pdf"))
        self.assertFalse(is_allowed_url("https://evil.example.com/x.pdf"))

    def test_ssrf_rejected(self):
        self.assertFalse(verify_source("http://localhost/secret"))
        self.assertFalse(verify_source("http://127.0.0.1/x"))
        self.assertFalse(verify_source("http://192.168.1.10/x"))
        self.assertFalse(verify_source("http://10.0.0.5/x"))
        self.assertFalse(verify_source("file:///etc/passwd"))

    def test_karnataka_and_central_allowed(self):
        self.assertTrue(verify_source("https://sevasindhu.karnataka.gov.in/"))
        self.assertTrue(verify_source("https://pmkisan.gov.in/guidelines.pdf"))
        self.assertEqual(
            source_category("https://sevasindhu.karnataka.gov.in/"), "karnataka"
        )
        self.assertEqual(source_category("https://pmkisan.gov.in/"), "central")


class TestCandidateScoring(unittest.TestCase):
    def test_relevant_pdf_preferred_over_logo(self):
        query = "What are PMAY-G eligibility requirements?"
        cands = [
            {
                "url": "https://www.myscheme.gov.in/docs/pmay-logo-guidelines.pdf",
                "link_text": "Logo Usage Guidelines",
            },
            {
                "url": "https://www.myscheme.gov.in/docs/pmay-g-guidelines.pdf",
                "link_text": "PMAY-G Guidelines",
            },
            {"url": "https://evil.com/pmay.pdf", "link_text": "fake"},
        ]
        best = select_best_candidates(cands, query, limit=3)
        self.assertTrue(best)
        self.assertIn("guidelines.pdf", best[0]["url"])
        self.assertNotIn("evil.com", best[0]["url"])
        # Logo should score below guidelines
        logo_score = score_candidate(cands[0]["url"], query, link_text=cands[0]["link_text"])
        guide_score = score_candidate(cands[1]["url"], query, link_text=cands[1]["link_text"])
        self.assertGreater(guide_score, logo_score)


class TestLiveFallbackGate(unittest.TestCase):
    def setUp(self):
        settings.LIVE_GOV_FALLBACK_ENABLED = True
        settings.EVIDENCE_GATE_ENABLED = True

    def _vr(self, ok, reason="ok", evidence=None, signals=None):
        from app.services.evidence_validator import ValidationResult

        return ValidationResult(
            ok=ok,
            confidence="high" if ok else "low",
            reason=reason,
            signals=signals or {},
            evidence=evidence or [],
        )

    def test_existing_evidence_does_not_call_live(self):
        docs = [
            {
                "content": "PMAY-G provides housing assistance benefits to rural households.",
                "scheme_name": "PMAY-G",
                "similarity_score": 0.95,
            }
        ]
        db = MagicMock()
        with patch.object(rag_service, "hybrid_retrieve", return_value=docs):
            with patch(
                "app.services.evidence_validator.EvidenceValidator.validate",
                side_effect=[
                    self._vr(False, "no_evidence"),  # pre-check with []
                    self._vr(True, "ok", evidence=docs),  # indexed PASS
                ],
            ):
                with patch.object(
                    rag_service,
                    "_call_llm_after_validation",
                    return_value="Benefits answer",
                ):
                    with patch(
                        "app.services.live_gov_retrieval_service.try_live_gov_fallback"
                    ) as live_mock:
                        out = rag_service.answer_with_evidence_gate(
                            db,
                            "What are PMAY-G benefits?",
                            top_k=3,
                            enable_live_fallback=True,
                        )
                        live_mock.assert_not_called()
                        self.assertTrue(out["validated"])
                        self.assertEqual(out.get("knowledge_source"), "indexed")

    def test_insufficient_evidence_triggers_live(self):
        docs = [{"content": "noise", "scheme_name": "X", "similarity_score": 0.1}]
        db = MagicMock()
        with patch.object(rag_service, "hybrid_retrieve", return_value=docs):
            with patch(
                "app.services.evidence_validator.EvidenceValidator.validate",
                side_effect=[
                    self._vr(False, "no_evidence"),
                    self._vr(False, "low_relevance"),
                ],
            ):
                with patch(
                    "app.services.live_gov_retrieval_service.try_live_gov_fallback",
                    return_value={
                        "status": NO_TRUSTED_INFORMATION_FOUND,
                        "ingested": [],
                        "latency_ms": 12,
                    },
                ) as live_mock:
                    out = rag_service.answer_with_evidence_gate(
                        db,
                        "How do I cook rice?",
                        top_k=3,
                        enable_live_fallback=True,
                    )
                    live_mock.assert_called_once()
                    self.assertFalse(out["llm_invoked"])
                    # Citizen UX: specific failure explanation (not a hallucinated answer)
                    self.assertFalse(out["validated"])
                    self.assertIn("live_status", out)
                    self.assertTrue(out.get("answer"))
                    self.assertNotIn("does not exist", (out.get("answer") or "").lower())
                    self.assertEqual(out.get("knowledge_source"), "none")

    def test_live_disabled_keeps_legacy_fallback(self):
        docs = [{"content": "noise", "scheme_name": "X", "similarity_score": 0.1}]
        db = MagicMock()
        with patch.object(rag_service, "hybrid_retrieve", return_value=docs):
            with patch(
                "app.services.evidence_validator.EvidenceValidator.validate",
                side_effect=[
                    self._vr(False, "no_evidence"),
                    self._vr(False, "low_relevance"),
                ],
            ):
                with patch(
                    "app.services.live_gov_retrieval_service.try_live_gov_fallback"
                ) as live_mock:
                    out = rag_service.answer_with_evidence_gate(
                        db,
                        "How do I cook rice?",
                        top_k=3,
                        enable_live_fallback=False,
                    )
                    live_mock.assert_not_called()
                    self.assertEqual(out["answer"], SAFE_FALLBACK_ANSWER)

    def test_live_ingest_then_second_retrieval_pass(self):
        """After live ingest, second gate PASS invokes LLM; knowledge_source=live."""
        strong = [
            {
                "content": (
                    "PMAY-G eligibility: rural households without pucca house "
                    "are eligible for housing assistance under the scheme."
                ),
                "scheme_name": "PMAY-G",
                "source": "https://www.myscheme.gov.in/docs/pmay.pdf",
                "page": 3,
                "similarity_score": 0.93,
            }
        ]
        db = MagicMock()
        with patch.object(rag_service, "hybrid_retrieve", return_value=strong):
            with patch(
                "app.services.evidence_validator.EvidenceValidator.validate",
                side_effect=[
                    self._vr(False, "no_evidence"),  # first pre
                    self._vr(False, "low_coverage"),  # first indexed FAIL → live
                    self._vr(False, "no_evidence"),  # second pre
                    self._vr(True, "ok", evidence=strong),  # second PASS
                ],
            ):
                with patch(
                    "app.services.live_gov_retrieval_service.try_live_gov_fallback",
                    return_value={
                        "status": LIVE_DOCUMENT_INGESTED,
                        "ingested": [
                            {
                                "status": "ok",
                                "document_id": "d1",
                                "source_url": "https://www.myscheme.gov.in/docs/pmay.pdf",
                                "document_hash": "abc",
                            }
                        ],
                        "latency_ms": 40,
                    },
                ):
                    with patch.object(
                        rag_service,
                        "_call_llm_after_validation",
                        return_value="Eligible rural households without pucca house.",
                    ) as llm:
                        out = rag_service.answer_with_evidence_gate(
                            db,
                            "Who is eligible for PMAY-G?",
                            top_k=3,
                            enable_live_fallback=True,
                        )
                        llm.assert_called_once()
                        self.assertTrue(out["validated"])
                        self.assertTrue(out["llm_invoked"])
                        self.assertEqual(out["knowledge_source"], "live_government")
                        self.assertEqual(out["sources"][0].get("scheme_name"), "PMAY-G")


class TestLiveServiceIngest(unittest.TestCase):
    def test_pdf_ingestion_uses_existing_pipeline(self):
        db = MagicMock()
        svc = LiveGovRetrievalService(db)
        pdf_bytes = b"%PDF-1.4 fake content for hash"
        with patch.object(svc, "_find_by_hash", return_value=None):
            with patch.object(
                svc.web,
                "_push_to_pipeline",
                return_value={
                    "status": "ok",
                    "document_id": "doc-1",
                    "source_url": "https://pmkisan.gov.in/a.pdf",
                    "document_hash": compute_hash(pdf_bytes),
                },
            ) as push:
                out = svc.ingest_verified_document(
                    url="https://pmkisan.gov.in/a.pdf",
                    content=pdf_bytes,
                    content_type="application/pdf",
                    scheme_name="PM-KISAN",
                    ministry="Agriculture",
                    state="India",
                    kind="pdf",
                )
                push.assert_called_once()
                self.assertEqual(out["status"], "ok")
                self.assertEqual(push.call_args.kwargs.get("ingestion_type"), "live_web")

    def test_myscheme_pdf_url_not_rewritten_to_scheme_page(self):
        db = MagicMock()
        svc = LiveGovRetrievalService(db)
        pdf_bytes = b"%PDF-1.4 udyogini guidelines"
        pdf_url = "https://www.myscheme.gov.in/sites/default/files/udyogini.pdf"
        with patch.object(svc, "_find_by_hash", return_value=None):
            with patch.object(
                svc.web,
                "_push_to_pipeline",
                return_value={"status": "ok", "document_id": "doc-pdf", "source_url": pdf_url},
            ) as push:
                out = svc.ingest_verified_document(
                    url=pdf_url,
                    content=pdf_bytes,
                    content_type="application/pdf",
                    scheme_name="Udyogini Scheme",
                    ministry=None,
                    state="Karnataka",
                    kind="pdf",
                    scheme_id="us",
                )
                push.assert_called_once()
                self.assertEqual(out["status"], "ok")
                self.assertEqual(push.call_args.kwargs.get("url"), pdf_url)
                meta = push.call_args.kwargs.get("extra_metadata") or {}
                self.assertEqual(meta.get("scheme_id"), "us")
                self.assertEqual(meta.get("document_url"), pdf_url)

    def test_deduplication_skips_second_ingest(self):
        db = MagicMock()
        svc = LiveGovRetrievalService(db)
        pdf_bytes = b"%PDF-1.4 same bytes"
        existing = MagicMock()
        existing.id = "existing-id"
        existing.scheme_name = "PM-KISAN"
        with patch.object(svc, "_find_by_hash", return_value=existing):
            with patch.object(svc.web, "_push_to_pipeline") as push:
                out = svc.ingest_verified_document(
                    url="https://pmkisan.gov.in/a.pdf",
                    content=pdf_bytes,
                    content_type="application/pdf",
                    scheme_name="PM-KISAN",
                    ministry=None,
                    state="India",
                    kind="pdf",
                )
                push.assert_not_called()
                self.assertEqual(out["status"], "skipped")
                self.assertEqual(out["reason"], "duplicate")

    def test_untrusted_never_ingested(self):
        db = MagicMock()
        svc = LiveGovRetrievalService(db)
        with patch.object(svc.web, "_push_to_pipeline") as push:
            out = svc.ingest_verified_document(
                url="https://random-blog.com/document.pdf",
                content=b"%PDF",
                content_type="application/pdf",
                scheme_name="X",
                ministry=None,
                state=None,
                kind="pdf",
            )
            push.assert_not_called()
            self.assertEqual(out["status"], "rejected")

    def test_website_failure_does_not_crash(self):
        db = MagicMock()
        svc = LiveGovRetrievalService(db)
        with patch.object(
            svc,
            "discover_candidate_pages",
            side_effect=TimeoutError("slow gov site"),
        ):
            out = svc.search_government_sources("What are PM-KISAN benefits?")
        self.assertEqual(out["status"], NO_TRUSTED_INFORMATION_FOUND)
        self.assertEqual(out.get("detail"), live.LIVE_UNAVAILABLE)

    def test_index_refresh_called_after_ingest(self):
        db = MagicMock()
        svc = LiveGovRetrievalService(db)
        with patch.object(
            svc,
            "discover_candidate_pages",
            return_value=[
                {
                    "url": "https://pmkisan.gov.in/benefits.pdf",
                    "kind": "pdf",
                    "content": b"%PDF-1.4 benefits",
                    "content_type": "application/pdf",
                    "scheme_name": "PM-KISAN",
                    "link_text": "Benefits PDF",
                }
            ],
        ):
            with patch.object(
                svc,
                "ingest_verified_document",
                return_value={
                    "status": "ok",
                    "document_id": "d1",
                    "source_url": "https://pmkisan.gov.in/benefits.pdf",
                },
            ):
                with patch.object(
                    svc, "refresh_indexes", return_value={"chunk_count": 3}
                ) as rebuild:
                    with patch.object(
                        svc, "_probe_evidence_ready", return_value=True
                    ):
                        out = svc.search_government_sources(
                            "What are PM-KISAN benefits?"
                        )
                        rebuild.assert_called_once()
                        self.assertEqual(out["status"], LIVE_DOCUMENT_INGESTED)
                        self.assertTrue(out.get("evidence_ready"))
                        self.assertTrue(out.get("live_request_id"))

    def test_karnataka_priority_in_seeds(self):
        seeds = live.discover_seed_urls("Karnataka housing scheme eligibility")
        # Prefer karnataka portal when query mentions Karnataka
        if seeds:
            # At least one seed should be karnataka-scoped when available
            cats = [source_category(s["url"]) for s in seeds]
            self.assertTrue(any(c == "karnataka" for c in cats) or any(
                (s.get("scope") or "").lower() == "karnataka" for s in seeds
            ))

    def test_central_sources_in_seeds_for_pm_kisan(self):
        seeds = live.discover_seed_urls("What are PM-KISAN eligibility criteria?")
        self.assertTrue(seeds)
        joined = " ".join(s["url"] for s in seeds)
        self.assertTrue(
            "pmkisan.gov.in" in joined or "myscheme.gov.in" in joined,
            joined,
        )

    def test_rewritten_query_used_for_live_search(self):
        """Conversation rewrite must drive live search (not the short follow-up alone)."""
        db = MagicMock()
        with patch.object(
            LiveGovRetrievalService,
            "search_government_sources",
            return_value={"status": NO_TRUSTED_INFORMATION_FOUND, "ingested": []},
        ) as search:
            try_live_gov_fallback(
                db,
                "Who is eligible for PMAY-G?",
                conversation_context=None,
            )
            search.assert_called_once()
            self.assertEqual(search.call_args.args[0], "Who is eligible for PMAY-G?")


if __name__ == "__main__":
    unittest.main()
