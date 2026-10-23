"""Regression: Render cloud without disk indexes must merge scheme_text even when pgvector hits."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from app.core.config import settings
from app.services import rag as rag_service
from app.services.evidence_validator import EvidenceValidator

QUERY = "What is PM-KISAN? Explain eligibility and benefits."

WEAK_PGVECTOR = [
    {
        "chunk_id": "pg1",
        "content": "PM-Kisan Samman Nidhi reimbursement process and operational guidelines portal.",
        "similarity_score": 0.78,
        "document_title": "PM-Kisan Samman Nidhi",
    }
]

STRONG_SCHEME_TEXT = [
    {
        "chunk_id": "st1",
        "content": (
            "Eligible farmer families who cultivate land may receive benefit installments "
            "under PM-KISAN criteria and who can apply via the portal."
        ),
        "similarity_score": 0.82,
        "document_title": "PM-Kisan Samman Nidhi",
        "source": "https://www.myscheme.gov.in/schemes/pm-kisan",
    }
]


class TestCloudIndexlessRetrieval(unittest.TestCase):
    def test_weak_pgvector_alone_fails_evidence_gate(self):
        v = EvidenceValidator()
        r = v.validate(QUERY, WEAK_PGVECTOR)
        self.assertFalse(r.ok)
        self.assertEqual(r.reason, "insufficient_coverage")

    def test_cloud_indexless_merges_scheme_text_when_pgvector_weak(self):
        """Reproduces production: non-empty pgvector admin chunks skipped scheme_text before fix."""
        ml_plan = MagicMock()
        ml_plan.validation_query = QUERY
        ml_plan.live_search_query = QUERY

        hybrid_called = {"n": 0}

        def _hybrid(*_a, **_k):
            hybrid_called["n"] += 1
            return WEAK_PGVECTOR

        with patch.object(settings, "RUNTIME_PROFILE", "cloud"):
            with patch.object(settings, "EVIDENCE_GATE_ENABLED", True):
                with patch(
                    "app.services.index_builder.hybrid_disk_indexes_present",
                    return_value=False,
                ):
                    with patch(
                        "app.services.multilingual_retrieval_service.build_retrieval_plan",
                        return_value=ml_plan,
                    ):
                        with patch.object(
                            rag_service,
                            "_pgvector_retrieve",
                            return_value=list(WEAK_PGVECTOR),
                        ) as pg_mock:
                            with patch.object(
                                rag_service,
                                "_scheme_text_retrieve",
                                return_value=list(STRONG_SCHEME_TEXT),
                            ) as st_mock:
                                with patch.object(
                                    rag_service,
                                    "_scheme_intent_supplement",
                                    return_value=[],
                                ):
                                    with patch(
                                        "app.services.multilingual_retrieval_service.multi_query_hybrid_retrieve",
                                        side_effect=_hybrid,
                                    ):
                                        with patch(
                                            "app.services.myscheme_service.filter_evidence_by_scheme",
                                            side_effect=lambda _q, docs: docs,
                                        ):
                                            out = rag_service.answer_with_evidence_gate(
                                                MagicMock(),
                                                QUERY,
                                                enable_live_fallback=False,
                                                skip_llm=True,
                                            )

        pg_mock.assert_called_once()
        st_mock.assert_called_once()
        self.assertEqual(hybrid_called["n"], 0, "cloud_indexless must not call hybrid retrieval")
        self.assertTrue(out.get("validated"), msg=f"reason={out.get('reason')} signals={out.get('signals')}")
        self.assertNotEqual(out.get("reason"), "insufficient_coverage")


if __name__ == "__main__":
    unittest.main()
