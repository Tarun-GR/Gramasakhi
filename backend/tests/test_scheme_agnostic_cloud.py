"""Scheme-agnostic cloud_indexless gate checks (catalog-driven queries)."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from app.core.config import settings
from app.database.session import SessionLocal, engine
from app.models import audit, citizen_account, conversation, rag, user  # noqa: F401
from app.services import rag as rag_service
from app.services.scheme_search_service import corpus_coverage_counts, load_scheme_catalog

# Generic eligibility/benefits templates — no hardcoded answers.
_QUERY_TEMPLATES = (
    "What is {name}? Explain eligibility and benefits.",
    "Who is eligible for {name}?",
)


@unittest.skipUnless(engine.dialect.name == "postgresql", "requires PostgreSQL KB")
class TestSchemeAgnosticCloud(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db = SessionLocal()
        try:
            cls._coverage = corpus_coverage_counts(db)
        finally:
            db.close()
        cls._cases: list[tuple[str, str]] = []
        for entry in load_scheme_catalog():
            eid = str(entry.get("id") or "")
            name = str(entry.get("name") or eid)
            if cls._coverage.get(eid, 0) >= 3:
                cls._cases.append((eid, _QUERY_TEMPLATES[0].format(name=name)))

    def test_catalog_has_eval_cases(self):
        self.assertGreaterEqual(len(self._cases), 3, "need at least 3 schemes with chunks in KB")

    def test_cloud_indexless_passes_for_catalog_schemes_with_coverage(self):
        failures: list[str] = []
        passed = 0
        with patch.object(settings, "RUNTIME_PROFILE", "cloud"):
            with patch(
                "app.services.index_builder.hybrid_disk_indexes_present",
                return_value=False,
            ):
                for eid, query in self._cases[:10]:
                    with patch.object(rag_service, "_pgvector_retrieve", return_value=[]):
                        db = SessionLocal()
                        try:
                            out = rag_service.answer_with_evidence_gate(
                                db,
                                query,
                                enable_live_fallback=False,
                                skip_llm=True,
                            )
                        finally:
                            db.close()
                        if out.get("validated"):
                            passed += 1
                        else:
                            failures.append(f"{eid}:{out.get('reason')}")
        # Corpus quality varies; require strong majority pass without pgvector.
        n_cases = min(10, len(self._cases))
        self.assertGreaterEqual(
            passed,
            max(5, int(n_cases * 0.6)),
            msg=f"cloud gate passed={passed}/{n_cases} failures={failures}",
        )


if __name__ == "__main__":
    unittest.main()
