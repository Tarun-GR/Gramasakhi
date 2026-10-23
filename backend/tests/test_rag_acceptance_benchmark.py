"""Smoke test for rag_acceptance_benchmark case definitions."""

from __future__ import annotations

import unittest

from app.services.myscheme_service import requested_scheme_identity


class TestRagAcceptanceBenchmarkCases(unittest.TestCase):
    def test_fictional_query_has_no_scheme_identity(self):
        self.assertIsNone(
            requested_scheme_identity(
                "What is the Mars farmer subsidy eligibility in Karnataka?"
            )
        )

    def test_pm_kisan_query_has_identity(self):
        ident = requested_scheme_identity(
            "What is PM-KISAN? Explain eligibility and benefits."
        )
        self.assertIsNotNone(ident)
        self.assertIn("kisan", (ident or {}).get("normalized_key", ""))


if __name__ == "__main__":
    unittest.main()
