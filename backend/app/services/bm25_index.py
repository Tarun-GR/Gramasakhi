"""
BM25 keyword index over chunk texts.

Complements FAISS semantic search for exact / acronym-heavy queries.
"""

from __future__ import annotations

import json
import logging
import pickle
import re
from pathlib import Path
from typing import Any, Dict, List, Sequence

logger = logging.getLogger("gramsakhi.bm25_index")

try:
    from rank_bm25 import BM25Okapi
except ImportError:  # pragma: no cover
    BM25Okapi = None


def _tokenize(text: str) -> List[str]:
    return re.findall(r"[a-z0-9]+", (text or "").lower())


class BM25Index:
    """Disk-backed BM25Okapi index."""

    def __init__(self, index_dir: str | Path):
        if BM25Okapi is None:
            raise ImportError("rank_bm25 is required. pip install rank_bm25")
        self.index_dir = Path(index_dir)
        self.index_dir.mkdir(parents=True, exist_ok=True)
        self.meta_path = self.index_dir / "bm25_meta.json"
        self.model_path = self.index_dir / "bm25_model.pkl"
        self.ids: List[str] = []
        self.texts: List[str] = []
        self.bm25: Any = None

    def build_index(self, documents: Sequence[Dict[str, Any]]) -> None:
        """
        documents: [{"id": chunk_id, "text": content}, ...]
        """
        self.ids = [str(d["id"]) for d in documents]
        self.texts = [str(d.get("text") or "") for d in documents]
        tokenized = [_tokenize(t) for t in self.texts]
        self.bm25 = BM25Okapi(tokenized) if tokenized else None
        # Small corpora can yield IDF≈0 for rare terms; keep keyword ranking useful.
        if self.bm25 is not None:
            for term, value in list(self.bm25.idf.items()):
                if value <= 0:
                    self.bm25.idf[term] = 0.25
        logger.info("BM25 index built with %s documents", len(self.ids))

    def search(self, query: str, top_k: int = 10) -> List[Dict[str, Any]]:
        if not self.bm25 or not self.ids:
            return []
        tokens = _tokenize(query)
        if not tokens:
            return []
        scores = self.bm25.get_scores(tokens)
        ranked = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)
        results: List[Dict[str, Any]] = []
        for idx, score in ranked[: int(top_k)]:
            if float(score) <= 0:
                continue
            results.append(
                {
                    "chunk_id": self.ids[idx],
                    "score": float(score),
                    "source": "bm25",
                }
            )
        return results

    def save(self) -> None:
        self.meta_path.write_text(
            json.dumps({"ids": self.ids, "texts": self.texts}),
            encoding="utf-8",
        )
        with open(self.model_path, "wb") as f:
            pickle.dump(self.bm25, f)
        logger.info("BM25 index saved to %s", self.index_dir)

    def load(self) -> bool:
        if not self.meta_path.exists() or not self.model_path.exists():
            return False
        meta = json.loads(self.meta_path.read_text(encoding="utf-8"))
        self.ids = meta.get("ids") or []
        self.texts = meta.get("texts") or []
        with open(self.model_path, "rb") as f:
            self.bm25 = pickle.load(f)
        logger.info("BM25 index loaded (%s documents)", len(self.ids))
        return True
