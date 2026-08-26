"""Phase 6 — query rewriter unit tests (no live Ollama)."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from app.core.config import settings
from app.services import query_rewriter as qr


class TestQueryRewriter(unittest.TestCase):
    def setUp(self):
        settings.QUERY_REWRITE_USE_OLLAMA = False

    def test_pmay_g_followup_eligibility(self):
        history = [
            {"role": "user", "content": "Tell me about PMAY-G."},
            {"role": "assistant", "content": "PMAY-G is a rural housing scheme."},
        ]
        out = qr.rewrite_query("Who is eligible?", history)
        self.assertEqual(out["original_query"], "Who is eligible?")
        self.assertEqual(out["rewritten_query"], "Who is eligible for PMAY-G?")
        self.assertTrue(out["was_rewritten"])

    def test_pm_kisan_followup_benefits(self):
        history = [
            {"role": "user", "content": "Tell me about PM-KISAN."},
            {"role": "assistant", "content": "PM-KISAN provides income support."},
        ]
        out = qr.rewrite_query("What are the benefits?", history)
        self.assertEqual(out["rewritten_query"], "What are the benefits of PM-KISAN?")

    def test_documents_followup(self):
        history = [{"role": "user", "content": "Tell me about PMAY-G."}]
        out = qr.rewrite_query("What documents are required?", history)
        self.assertIn("PMAY-G", out["rewritten_query"])
        self.assertIn("document", out["rewritten_query"].lower())

    def test_third_turn_still_uses_scheme(self):
        history = [
            {"role": "user", "content": "Tell me about PMAY-G."},
            {"role": "assistant", "content": "PMAY-G provides housing support."},
            {"role": "user", "content": "Who is eligible?"},
            {"role": "assistant", "content": "Eligible rural households..."},
        ]
        out = qr.rewrite_query("What documents are needed?", history)
        self.assertEqual(out["rewritten_query"], "What documents are needed for PMAY-G?")

    def test_standalone_query_preserved(self):
        history = [{"role": "user", "content": "Tell me about PMAY-G."}]
        out = qr.rewrite_query("What is PM-KISAN?", history)
        self.assertEqual(out["rewritten_query"], "What is PM-KISAN?")
        self.assertFalse(out["was_rewritten"])
        # Must NOT become PMAY-G
        self.assertNotIn("PMAY-G", out["rewritten_query"])

    def test_independent_conversations_no_cross_contamination(self):
        hist_a = [{"role": "user", "content": "Tell me about PMAY-G."}]
        hist_b = [{"role": "user", "content": "Tell me about PM-KISAN."}]
        a = qr.rewrite_query("Who is eligible?", hist_a)
        b = qr.rewrite_query("Who is eligible?", hist_b)
        self.assertEqual(a["rewritten_query"], "Who is eligible for PMAY-G?")
        self.assertEqual(b["rewritten_query"], "Who is eligible for PM-KISAN?")

    def test_rewriter_failure_falls_back_to_original(self):
        history = [{"role": "user", "content": "Tell me about PMAY-G."}]
        with patch.object(qr, "_heuristic_rewrite", side_effect=RuntimeError("boom")):
            with patch.object(qr, "_ollama_rewrite", return_value=None):
                out = qr.rewrite_query("Who is eligible?", history)
        self.assertEqual(out["rewritten_query"], "Who is eligible?")
        self.assertEqual(out["method"], "fallback")
        self.assertFalse(out["was_rewritten"])

    def test_original_query_unchanged_in_result(self):
        history = [{"role": "user", "content": "Tell me about PM-KISAN."}]
        original = "Who is eligible?"
        out = qr.rewrite_query(original, history)
        self.assertEqual(out["original_query"], original)

    def test_stt_guruha_jyoti_not_forced_onto_pm_kisan(self):
        """Whisper often emits 'Guruha Jyoti Mahiti'; must not append prior PM-KISAN."""
        history = [{"role": "user", "content": "Tell me about PM-KISAN."}]
        out = qr.rewrite_query("Guruha Jyoti Mahiti", history)
        self.assertNotIn("PM-KISAN", out["rewritten_query"])
        self.assertEqual(out["active_scheme"], "Gruha Jyoti")
        self.assertFalse(out["was_rewritten"])


if __name__ == "__main__":
    unittest.main()
