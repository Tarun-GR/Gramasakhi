"""PM-KISAN cloud retrieval path — evidence gate must not weaken for admin-only chunks."""

from __future__ import annotations

import unittest

from app.services.evidence_validator import EvidenceValidator

QUERY = "What is PM-KISAN? Explain eligibility and benefits."

ADMIN_ONLY = [
    {
        "chunk_id": "a1",
        "content": "PM-Kisan Samman Nidhi reimbursement process and operational guidelines portal.",
        "similarity_score": 0.78,
        "document_title": "PM-Kisan Samman Nidhi",
    }
]

WITH_ELIGIBILITY = ADMIN_ONLY + [
    {
        "chunk_id": "b2",
        "content": (
            "Eligible farmer families who cultivate land may receive benefit installments "
            "under PM-KISAN criteria and who can apply via the portal."
        ),
        "similarity_score": 0.82,
        "document_title": "PM-Kisan Samman Nidhi",
        "source": "https://www.myscheme.gov.in/schemes/pm-kisan",
    }
]


class TestPmKisanEvidence(unittest.TestCase):
    def test_admin_only_chunks_fail_coverage(self):
        v = EvidenceValidator()
        r = v.validate(QUERY, ADMIN_ONLY)
        self.assertFalse(r.ok)
        self.assertIn(r.reason, ("insufficient_coverage", "insufficient_relevance"))

    def test_eligibility_rich_chunks_pass_gate(self):
        v = EvidenceValidator()
        r = v.validate(QUERY, WITH_ELIGIBILITY)
        self.assertTrue(r.ok, msg=f"reason={r.reason} signals={r.signals}")

    def test_unrelated_scheme_still_fails(self):
        v = EvidenceValidator()
        other = [
            {
                "chunk_id": "x",
                "content": "Eligible members under PMSBY insurance scheme benefits and criteria.",
                "similarity_score": 0.9,
                "scheme_name": "PMSBY",
            }
        ]
        r = v.validate(QUERY, other)
        self.assertFalse(r.ok)


if __name__ == "__main__":
    unittest.main()
