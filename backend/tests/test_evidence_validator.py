"""
Evidence sufficiency validator tests — hard gate before LLM.
"""

from __future__ import annotations

import unittest
from typing import Dict, List
from unittest.mock import MagicMock, patch

import numpy as np

from app.core.config import settings
from app.services.evidence_validator import (
    SAFE_FALLBACK_ANSWER,
    EvidenceValidator,
    extract_keywords,
)
from app.services import rag as rag_service


def _emb(seed: str, dim: int = 16) -> List[float]:
    rng = np.random.default_rng(abs(hash(seed)) % (2**32))
    v = rng.normal(size=dim).astype(np.float32)
    v = v / (np.linalg.norm(v) + 1e-12)
    return v.tolist()


class TestEvidenceValidator(unittest.TestCase):
    def setUp(self):
        self._orig = {
            "EVIDENCE_RELEVANCE_THRESHOLD": settings.EVIDENCE_RELEVANCE_THRESHOLD,
            "EVIDENCE_COVERAGE_THRESHOLD": settings.EVIDENCE_COVERAGE_THRESHOLD,
            "EVIDENCE_AGREEMENT_THRESHOLD": settings.EVIDENCE_AGREEMENT_THRESHOLD,
            "EVIDENCE_AGREEMENT_VARIANCE_MAX": settings.EVIDENCE_AGREEMENT_VARIANCE_MAX,
            "EVIDENCE_MIN_QUERY_TERMS": settings.EVIDENCE_MIN_QUERY_TERMS,
            "EVIDENCE_GATE_ENABLED": settings.EVIDENCE_GATE_ENABLED,
        }
        settings.EVIDENCE_RELEVANCE_THRESHOLD = 0.65
        settings.EVIDENCE_COVERAGE_THRESHOLD = 0.6
        settings.EVIDENCE_AGREEMENT_THRESHOLD = 0.7
        settings.EVIDENCE_AGREEMENT_VARIANCE_MAX = 0.08
        settings.EVIDENCE_MIN_QUERY_TERMS = 2
        settings.EVIDENCE_GATE_ENABLED = True

        # Agreement: same scheme texts → similar embeddings; conflict → orthogonal
        def embed_fn(text: str):
            t = text.lower()
            if "penalty" in t or "fine" in t or "cook" in t or "rice" in t:
                return _emb("conflict-or-noise:" + t[:40])
            if "pm kisan" in t or "benefit" in t or "eligibility" in t or "farmer" in t:
                # Shared cluster for agreeing PM-Kisan docs
                base = np.array(_emb("pm-kisan-cluster"), dtype=np.float32)
                noise = np.array(_emb(t[:60]), dtype=np.float32) * 0.05
                v = base + noise
                v = v / (np.linalg.norm(v) + 1e-12)
                return v.tolist()
            return _emb(t[:80])

        self.validator = EvidenceValidator(embed_fn=embed_fn)

    def tearDown(self):
        for k, v in self._orig.items():
            setattr(settings, k, v)

    def test_valid_query_benefits_pass(self):
        docs = [
            {
                "content": (
                    "PM Kisan Samman Nidhi provides income support benefits of "
                    "Rs 6000 per year to eligible landholding farmer families."
                ),
                "scheme_name": "PM-KISAN",
                "similarity_score": 0.88,
                "hybrid_score": 0.9,
            },
            {
                "content": (
                    "Under PM Kisan, benefit installments are transferred directly "
                    "to the farmer bank account in three equal payments."
                ),
                "scheme_name": "PM-KISAN",
                "similarity_score": 0.82,
                "hybrid_score": 0.85,
            },
        ]
        result = self.validator.validate("What are benefits of PM Kisan?", docs)
        self.assertTrue(result.ok, msg=result.to_dict())
        self.assertIn(result.confidence, ("medium", "high"))
        self.assertEqual(result.reason, "evidence_sufficient")

    def test_partial_data_penalties_fail(self):
        docs = [
            {
                "content": (
                    "PM Kisan Samman Nidhi provides income support benefits of "
                    "Rs 6000 per year to landholding farmers."
                ),
                "scheme_name": "PM-KISAN",
                "similarity_score": 0.8,
                "hybrid_score": 0.8,
            },
            {
                "content": (
                    "PM Kisan benefits are credited in installments to Aadhaar "
                    "linked bank accounts of farmers."
                ),
                "scheme_name": "PM-KISAN",
                "similarity_score": 0.75,
                "hybrid_score": 0.78,
            },
        ]
        result = self.validator.validate("What are penalties in PM Kisan?", docs)
        self.assertFalse(result.ok)
        self.assertEqual(result.confidence, "low")
        self.assertIn(result.reason, ("insufficient_coverage", "insufficient_relevance"))

    def test_irrelevant_query_fail(self):
        docs = [
            {
                "content": "PM Kisan income support for farmers and eligibility criteria.",
                "scheme_name": "PM-KISAN",
                "similarity_score": 0.2,
                "hybrid_score": 0.2,
            }
        ]
        result = self.validator.validate("How to cook rice?", docs)
        self.assertFalse(result.ok)
        self.assertEqual(result.confidence, "low")

    def test_conflicting_documents_fail(self):
        docs = [
            {
                "content": "PM Kisan benefits provide Rs 6000 yearly income support to farmers.",
                "scheme_name": "PM-KISAN",
                "similarity_score": 0.9,
                "hybrid_score": 0.9,
            },
            {
                "content": (
                    "Severe penalties and fines apply for cooking rice incorrectly "
                    "under kitchen regulations."
                ),
                "scheme_name": "Kitchen Rules",
                "similarity_score": 0.88,
                "hybrid_score": 0.88,
            },
        ]
        # Coverage may also fail; force agreement path with matching keywords present
        result = self.validator.validate(
            "PM Kisan benefits and penalties overview", docs
        )
        self.assertFalse(result.ok)
        # Either coverage gap or conflict — both fail closed
        self.assertIn(
            result.reason,
            (
                "conflicting_evidence",
                "insufficient_agreement",
                "insufficient_coverage",
            ),
        )

    def test_short_query_edge_case(self):
        result = self.validator.validate("hi", [])
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "query_too_short")

    def test_empty_docs_fail(self):
        result = self.validator.validate("What are benefits of PM Kisan?", [])
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "no_evidence")

    def test_weak_tail_chunks_do_not_block_strong_evidence(self):
        """One strongly relevant chunk is sufficient; weak tail hits are pruned."""
        docs = [
            {
                "content": (
                    "Financial help for farmers includes short term crop loans and "
                    "interest subvention under the Kisan Credit Card scheme."
                ),
                "scheme_name": "Kisan Credit Card",
                "ce_score": 8.63,
            },
            {
                "content": "Card validity is five years subject to annual review.",
                "scheme_name": "Kisan Credit Card",
                "ce_score": -0.13,
            },
            {
                "content": "Rural housing construction stages and installments.",
                "scheme_name": "PMAY-G",
                "ce_score": -2.18,
            },
        ]
        result = self.validator.validate("financial help for farmers", docs)
        self.assertTrue(result.ok, msg=result.to_dict())
        self.assertEqual(len(result.evidence), 1)
        self.assertEqual(result.signals["pruning"]["kept"], 1)
        self.assertEqual(result.signals["pruning"]["retrieved"], 3)

    def test_all_weak_chunks_fail(self):
        docs = [
            {"content": "Rural housing scheme details.", "ce_score": -6.0},
            {"content": "Crop loan interest rates.", "ce_score": -8.5},
        ]
        result = self.validator.validate("how to cook rice", docs)
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "no_relevant_evidence")
        self.assertEqual(result.evidence, [])

    def test_extract_keywords_filters_stopwords(self):
        terms = extract_keywords("What are the benefits of PM Kisan?")
        self.assertIn("benefits", terms)
        self.assertIn("pm", terms)
        self.assertIn("kisan", terms)
        self.assertNotIn("what", terms)
        self.assertNotIn("the", terms)


class TestEvidenceGateIntegration(unittest.TestCase):
    def setUp(self):
        settings.EVIDENCE_GATE_ENABLED = True

    def test_fail_never_invokes_llm(self):
        docs = [
            {
                "content": "PM Kisan benefits for farmers.",
                "scheme_name": "PM-KISAN",
                "similarity_score": 0.2,
                "hybrid_score": 0.2,
            }
        ]
        db = MagicMock()
        with patch.object(rag_service, "hybrid_retrieve", return_value=docs):
            with patch.object(
                rag_service, "_call_llm_after_validation", return_value="SHOULD_NOT_RUN"
            ) as llm:
                out = rag_service.answer_with_evidence_gate(
                    db, "How to cook rice?", top_k=3
                )
                llm.assert_not_called()
                self.assertFalse(out["validated"])
                self.assertFalse(out["llm_invoked"])
                self.assertEqual(out["answer"], SAFE_FALLBACK_ANSWER)
                self.assertEqual(out["sources"], [])

    def test_pass_invokes_llm(self):
        docs = [
            {
                "content": (
                    "PM Kisan Samman Nidhi provides income support benefits of "
                    "Rs 6000 per year to eligible landholding farmer families."
                ),
                "scheme_name": "PM-KISAN",
                "similarity_score": 0.9,
                "hybrid_score": 0.9,
            },
            {
                "content": (
                    "PM Kisan benefit installments are paid to farmers in three "
                    "equal transfers each year."
                ),
                "scheme_name": "PM-KISAN",
                "similarity_score": 0.85,
                "hybrid_score": 0.86,
            },
        ]

        def embed_fn(text: str):
            base = np.array(_emb("pm-kisan-cluster"), dtype=np.float32)
            noise = np.array(_emb(text[:50]), dtype=np.float32) * 0.05
            v = base + noise
            v = v / (np.linalg.norm(v) + 1e-12)
            return v.tolist()

        validator = EvidenceValidator(embed_fn=embed_fn)
        db = MagicMock()
        with patch.object(rag_service, "hybrid_retrieve", return_value=docs):
            with patch.object(
                rag_service,
                "_call_llm_after_validation",
                return_value="Grounded LLM answer about PM Kisan benefits.",
            ) as llm:
                out = rag_service.answer_with_evidence_gate(
                    db,
                    "What are benefits of PM Kisan?",
                    top_k=3,
                    validator=validator,
                )
                llm.assert_called_once()
                self.assertTrue(out["validated"])
                self.assertTrue(out["llm_invoked"])
                self.assertIn("PM Kisan", out["answer"])
                self.assertTrue(out["sources"])

    def test_sources_never_expose_raw_embeddings(self):
        docs = [
            {
                "content": (
                    "PM Kisan provides income support benefits of Rs 6000 per year "
                    "to eligible landholding farmer families."
                ),
                "scheme_name": "PM-KISAN",
                "ce_score": 8.0,
                "_embedding": [0.1] * 8,
            }
        ]
        db = MagicMock()
        with patch.object(rag_service, "hybrid_retrieve", return_value=docs):
            out = rag_service.answer_with_evidence_gate(
                db, "What are benefits of PM Kisan?", top_k=3, skip_llm=True
            )
        self.assertTrue(out["validated"])
        self.assertFalse(out["llm_invoked"])
        for src in out["sources"]:
            self.assertNotIn("_embedding", src)


class TestQueryEmbeddingCache(unittest.TestCase):
    def setUp(self):
        rag_service._QUERY_EMBED_CACHE.clear()

    def tearDown(self):
        rag_service._QUERY_EMBED_CACHE.clear()

    def test_repeat_query_hits_cache(self):
        calls = []

        def fake_embed(text):
            calls.append(text)
            return [0.5] * 8

        with patch.object(rag_service, "get_embeddings", side_effect=fake_embed):
            a = rag_service.get_query_embedding("PM Kisan eligibility")
            b = rag_service.get_query_embedding("pm kisan eligibility  ")
        self.assertEqual(a, b)
        self.assertEqual(len(calls), 1)

    def test_cache_is_bounded(self):
        with patch.object(settings, "QUERY_EMBED_CACHE_SIZE", 3):
            with patch.object(rag_service, "get_embeddings", return_value=[0.1] * 4):
                for i in range(10):
                    rag_service.get_query_embedding(f"query number {i}")
        self.assertLessEqual(len(rag_service._QUERY_EMBED_CACHE), 3)

    def test_cache_key_isolates_embedding_dimensions(self):
        """A dimension change must not serve a stale vector of the wrong size."""
        with patch.object(rag_service, "get_embeddings", return_value=[0.1] * 8):
            with patch.object(settings, "EMBEDDING_DIMENSIONS", 8):
                small = rag_service.get_query_embedding("PM Kisan eligibility")
        with patch.object(rag_service, "get_embeddings", return_value=[0.2] * 32):
            with patch.object(settings, "EMBEDDING_DIMENSIONS", 32):
                large = rag_service.get_query_embedding("PM Kisan eligibility")
        self.assertEqual(len(small), 8)
        self.assertEqual(len(large), 32)


if __name__ == "__main__":
    unittest.main()
