"""PM-JAY must pass evidence gate on cloud_indexless (parity with local hybrid)."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from app.core.config import settings
from app.database.session import SessionLocal, engine
from app.models import audit, citizen_account, conversation, rag, user  # noqa: F401
from app.services import rag as rag_service

PMJAY_QUERY = (
    "What is Ayushman Bharat PM-JAY? Explain eligibility and benefits for citizens."
)


@unittest.skipUnless(engine.dialect.name == "postgresql", "requires PostgreSQL KB")
class TestPmjayCloudEvidence(unittest.TestCase):
    def test_cloud_indexless_pmjay_passes_gate(self):
        with patch.object(settings, "RUNTIME_PROFILE", "cloud"):
            with patch(
                "app.services.index_builder.hybrid_disk_indexes_present",
                return_value=False,
            ):
                with patch.object(rag_service, "_pgvector_retrieve", return_value=[]):
                    db = SessionLocal()
                    try:
                        out = rag_service.answer_with_evidence_gate(
                            db,
                            PMJAY_QUERY,
                            enable_live_fallback=False,
                            skip_llm=True,
                        )
                    finally:
                        db.close()

        self.assertTrue(
            out.get("validated"),
            msg=f"reason={out.get('reason')} signals={out.get('signals')}",
        )
        self.assertNotEqual(out.get("reason"), "insufficient_coverage")


if __name__ == "__main__":
    unittest.main()
