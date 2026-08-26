"""H3 — RAG + evidence reliability regression tests."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from app.core.config import settings
from app.services.evidence_validator import EvidenceValidator, has_substantive_content
from app.services import rag as rag_service
from app.services.query_rewriter import rewrite_query


class TestH3SubstantiveEvidence(unittest.TestCase):
    def setUp(self):
        settings.EVIDENCE_GATE_ENABLED = True
        self.validator = EvidenceValidator()

    def test_url_only_chunk_fails_validation(self):
        doc = {
            "content": "",
            "source": "https://gov.in/PM-Kisan-Refund-Mechanism.pdf",
            "scheme_name": "PM-KISAN",
            "similarity_score": 0.92,
        }
        self.assertFalse(has_substantive_content(doc))
        result = self.validator.validate("PM Kisan refund mechanism", [doc])
        self.assertFalse(result.ok)
        self.assertIn(
            result.reason,
            ("no_substantive_evidence", "no_relevant_evidence"),
        )

    def test_substantive_chunk_passes_prune(self):
        doc = {
            "content": (
                "PM Kisan Samman Nidhi provides income support benefits of "
                "Rs 6000 per year to eligible landholding farmer families."
            ),
            "scheme_name": "PM-KISAN",
            "similarity_score": 0.9,
        }
        self.assertTrue(has_substantive_content(doc))
        kept = self.validator.prune_weak([doc])
        self.assertEqual(len(kept), 1)

    def test_scheme_filter_error_fails_closed(self):
        doc = {
            "content": "PM Kisan provides income support to eligible farmer families annually.",
            "scheme_name": "PM-KISAN",
            "similarity_score": 0.9,
        }
        with patch(
            "app.services.myscheme_service.filter_evidence_by_scheme",
            side_effect=RuntimeError("filter boom"),
        ):
            result = self.validator.validate("PM Kisan benefits", [doc])
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "scheme_filter_error")


class TestH3SchemeContextRewrite(unittest.TestCase):
    def setUp(self):
        settings.QUERY_REWRITE_USE_OLLAMA = False

    def test_followup_after_non_scheme_topic_does_not_inherit_pm_kisan(self):
        history = [
            {"role": "user", "content": "Tell me about PM-KISAN."},
            {"role": "user", "content": "Tell me about farming subsidies in Karnataka."},
        ]
        out = rewrite_query("Who is eligible?", history)
        self.assertNotIn("PM-KISAN", out["rewritten_query"])
        self.assertIsNone(out.get("active_scheme"))

    def test_udyogini_switch_then_followup(self):
        history = [
            {"role": "user", "content": "What is PM-KISAN?"},
            {"role": "user", "content": "Tell me about Udyogini."},
        ]
        out = rewrite_query("Who is eligible?", history)
        self.assertIn("Udyogini", out["rewritten_query"])
        self.assertNotIn("PM-KISAN", out["rewritten_query"])


class TestH3RagSourceHygiene(unittest.TestCase):
    def test_strip_private_fields_removes_internal_scores(self):
        docs = [
            {
                "content": "Benefit details for farmers.",
                "source": "https://gov.in/doc.pdf",
                "ce_score": 9.2,
                "source_aligned": True,
                "hybrid_score": 0.8,
                "_embedding": [1.0, 2.0],
            }
        ]
        out = rag_service.strip_private_fields(docs)
        self.assertEqual(len(out), 1)
        self.assertNotIn("ce_score", out[0])
        self.assertNotIn("source_aligned", out[0])
        self.assertNotIn("_embedding", out[0])
        self.assertEqual(out[0]["document_url"], "https://gov.in/doc.pdf")

    def test_strip_private_fields_dedupes_urls(self):
        docs = [
            {
                "content": "Chunk one about PM Kisan benefits for farmers.",
                "source": "https://gov.in/same.pdf",
            },
            {
                "content": "Chunk two about PM Kisan eligibility criteria details.",
                "source": "https://gov.in/same.pdf",
            },
        ]
        out = rag_service.strip_private_fields(docs)
        self.assertEqual(len(out), 1)

    def test_prefer_source_aligned_skips_empty_content(self):
        url = "https://gov.in/PM-Kisan-Refund-Mechanism.pdf"
        pool = [
            {
                "content": "",
                "source": url,
                "similarity_score": 0.1,
                "bm25_score": 0.9,
            },
            {
                "content": "PM Kisan provides direct income support to eligible farmers.",
                "source": "https://gov.in/other.pdf",
                "similarity_score": 0.7,
            },
        ]
        ranked = rag_service._prefer_source_aligned(
            "PM Kisan refund mechanism",
            pool,
            pool,
            top_k=2,
        )
        empty_rows = [r for r in ranked if r.get("source") == url]
        for row in empty_rows:
            self.assertFalse(row.get("source_aligned"))
            self.assertLess(float(row.get("similarity_score") or 0.0), 0.85)


if __name__ == "__main__":
    unittest.main()
