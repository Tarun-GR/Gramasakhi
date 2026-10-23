"""Scheme needle expansion for SQL retrieval parity."""

from __future__ import annotations

import unittest

from app.services.rag import _scheme_retrieval_needles


class TestSchemeRetrievalNeedles(unittest.TestCase):
    def test_pmjay_includes_human_aliases(self):
        needles = _scheme_retrieval_needles(
            "What is Ayushman Bharat PM-JAY?",
            scheme_id_hint="ab-pmjay",
        )
        blob = " ".join(needles).lower()
        self.assertIn("pmjay", blob.replace(" ", ""))
        self.assertTrue(any("ayushman" in n for n in needles))

    def test_pm_kisan_includes_samman(self):
        needles = _scheme_retrieval_needles(
            "What is PM-KISAN?",
            scheme_id_hint="pm-kisan",
        )
        blob = " ".join(needles).lower()
        self.assertTrue("samman" in blob or "pmkisan" in blob.replace(" ", ""))


if __name__ == "__main__":
    unittest.main()
