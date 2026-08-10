"""
FAISS vector index built from existing DB embeddings.

Does not re-embed documents — uses vectors already stored via the ingestion pipeline.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import numpy as np

logger = logging.getLogger("gramsakhi.faiss_index")

try:
    import faiss
except ImportError:  # pragma: no cover
    faiss = None


def _l2_normalize(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms = np.maximum(norms, 1e-12)
    return matrix / norms


class FaissIndex:
    """Disk-backed FAISS IndexFlatIP over precomputed embeddings."""

    def __init__(self, dim: int, index_dir: str | Path):
        if faiss is None:
            raise ImportError("faiss is required. pip install faiss-cpu")
        self.dim = int(dim)
        self.index_dir = Path(index_dir)
        self.index_dir.mkdir(parents=True, exist_ok=True)
        self.index_path = self.index_dir / "faiss.index"
        self.ids_path = self.index_dir / "faiss_ids.json"
        self.index = faiss.IndexFlatIP(self.dim)
        self.ids: List[str] = []

    def build_index(self, embeddings: Sequence[Sequence[float]], ids: Sequence[str]) -> None:
        if len(embeddings) != len(ids):
            raise ValueError("embeddings and ids length mismatch")
        if not embeddings:
            self.index = faiss.IndexFlatIP(self.dim)
            self.ids = []
            return

        matrix = np.asarray(embeddings, dtype=np.float32)
        if matrix.ndim != 2 or matrix.shape[1] != self.dim:
            raise ValueError(
                f"Expected embedding shape (N, {self.dim}), got {matrix.shape}"
            )
        matrix = _l2_normalize(matrix)
        self.index = faiss.IndexFlatIP(self.dim)
        self.index.add(matrix)
        self.ids = [str(i) for i in ids]
        logger.info("FAISS index built with %s vectors (dim=%s)", len(self.ids), self.dim)

    def search(self, query_embedding: Sequence[float], top_k: int = 10) -> List[Dict[str, Any]]:
        if self.index.ntotal == 0 or not self.ids:
            return []
        q = np.asarray(query_embedding, dtype=np.float32).reshape(1, -1)
        if q.shape[1] != self.dim:
            raise ValueError(f"Query dim {q.shape[1]} != index dim {self.dim}")
        q = _l2_normalize(q)
        k = min(int(top_k), self.index.ntotal)
        scores, indices = self.index.search(q, k)
        results: List[Dict[str, Any]] = []
        for score, idx in zip(scores[0], indices[0]):
            if idx < 0 or idx >= len(self.ids):
                continue
            results.append(
                {
                    "chunk_id": self.ids[idx],
                    "score": float(score),
                    "source": "faiss",
                }
            )
        return results

    def save(self) -> None:
        faiss.write_index(self.index, str(self.index_path))
        self.ids_path.write_text(json.dumps(self.ids), encoding="utf-8")
        logger.info("FAISS index saved to %s", self.index_path)

    def load(self) -> bool:
        if not self.index_path.exists() or not self.ids_path.exists():
            return False
        self.index = faiss.read_index(str(self.index_path))
        if self.index.d != self.dim:
            logger.warning(
                "FAISS dim mismatch (found %s, expected %s)", self.index.d, self.dim
            )
            return False
        self.ids = json.loads(self.ids_path.read_text(encoding="utf-8"))
        logger.info("FAISS index loaded (%s vectors)", self.index.ntotal)
        return True
