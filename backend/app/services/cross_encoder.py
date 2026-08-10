"""
CrossEncoder reranker for hybrid retrieval candidates.

Lazy-loads sentence-transformers CrossEncoder so API boot is not blocked.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("gramsakhi.cross_encoder")

DEFAULT_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"


class CrossEncoderReranker:
    def __init__(self, model_name: str = DEFAULT_MODEL):
        self.model_name = model_name
        self._model = None

    def _ensure_model(self):
        if self._model is not None:
            return self._model
        try:
            from sentence_transformers import CrossEncoder
        except ImportError as e:  # pragma: no cover
            raise ImportError(
                "sentence-transformers is required for CrossEncoder. "
                "pip install sentence-transformers"
            ) from e
        logger.info("Loading CrossEncoder model: %s", self.model_name)
        self._model = CrossEncoder(self.model_name)
        return self._model

    def rerank(
        self,
        query: str,
        documents: List[Dict[str, Any]],
        top_k: Optional[int] = None,
        text_key: str = "content",
    ) -> List[Dict[str, Any]]:
        if not documents:
            return []
        model = self._ensure_model()
        pairs = [[query, str(d.get(text_key) or "")] for d in documents]
        scores = model.predict(pairs)
        ranked = []
        for doc, score in zip(documents, scores):
            item = dict(doc)
            item["ce_score"] = float(score)
            ranked.append(item)
        ranked.sort(key=lambda x: x.get("ce_score", 0.0), reverse=True)
        if top_k is not None:
            ranked = ranked[: int(top_k)]
        return ranked


# Model load is expensive (~seconds); keep one instance per process.
_RERANKERS: Dict[str, CrossEncoderReranker] = {}


def get_reranker(model_name: str = DEFAULT_MODEL) -> CrossEncoderReranker:
    reranker = _RERANKERS.get(model_name)
    if reranker is None:
        reranker = CrossEncoderReranker(model_name)
        _RERANKERS[model_name] = reranker
    return reranker
