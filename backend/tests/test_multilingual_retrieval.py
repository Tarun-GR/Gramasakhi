"""Multilingual retrieval bridge + semantic equivalence metrics."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from app.services.evidence_validator import EvidenceValidator
from app.services.multilingual_retrieval_service import (
    build_retrieval_plan,
    multi_query_hybrid_retrieve,
    normalize_transcript,
)
from app.services.query_rewriter import rewrite_query
from tests.fixtures.multilingual_retrieval_corpus import CORPUS, relevant_doc_for


class TestTranscriptNormalize(unittest.TestCase):
    def test_preserves_kannada_and_numbers(self):
        raw = "  PM-KISAN  \u0caf\u0ccb\u0c9c\u0ca8\u0cc6  6000  "
        orig, norm = normalize_transcript(raw)
        self.assertEqual(orig, raw)
        self.assertIn("PM-KISAN", norm)
        self.assertIn("6000", norm)
        self.assertIn("\u0caf\u0ccb\u0c9c\u0ca8\u0cc6", norm)


class TestRetrievalPlan(unittest.TestCase):
    def test_kannada_expands_to_english_retrieval(self):
        q = "PM-KISAN \u0caf\u0ccb\u0c9c\u0ca8\u0cc6\u0c97\u0cc6 \u0caf\u0cbe\u0cb0\u0cc1 \u0c85\u0cb0\u0ccd\u0cb9\u0cb0\u0cc1?"
        plan = build_retrieval_plan(q, language="KN")
        self.assertTrue(plan.multilingual_expansion_used)
        self.assertEqual(plan.original_query, q.strip())
        sem = plan.semantic_retrieval_query.lower()
        self.assertIn("pm-kisan", sem)
        self.assertIn("eligib", sem)
        self.assertIn("PM-KISAN", plan.entities)

    def test_hindi_expands(self):
        q = "PM-KISAN \u092f\u094b\u091c\u0928\u093e \u0915\u0940 \u092a\u093e\u0924\u094d\u0930\u0924\u093e?"
        plan = build_retrieval_plan(q, language="HI")
        self.assertTrue(plan.multilingual_expansion_used)
        self.assertIn("eligib", plan.semantic_retrieval_query.lower())

    def test_english_no_unnecessary_expansion(self):
        q = "Who is eligible for PM-KISAN?"
        plan = build_retrieval_plan(q, language="EN")
        self.assertFalse(plan.multilingual_expansion_used)
        self.assertEqual(plan.semantic_retrieval_query, plan.normalized_query)

    def test_does_not_mutate_citizen_query(self):
        q = "PM-KISAN \u0c85\u0cb0\u0ccd\u0cb9\u0ca4\u0cc6?"
        plan = build_retrieval_plan(q, language="KN")
        self.assertEqual(plan.original_query, q)


class TestFollowupRewrite(unittest.TestCase):
    def test_kannada_followup_resolves_scheme(self):
        hist = [{"role": "user", "content": "PM-KISAN \u0caf\u0ccb\u0c9c\u0ca8\u0cc6 \u0c8f\u0ca8\u0cc1?"}]
        out = rewrite_query("\u0c85\u0ca6\u0c95\u0ccd\u0c95\u0cc6 \u0caf\u0cbe\u0cb0\u0cc1 \u0c85\u0cb0\u0ccd\u0cb9\u0cb0\u0cc1?", hist)
        self.assertTrue(out["was_rewritten"])
        self.assertIn("PM-KISAN", out["rewritten_query"])
        self.assertIn("eligible", out["rewritten_query"].lower())

    def test_hindi_followup_resolves_scheme(self):
        hist = [{"role": "user", "content": "PM-KISAN \u0915\u094d\u092f\u093e \u0939\u0948?"}]
        out = rewrite_query("\u0909\u0938\u0915\u0947 \u0932\u093f\u090f \u0915\u094c\u0928 \u092a\u093e\u0924\u094d\u0930 \u0939\u0948?", hist)
        self.assertIn("PM-KISAN", out["rewritten_query"])


class TestEvidenceAcceptsEnglishForKannadaIntent(unittest.TestCase):
    def test_validator_passes_english_pdf_for_kn_semantic_query(self):
        plan = build_retrieval_plan(
            "PM-KISAN \u0caf\u0ccb\u0c9c\u0ca8\u0cc6\u0c97\u0cc6 \u0caf\u0cbe\u0cb0\u0cc1 \u0c85\u0cb0\u0ccd\u0cb9\u0cb0\u0cc1?",
            language="KN",
        )
        docs = [
            {
                "chunk_id": "1",
                "content": (
                    "PM-KISAN eligibility: small and marginal farmer families "
                    "with landholding are eligible. Benefits Rs 6000 per year."
                ),
                "scheme_name": "PM-KISAN",
                "document_title": "PM-KISAN guidelines",
                "similarity_score": 0.92,
                "ce_score": 3.0,
            }
        ]
        v = EvidenceValidator(
            relevance_threshold=0.2,
            coverage_threshold=0.2,
            agreement_threshold=0.0,
            min_query_terms=1,
        )
        # Semantic/English validation query must pass for English PDF evidence
        sem = v.validate(plan.validation_query, docs)
        self.assertTrue(sem.ok, sem.reason)
        self.assertIn("eligib", plan.validation_query.lower())


class TestSemanticEquivalenceMetrics(unittest.TestCase):
    """Proxy recall: bridge semantic terms must hit the synthetic EN doc bag."""

    def _hit(self, query: str, doc: dict, k: int = 5) -> bool:
        plan = build_retrieval_plan(query)
        toks = [w for w in plan.semantic_retrieval_query.lower().split() if len(w) > 2]
        entities = [e.lower() for e in plan.entities]
        scored = []
        for t in CORPUS:
            d = relevant_doc_for(t)
            text = (d["content"] + " " + d["scheme_name"]).lower()
            score = sum(1 for w in toks if w in text)
            for e in entities:
                token = e.split()[0]
                if token in text or e in text:
                    score += 10
            if plan.intent and plan.intent in text:
                score += 8
            # Unique primary topic phrase from synthetic docs
            if plan.intent and f"primary topic {plan.intent}" in text:
                score += 20
            scored.append((score, d["chunk_id"]))
        scored.sort(reverse=True)
        if not scored:
            return False
        # Include ties at rank k
        kth = scored[min(k, len(scored)) - 1][0]
        top = {cid for sc, cid in scored if sc >= kth}
        # Cap extreme ties to top-k by original order
        if len(top) > k * 3:
            top = {cid for _, cid in scored[:k]}
        return doc["chunk_id"] in top

    def test_corpus_size(self):
        self.assertGreaterEqual(len(CORPUS), 50)

    def test_kannada_recall_at_5(self):
        hits = 0
        for t in CORPUS:
            doc = relevant_doc_for(t)
            if self._hit(t["kn"], doc, k=5):
                hits += 1
        recall = hits / len(CORPUS)
        self.assertGreaterEqual(recall, 0.65, f"Kannada Recall@5={recall:.2f}")

    def test_hindi_recall_at_5(self):
        hits = 0
        for t in CORPUS:
            doc = relevant_doc_for(t)
            if self._hit(t["hi"], doc, k=5):
                hits += 1
        recall = hits / len(CORPUS)
        self.assertGreaterEqual(recall, 0.65, f"Hindi Recall@5={recall:.2f}")

    def test_english_recall_at_5(self):
        hits = 0
        for t in CORPUS:
            doc = relevant_doc_for(t)
            if self._hit(t["en"], doc, k=5):
                hits += 1
        recall = hits / len(CORPUS)
        self.assertGreaterEqual(recall, 0.65, f"English Recall@5={recall:.2f}")

    def test_kannada_hindi_share_semantic_overlap(self):
        overlap = 0
        for t in CORPUS:
            kn = set(build_retrieval_plan(t["kn"]).semantic_retrieval_query.lower().split())
            hi = set(build_retrieval_plan(t["hi"]).semantic_retrieval_query.lower().split())
            en = set(build_retrieval_plan(t["en"]).semantic_retrieval_query.lower().split())
            if kn & en and hi & en:
                overlap += 1
        rate = overlap / len(CORPUS)
        self.assertGreaterEqual(rate, 0.8, f"semantic overlap rate={rate:.2f}")


class TestMultiQueryWiring(unittest.TestCase):
    def test_english_calls_hybrid_once(self):
        from app.services import rag as rag_service

        db = MagicMock()
        plan = build_retrieval_plan("Who is eligible for PM-KISAN?", language="EN")
        with patch.object(rag_service, "hybrid_retrieve", return_value=[{"chunk_id": "a"}]) as hr:
            docs = multi_query_hybrid_retrieve(db, plan, top_k=3, use_rerank=False)
        self.assertEqual(hr.call_count, 1)
        self.assertEqual(docs[0]["chunk_id"], "a")

    def test_kannada_fans_out_queries(self):
        from app.services import rag as rag_service

        db = MagicMock()
        plan = build_retrieval_plan(
            "PM-KISAN \u0caf\u0ccb\u0c9c\u0ca8\u0cc6\u0c97\u0cc6 \u0caf\u0cbe\u0cb0\u0cc1 \u0c85\u0cb0\u0ccd\u0cb9\u0cb0\u0cc1?",
            language="KN",
        )
        self.assertTrue(plan.multilingual_expansion_used)

        def fake(db, q, **kwargs):
            return [
                {
                    "chunk_id": "c1",
                    "content": "PM-KISAN eligibility",
                    "similarity_score": 0.8,
                    "hybrid_score": 0.8,
                }
            ]

        with patch.object(rag_service, "hybrid_retrieve", side_effect=fake) as hr:
            docs = multi_query_hybrid_retrieve(db, plan, top_k=3, use_rerank=False)
        self.assertGreaterEqual(hr.call_count, 2)
        self.assertEqual(docs[0]["chunk_id"], "c1")


class TestGateUsesValidationQuery(unittest.TestCase):
    def test_kannada_query_validates_via_bridge(self):
        from app.services import rag as rag_service
        from app.services.evidence_validator import ValidationResult

        db = MagicMock()
        docs = [
            {
                "chunk_id": "1",
                "content": (
                    "PM-KISAN eligibility criteria for farmer families. "
                    "Benefit amount Rs 6000 per year in three installments."
                ),
                "scheme_name": "PM-KISAN",
                "document_title": "PM-KISAN",
                "similarity_score": 0.95,
                "ce_score": 4.0,
                "_embedding": [0.1] * 8,
            }
        ]

        class V:
            def validate(self, query, docs_in):
                # Fail if asked to validate raw Kannada-only coverage
                if any(ord(c) > 127 for c in query) and "eligib" not in query.lower():
                    return ValidationResult(ok=False, confidence="low", reason="low_coverage", signals={})
                if docs_in:
                    return ValidationResult(
                        ok=True,
                        confidence="high",
                        reason="ok",
                        signals={"coverage": 0.9},
                        evidence=docs_in,
                    )
                return ValidationResult(ok=False, confidence="low", reason="no_evidence", signals={})

        with patch(
            "app.services.multilingual_retrieval_service.multi_query_hybrid_retrieve",
            return_value=docs,
        ):
            with patch.object(
                rag_service,
                "_call_llm_after_validation",
                return_value={
                    "success": True,
                    "answer": "KN ans 6000",
                    "response_language": "KN",
                    "model": "m",
                    "latency_ms": 1,
                },
            ):
                out = rag_service.answer_with_evidence_gate(
                    db,
                    "PM-KISAN \u0caf\u0ccb\u0c9c\u0ca8\u0cc6\u0c97\u0cc6 \u0caf\u0cbe\u0cb0\u0cc1 \u0c85\u0cb0\u0ccd\u0cb9\u0cb0\u0cc1?",
                    validator=V(),
                    response_language="KN",
                    enable_live_fallback=False,
                )
        self.assertTrue(out.get("validated"))
        self.assertEqual(out.get("response_language"), "KN")


if __name__ == "__main__":
    unittest.main()
