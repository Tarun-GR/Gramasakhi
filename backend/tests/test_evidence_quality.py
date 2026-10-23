"""Evidence quality ranking — navigation vs policy substance."""

from __future__ import annotations

import unittest

from app.services.evidence_quality import (
    evidence_quality_score,
    navigation_heaviness,
    policy_substance,
    rerank_docs_by_evidence_quality,
)

PORTAL_SNIPPET = (
    "Create Ayushman Card Create ABHA Number Our YouTube Channel @AyushmanNHA "
    "Am I Eligible ? PMJAY for 70+ Find Hospitals ABHA Number How to Use Ayushman App"
)

POLICY_SNIPPET = (
    "SECTION:\nEligibility\n\nCONTENT:\n"
    "Rural families listed in SECC database are eligible for health coverage up to Rs. 5 lakh "
    "per family per year for secondary and tertiary care hospitalization."
)


class TestEvidenceQuality(unittest.TestCase):
    def test_navigation_heavier_on_portal_menu(self):
        self.assertGreater(navigation_heaviness(PORTAL_SNIPPET), navigation_heaviness(POLICY_SNIPPET))

    def test_policy_substance_higher_on_eligibility_section(self):
        self.assertGreater(policy_substance(POLICY_SNIPPET), policy_substance(PORTAL_SNIPPET))

    def test_rerank_prefers_policy_chunk(self):
        portal = {"content": PORTAL_SNIPPET, "similarity_score": 0.95}
        policy = {"content": POLICY_SNIPPET, "similarity_score": 0.55}
        ranked = rerank_docs_by_evidence_quality("PM-JAY eligibility", [portal, policy])
        self.assertEqual(ranked[0]["content"], POLICY_SNIPPET)

    def test_pdf_source_gets_modest_boost(self):
        base = {"content": POLICY_SNIPPET, "source": "https://x.gov.in/a.pdf"}
        html = {"content": POLICY_SNIPPET, "source": "https://x.gov.in/page"}
        self.assertGreater(evidence_quality_score(base), evidence_quality_score(html))


if __name__ == "__main__":
    unittest.main()
