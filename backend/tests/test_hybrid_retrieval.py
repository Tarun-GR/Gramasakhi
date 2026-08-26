"""
Unit tests for hybrid retrieval (FAISS + BM25 + merge + CrossEncoder stub).
"""

from __future__ import annotations

import os
import time
import unittest
from typing import Any, Dict, List
from unittest.mock import patch
from uuid import uuid4

import numpy as np
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.database.session import Base
from app.models import audit, conversation, citizen_account, rag, user  # noqa: F401
from app.models.rag import DocumentChunk, RagDocument
from app.services import rag as rag_service
from app.services.bm25_index import BM25Index
from app.services.faiss_index import FaissIndex
from app.services.index_builder import IndexBuilder, set_index_builder


DIM = 32


def _fake_embedding(seed: str, dim: int = DIM) -> List[float]:
    rng = np.random.default_rng(abs(hash(seed)) % (2**32))
    vec = rng.normal(size=dim).astype(np.float32)
    vec = vec / (np.linalg.norm(vec) + 1e-12)
    return vec.tolist()


class TestHybridRetrieval(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db_path = "test_hybrid_retrieval.db"
        cls.index_dir = "test_hybrid_indexes"
        cls.engine = create_engine(f"sqlite:///{cls.db_path}")
        Base.metadata.create_all(bind=cls.engine)
        cls.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=cls.engine)
        cls._orig = {
            "EMBEDDING_DIMENSIONS": settings.EMBEDDING_DIMENSIONS,
            "HYBRID_INDEX_DIR": settings.HYBRID_INDEX_DIR,
            "HYBRID_RERANK_ENABLED": settings.HYBRID_RERANK_ENABLED,
            "HYBRID_TOP_K": settings.HYBRID_TOP_K,
            "HYBRID_CANDIDATE_K": settings.HYBRID_CANDIDATE_K,
        }
        settings.EMBEDDING_DIMENSIONS = DIM
        settings.HYBRID_INDEX_DIR = cls.index_dir
        settings.HYBRID_RERANK_ENABLED = True
        settings.HYBRID_TOP_K = 3
        settings.HYBRID_CANDIDATE_K = 10

    @classmethod
    def tearDownClass(cls):
        for k, v in cls._orig.items():
            setattr(settings, k, v)
        if os.path.exists(cls.db_path):
            try:
                os.remove(cls.db_path)
            except Exception:
                pass
        if os.path.isdir(cls.index_dir):
            for name in os.listdir(cls.index_dir):
                try:
                    os.remove(os.path.join(cls.index_dir, name))
                except Exception:
                    pass
            try:
                os.rmdir(cls.index_dir)
            except Exception:
                pass

    def setUp(self):
        self.db = self.SessionLocal()
        self.db.query(DocumentChunk).delete()
        self.db.query(RagDocument).delete()
        self.db.commit()
        self._seed_chunks()
        self._embed_patch = patch.object(rag_service, "get_embeddings", side_effect=self._fake_embed)
        self._embed_patch.start()

        class StubCE:
            def rerank(self, query, documents, top_k=None, text_key="content"):
                q = set(query.lower().split())
                scored = []
                for d in documents:
                    tokens = set((d.get(text_key) or "").lower().split())
                    score = len(q & tokens) + float(d.get("hybrid_score") or 0)
                    item = dict(d)
                    item["ce_score"] = score
                    scored.append(item)
                scored.sort(key=lambda x: x["ce_score"], reverse=True)
                return scored[:top_k] if top_k else scored

        self._ce_patch = patch(
            "app.services.cross_encoder.CrossEncoderReranker",
            lambda *a, **k: StubCE(),
        )
        self._ce_patch.start()

        builder = IndexBuilder(index_dir=self.index_dir, dim=DIM)
        builder.build_all(self.db)
        set_index_builder(builder)

    def tearDown(self):
        self._embed_patch.stop()
        self._ce_patch.stop()
        self.db.close()

    def _fake_embed(self, text: str):
        t = text.lower()
        if "financial" in t or ("farmer" in t and "pm" not in t):
            return _fake_embedding(
                "Farmer Credit"
                + "Financial help for farmers includes short-term crop loans and "
                "interest subvention under Kisan Credit Card schemes."
            )
        if "pm kisan" in t or "eligibility" in t:
            return _fake_embedding(
                "PM-KISAN"
                + "PM Kisan Samman Nidhi eligibility requires landholding farmers "
                "to register with Aadhaar linked bank account for income support."
            )
        if "housing" in t or "loan subsidy" in t or "rural" in t:
            return _fake_embedding(
                "PMAY-G"
                + "Rural housing loan subsidy is available under PMAY-G for "
                "construction of houses for rural poor families."
            )
        return _fake_embedding(text)

    def _seed_chunks(self):
        docs_spec = [
            (
                "PM-KISAN",
                "PM Kisan Samman Nidhi eligibility requires landholding farmers "
                "to register with Aadhaar linked bank account for income support.",
                "agriculture",
            ),
            (
                "Farmer Credit",
                "Financial help for farmers includes short-term crop loans and "
                "interest subvention under Kisan Credit Card schemes.",
                "agriculture",
            ),
            (
                "PMAY-G",
                "Rural housing loan subsidy is available under PMAY-G for "
                "construction of houses for rural poor families.",
                "housing",
            ),
            (
                "Irrelevant Health",
                "Hospital bed occupancy and clinical triage protocols for ICU.",
                "health",
            ),
        ]
        for title, text, category in docs_spec:
            doc = RagDocument(
                id=str(uuid4()),
                title=title,
                file_url=f"local://{title}",
                category=category,
                scheme_name=title,
                source="test",
                indexing_status="INDEXED",
            )
            self.db.add(doc)
            self.db.flush()
            chunk = DocumentChunk(
                id=str(uuid4()),
                document_id=doc.id,
                content=text,
                embedding=_fake_embedding(title + text),
                chunk_index=0,
                metadata_dict={"scheme_name": title, "page": 1},
            )
            self.db.add(chunk)
        self.db.commit()

    def test_faiss_build_and_search(self):
        idx = FaissIndex(dim=4, index_dir=os.path.join(self.index_dir, "faiss_unit"))
        emb = [[1, 0, 0, 0], [0, 1, 0, 0], [0.9, 0.1, 0, 0]]
        ids = ["a", "b", "c"]
        idx.build_index(emb, ids)
        idx.save()
        loaded = FaissIndex(dim=4, index_dir=os.path.join(self.index_dir, "faiss_unit"))
        self.assertTrue(loaded.load())
        hits = loaded.search([1, 0, 0, 0], top_k=2)
        self.assertIn(hits[0]["chunk_id"], ("a", "c"))
        self.assertEqual(len(hits), 2)

    def test_bm25_keyword_search(self):
        idx = BM25Index(index_dir=os.path.join(self.index_dir, "bm25_unit"))
        idx.build_index(
            [
                {"id": "1", "text": "PM Kisan eligibility criteria for farmers"},
                {"id": "2", "text": "Hospital clinical triage guidelines"},
            ]
        )
        hits = idx.search("PM Kisan eligibility", top_k=2)
        self.assertTrue(hits)
        self.assertEqual(hits[0]["chunk_id"], "1")

    def test_merge_deduplicates(self):
        faiss = [
            {"chunk_id": "a", "score": 0.9},
            {"chunk_id": "b", "score": 0.5},
        ]
        bm25 = [
            {"chunk_id": "a", "score": 3.0},
            {"chunk_id": "c", "score": 2.0},
        ]
        merged = rag_service.merge_results(faiss, bm25)
        ids = [m["chunk_id"] for m in merged]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(set(ids), {"a", "b", "c"})

    def test_semantic_query(self):
        results = rag_service.hybrid_retrieve(
            self.db, "financial help for farmers", top_k=3, use_rerank=True
        )
        self.assertTrue(results)
        joined = " ".join(
            (r.get("content") or "") + (r.get("scheme_name") or "") for r in results
        ).lower()
        self.assertTrue(
            "farmer" in joined or "kisan" in joined or "credit" in joined
        )

    def test_keyword_query(self):
        results = rag_service.hybrid_retrieve(
            self.db, "PM Kisan eligibility", top_k=3, use_rerank=False
        )
        self.assertTrue(results)
        self.assertTrue(
            any("pm kisan" in (r.get("content") or "").lower() for r in results)
        )

    def test_mixed_query(self):
        results = rag_service.hybrid_retrieve(
            self.db, "loan subsidy for rural housing", top_k=3, use_rerank=True
        )
        self.assertTrue(results)
        top = results[0]
        blob = ((top.get("content") or "") + (top.get("scheme_name") or "")).lower()
        self.assertTrue("housing" in blob or "pmay" in blob or "subsidy" in blob)

    def test_no_duplicate_chunks(self):
        results = rag_service.hybrid_retrieve(
            self.db, "loan subsidy for rural housing", top_k=5
        )
        ids = [r["chunk_id"] for r in results]
        self.assertEqual(len(ids), len(set(ids)))

    def test_latency_budget(self):
        start = time.perf_counter()
        rag_service.hybrid_retrieve(
            self.db, "financial help for farmers", top_k=3, use_rerank=True
        )
        elapsed = time.perf_counter() - start
        self.assertLess(elapsed, 2.0)


if __name__ == "__main__":
    unittest.main()
