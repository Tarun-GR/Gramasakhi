"""Scheme intent supplement must not return obvious portal navigation chunks."""

from __future__ import annotations

import unittest

from app.database.session import SessionLocal, engine
from app.models import audit, citizen_account, conversation, rag, user  # noqa: F401
from app.services.evidence_quality import navigation_heaviness
from app.services.rag import _scheme_intent_supplement

PMJAY_Q = (
    "What is Ayushman Bharat PM-JAY? Explain eligibility and benefits for citizens."
)


@unittest.skipUnless(engine.dialect.name == "postgresql", "requires PostgreSQL KB")
class TestSchemeIntentSupplement(unittest.TestCase):
    def test_pmjay_supplement_avoids_high_navigation_chunks(self):
        db = SessionLocal()
        try:
            rows = _scheme_intent_supplement(
                db,
                PMJAY_Q,
                scheme_id_hint="ab-pmjay",
                limit=6,
            )
        finally:
            db.close()
        for row in rows:
            nav = navigation_heaviness(str(row.get("content") or ""))
            self.assertLess(
                nav,
                0.42,
                msg=f"navigation-heavy supplement chunk nav={nav:.2f}",
            )


if __name__ == "__main__":
    unittest.main()
