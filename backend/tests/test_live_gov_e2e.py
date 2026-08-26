"""
End-to-end live-government path with a deterministic fixture (no live network).

Simulates: absent KB → live discover → download → ingest_raw_bytes → index
→ second retrieval → evidence validator PASS (and FAIL paths).
"""

from __future__ import annotations

import os
import shutil
import unittest
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch
from uuid import uuid4

import numpy as np
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.database.session import Base
from app.models import audit, conversation, citizen_account, rag, user  # noqa: F401
from app.models.rag import DocumentChunk, RagDocument
from app.services import rag as rag_service
from app.services.evidence_validator import EvidenceValidator
from app.services.index_builder import IndexBuilder, set_index_builder
from app.services.live_gov_retrieval_service import (
    LIVE_DOCUMENT_INGESTED,
    NO_TRUSTED_INFORMATION_FOUND,
    LiveGovRetrievalService,
    content_relevant_to_query,
    try_live_gov_fallback,
)
from app.services.web_ingestion_service import compute_hash


DIM = 32
FIXTURE_URL = (
    "https://pmkisan.gov.in/guidelines/pm-kisan-eligible-benefits-documents.txt"
)
FIXTURE_TEXT = (
    "Pradhan Mantri Kisan Samman Nidhi (PM-KISAN) operational guidelines. "
    "Eligibility: All landholding farmer families who own cultivable land "
    "are eligible for income support benefits under PM-KISAN. "
    "The scheme provides financial benefit of Rs 6000 per year "
    "in three equal installments. Application is through the PM-KISAN portal. "
    "Required documents include Aadhaar and land records."
)


def _fake_embedding(seed: str, dim: int = DIM) -> List[float]:
    """Bag-aware fake embed so query/chunk overlap yields high cosine similarity."""
    import re

    tokens = sorted(set(re.findall(r"[a-z0-9]{4,}", (seed or "").lower())))
    vec = np.zeros(dim, dtype=np.float32)
    if not tokens:
        vec[0] = 1.0
        return vec.tolist()
    for t in tokens:
        idx = abs(hash(t)) % dim
        vec[idx] += 1.0
    vec = vec / (np.linalg.norm(vec) + 1e-12)
    return vec.tolist()


class TestLiveGovE2E(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db_path = "test_live_gov_e2e.db"
        cls.index_dir = "test_live_gov_e2e_indexes"
        if os.path.exists(cls.db_path):
            os.remove(cls.db_path)
        if os.path.isdir(cls.index_dir):
            shutil.rmtree(cls.index_dir, ignore_errors=True)
        cls.engine = create_engine(f"sqlite:///{cls.db_path}")
        Base.metadata.create_all(bind=cls.engine)
        cls.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=cls.engine)
        cls._orig = {
            "EMBEDDING_DIMENSIONS": settings.EMBEDDING_DIMENSIONS,
            "HYBRID_INDEX_DIR": settings.HYBRID_INDEX_DIR,
            "HYBRID_RERANK_ENABLED": settings.HYBRID_RERANK_ENABLED,
            "HYBRID_TOP_K": settings.HYBRID_TOP_K,
            "HYBRID_CANDIDATE_K": settings.HYBRID_CANDIDATE_K,
            "LIVE_GOV_FALLBACK_ENABLED": settings.LIVE_GOV_FALLBACK_ENABLED,
            "EVIDENCE_GATE_ENABLED": settings.EVIDENCE_GATE_ENABLED,
            "LIVE_GOV_MAX_PDFS": settings.LIVE_GOV_MAX_PDFS,
            "LIVE_GOV_MAX_CANDIDATES": settings.LIVE_GOV_MAX_CANDIDATES,
        }
        settings.EMBEDDING_DIMENSIONS = DIM
        settings.HYBRID_INDEX_DIR = cls.index_dir
        settings.HYBRID_RERANK_ENABLED = False
        settings.HYBRID_TOP_K = 5
        settings.HYBRID_CANDIDATE_K = 10
        settings.LIVE_GOV_FALLBACK_ENABLED = True
        settings.EVIDENCE_GATE_ENABLED = True
        settings.LIVE_GOV_MAX_PDFS = 2
        settings.LIVE_GOV_MAX_CANDIDATES = 4

    @classmethod
    def tearDownClass(cls):
        for k, v in cls._orig.items():
            setattr(settings, k, v)
        set_index_builder(IndexBuilder())
        if os.path.exists(cls.db_path):
            try:
                os.remove(cls.db_path)
            except Exception:
                pass
        if os.path.isdir(cls.index_dir):
            shutil.rmtree(cls.index_dir, ignore_errors=True)

    def setUp(self):
        self.db = self.SessionLocal()
        for table in reversed(Base.metadata.sorted_tables):
            self.db.execute(table.delete())
        self.db.commit()
        set_index_builder(IndexBuilder())

    def tearDown(self):
        self.db.close()

    def _patch_embeddings(self):
        def _batch(texts):
            return [_fake_embedding(t[:80]) for t in texts]

        return patch.multiple(
            rag_service,
            get_embeddings=lambda text: _fake_embedding(text[:80]),
            get_embeddings_batch=_batch,
            get_query_embedding=lambda text: _fake_embedding(text[:80]),
        )

    def _patch_storage(self):
        return patch(
            "app.services.rag.upload_rag_document",
            side_effect=lambda path, *_a, **_k: f"local://{path}",
        )

    def _candidate(self, text: str = FIXTURE_TEXT, url: str = FIXTURE_URL) -> Dict[str, Any]:
        return {
            "url": url,
            "kind": "html",
            "content": text.encode("utf-8"),
            "content_type": "text/html",
            "scheme_name": "PM-KISAN",
            "ministry": "Agriculture",
            "state": "India",
            "link_text": "PM-KISAN eligibility guidelines",
        }

    def test_content_relevance_accepts_matching_fixture(self):
        q = "Who is eligible for PM-KISAN benefits?"
        self.assertTrue(content_relevant_to_query(FIXTURE_TEXT, q))
        self.assertFalse(
            content_relevant_to_query(
                "Public holiday list for Karnataka government offices 2024.",
                q,
            )
        )

    def test_absent_kb_live_ingest_index_second_retrieval(self):
        """Full handoff: discover → ingest_raw_bytes → index → validator PASS."""
        query = "Who is eligible for PM-KISAN benefits and what documents are required?"
        # Confirm KB empty
        self.assertEqual(self.db.query(RagDocument).count(), 0)

        with self._patch_embeddings(), self._patch_storage():
            with patch(
                "app.database.session.SessionLocal",
                return_value=self.db,
            ):
                svc = LiveGovRetrievalService(self.db)
                svc._owns_session = False  # tearDown closes self.db
                with patch.object(
                    svc,
                    "discover_candidate_pages",
                    return_value=[self._candidate()],
                ):
                    with patch.object(
                        svc.web,
                        "extract_text_from_html",
                        return_value=FIXTURE_TEXT,
                    ):
                        out = svc.search_government_sources(query)

                self.assertTrue(out.get("live_request_id"))
                self.assertTrue(out.get("ingested"))
                self.assertTrue(out.get("evidence_ready"), out)
                self.assertEqual(out.get("status"), LIVE_DOCUMENT_INGESTED)

                docs = self.db.query(RagDocument).all()
                self.assertEqual(len(docs), 1)
                self.assertEqual(docs[0].source, FIXTURE_URL)
                self.assertEqual(docs[0].document_type, "LIVE_HTML")
                chunks = (
                    self.db.query(DocumentChunk)
                    .filter(DocumentChunk.document_id == docs[0].id)
                    .all()
                )
                self.assertGreater(len(chunks), 0)
                self.assertTrue(all(c.embedding for c in chunks))
                meta0 = chunks[0].metadata_dict or {}
                self.assertEqual(meta0.get("ingestion_type"), "live_web")

                retrieved = rag_service.hybrid_retrieve(self.db, query, top_k=5)
                self.assertTrue(retrieved)
                self.assertEqual(retrieved[0].get("scheme_name"), "PM-KISAN")
                self.assertIn("eligible", (retrieved[0].get("content") or "").lower())

                validation = EvidenceValidator().validate(query, retrieved)
                self.assertTrue(validation.ok, validation.reason)

                # Duplicate SHA-256 reuse
                svc2 = LiveGovRetrievalService(self.db)
                svc2._owns_session = False
                with patch.object(
                    svc2,
                    "discover_candidate_pages",
                    return_value=[self._candidate()],
                ):
                    with patch.object(
                        svc2.web,
                        "extract_text_from_html",
                        return_value=FIXTURE_TEXT,
                    ):
                        out2 = svc2.search_government_sources(query)

                self.assertEqual(self.db.query(RagDocument).count(), 1)
                self.assertTrue(
                    any(
                        i.get("reason") == "duplicate"
                        for i in (out2.get("ingested") or [])
                    )
                    or out2.get("evidence_ready")
                )

    def test_gate_uses_live_then_marks_live_government(self):
        query = "What are PM-KISAN eligibility criteria and benefits?"
        strong = [
            {
                "content": FIXTURE_TEXT,
                "scheme_name": "PM-KISAN",
                "source": FIXTURE_URL,
                "similarity_score": 0.92,
                "document_id": str(uuid4()),
            }
        ]

        def _vr(ok, reason="ok", evidence=None):
            from app.services.evidence_validator import ValidationResult

            return ValidationResult(
                ok=ok,
                confidence="high" if ok else "low",
                reason=reason,
                signals={},
                evidence=evidence or [],
            )

        with patch.object(rag_service, "hybrid_retrieve", return_value=strong):
            with patch(
                "app.services.evidence_validator.EvidenceValidator.validate",
                side_effect=[
                    _vr(False, "no_evidence"),
                    _vr(False, "low_coverage"),
                    _vr(False, "no_evidence"),
                    _vr(True, "ok", evidence=strong),
                ],
            ):
                with patch(
                    "app.services.live_gov_retrieval_service.try_live_gov_fallback",
                    return_value={
                        "status": LIVE_DOCUMENT_INGESTED,
                        "ingested": [{"status": "ok", "document_id": "d1"}],
                        "latency_ms": 10,
                        "live_request_id": "rid-e2e",
                        "evidence_ready": True,
                    },
                ):
                    with patch.object(
                        rag_service,
                        "_call_llm_after_validation",
                        return_value="Landholding farmer families are eligible.",
                    ):
                        out = rag_service.answer_with_evidence_gate(
                            self.db,
                            query,
                            enable_live_fallback=True,
                        )
        self.assertEqual(out["knowledge_source"], "live_government")
        self.assertTrue(out["llm_invoked"])
        self.assertEqual(out.get("live_request_id"), "rid-e2e")

    def test_no_relevant_candidate_no_hallucination(self):
        query = "What are PM-KISAN eligibility benefits documents application?"
        with patch(
            "app.database.session.SessionLocal",
            return_value=self.db,
        ):
            svc = LiveGovRetrievalService(self.db)
            svc._owns_session = False
            with patch.object(svc, "discover_candidate_pages", return_value=[]):
                out = svc.search_government_sources(query)
        self.assertEqual(out["status"], NO_TRUSTED_INFORMATION_FOUND)
        self.assertFalse(out.get("ingested"))

    def test_ingest_failure_is_structured(self):
        query = "What are PM-KISAN eligibility benefits?"
        with patch(
            "app.database.session.SessionLocal",
            return_value=self.db,
        ):
            svc = LiveGovRetrievalService(self.db)
            svc._owns_session = False
            with patch.object(
                svc,
                "discover_candidate_pages",
                return_value=[self._candidate()],
            ):
                with patch.object(
                    svc.web,
                    "extract_text_from_html",
                    return_value=FIXTURE_TEXT,
                ):
                    with patch.object(
                        svc.web,
                        "_push_to_pipeline",
                        return_value={
                            "status": "error",
                            "detail": "Storage upload failed",
                            "source_url": FIXTURE_URL,
                        },
                    ):
                        out = svc.search_government_sources(query)
        self.assertFalse(out.get("ingested"))
        self.assertEqual(out["status"], NO_TRUSTED_INFORMATION_FOUND)

    def test_try_live_disabled_skips(self):
        settings.LIVE_GOV_FALLBACK_ENABLED = False
        try:
            out = try_live_gov_fallback(self.db, "PM-KISAN eligibility?")
            self.assertTrue(out.get("skipped"))
        finally:
            settings.LIVE_GOV_FALLBACK_ENABLED = True


if __name__ == "__main__":
    unittest.main()
