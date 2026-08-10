import os
import hashlib
import math
import json
import uuid
from collections import OrderedDict
import urllib.request
import urllib.error
from io import BytesIO
from typing import List, Dict, Any, Optional
from fastapi import UploadFile, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.models.rag import RagDocument, DocumentChunk
from app.core.config import settings
from app.services.storage import upload_rag_document, delete_rag_document

# Try importing pypdf for PDF extraction
try:
    import pypdf
except ImportError:
    pypdf = None

# Max file size: 10MB
MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024
ALLOWED_EXTENSIONS = {".pdf", ".txt"}

def extract_text_from_bytes(content: bytes, ext: str) -> List[Dict[str, Any]]:
    """Extracts text contents from file bytes, page by page. Returns list of chunk sources."""
    pages_data = []
    ext = ext.lower()

    if ext == ".txt":
        text = content.decode("utf-8", errors="ignore")
        pages_data.append({"page": 1, "text": text})
    elif ext == ".pdf":
        if pypdf is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="PDF processing library (pypdf) is not installed on the server."
            )
        try:
            stream = BytesIO(content)
            reader = pypdf.PdfReader(stream)
            for idx, page in enumerate(reader.pages):
                text = page.extract_text() or ""
                pages_data.append({"page": idx + 1, "text": text})
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Failed to parse PDF document: {str(e)}"
            )
    return pages_data

def chunk_text(pages_data: List[Dict[str, Any]], chunk_size: int = 500, overlap: int = 100) -> List[Dict[str, Any]]:
    """Splits text into chunks of specified characters size with overlap."""
    chunks = []
    chunk_index = 0

    for page_info in pages_data:
        text = page_info["text"]
        page_num = page_info["page"]
        
        # Clean text
        text = " ".join(text.split())
        
        start = 0
        while start < len(text):
            end = start + chunk_size
            chunk_content = text[start:end]
            
            # Trim chunk
            chunk_content = chunk_content.strip()
            if chunk_content:
                chunks.append({
                    "chunk_index": chunk_index,
                    "content": chunk_content,
                    "metadata": {"page": page_num}
                })
                chunk_index += 1
            
            start += (chunk_size - overlap)
            
    return chunks


def _select_chunks_for_query(
    chunks: List[Dict[str, Any]],
    query: str,
    *,
    max_chunks: int = 48,
) -> List[Dict[str, Any]]:
    """Keep query-overlapping chunks when truncating a large live PDF."""
    if len(chunks) <= max_chunks:
        return chunks
    import re

    tokens = [t for t in re.findall(r"[a-zA-Z0-9\-]{3,}", (query or "").lower())]
    if not tokens:
        return chunks[:max_chunks]
    scored: List[tuple] = []
    for c in chunks:
        content = (c.get("content") or "").lower()
        score = sum(3 for t in tokens if t in content)
        # Small bias for earlier chunks (cover / definitions)
        score += max(0, 3 - int(c.get("chunk_index") or 0) // 20)
        scored.append((score, c))
    scored.sort(key=lambda x: (-x[0], int(x[1].get("chunk_index") or 0)))
    selected = [c for s, c in scored[:max_chunks] if s > 0]
    if len(selected) < max(8, max_chunks // 4):
        # Fallback: keep head of document if overlap is weak
        return chunks[:max_chunks]
    selected.sort(key=lambda c: int(c.get("chunk_index") or 0))
    return selected

def get_embeddings(text: str) -> List[float]:
    """
    Retrieves embedding from the configured provider (Ollama) using settings configurations.
    Uses POST /api/embed Ollama endpoint.
    """
    if settings.EMBEDDING_PROVIDER != "ollama":
        raise ValueError(f"Unsupported embedding provider: {settings.EMBEDDING_PROVIDER}")
        
    if not settings.OLLAMA_API_URL:
        raise ValueError("Ollama API URL is not configured. Please check settings.")

    url = f"{settings.OLLAMA_API_URL.rstrip('/')}/api/embed"
    payload = json.dumps({
        "model": settings.EMBEDDING_MODEL,
        "input": text
    }).encode("utf-8")
    
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    
    try:
        # Use 15.0s timeout to allow model loading if needed
        with urllib.request.urlopen(req, timeout=15.0) as response:
            res = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")
        if "not found" in body or "pull" in body or e.code == 404:
            raise ValueError(f"Ollama embedding model '{settings.EMBEDDING_MODEL}' is not installed. Please run: ollama pull {settings.EMBEDDING_MODEL}")
        raise ValueError(f"Ollama embedding request failed with status {e.code}: {body}")
    except (urllib.error.URLError, TimeoutError) as e:
        reason = getattr(e, "reason", str(e))
        raise ConnectionError(f"Ollama embedding service is unreachable at {settings.OLLAMA_API_URL}. Details: {str(reason)}")
    except Exception as e:
        raise ValueError(f"Unexpected connection failure during Ollama embedding: {str(e)}")

    embeddings = res.get("embeddings")
    if not embeddings or not isinstance(embeddings, list) or len(embeddings) == 0:
        raise ValueError("Ollama response did not contain standard embeddings array.")
        
    embedding = embeddings[0]
    if len(embedding) != settings.EMBEDDING_DIMENSIONS:
        raise ValueError(f"Incompatible embedding dimensions. Provider returned {len(embedding)} dimensions, expected {settings.EMBEDDING_DIMENSIONS}.")
        
    return embedding

def get_embeddings_batch(texts: List[str]) -> List[List[float]]:
    """
    Retrieves embeddings for a list of texts from Ollama.

    Large live PDFs can produce many chunks; send them in small batches so the
    local Ollama runner does not crash mid-request.
    """
    if not texts:
        return []
        
    if settings.EMBEDDING_PROVIDER != "ollama":
        raise ValueError(f"Unsupported embedding provider: {settings.EMBEDDING_PROVIDER}")
        
    if not settings.OLLAMA_API_URL:
        raise ValueError("Ollama API URL is not configured. Please check settings.")

    url = f"{settings.OLLAMA_API_URL.rstrip('/')}/api/embed"
    batch_size = 8
    all_embeddings: List[List[float]] = []

    for start in range(0, len(texts), batch_size):
        batch = texts[start : start + batch_size]
        payload = json.dumps({
            "model": settings.EMBEDDING_MODEL,
            "input": batch,
        }).encode("utf-8")

        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=180.0) as response:
                res = json.loads(response.read().decode("utf-8"))
        except Exception as e:
            # One retry helps when the local Ollama runner briefly drops
            import time as _time

            _time.sleep(1.0)
            try:
                with urllib.request.urlopen(req, timeout=180.0) as response:
                    res = json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as e2:
                body = e2.read().decode("utf-8", errors="ignore")
                if "not found" in body or "pull" in body or e2.code == 404:
                    raise ValueError(
                        f"Ollama embedding model '{settings.EMBEDDING_MODEL}' is not installed. "
                        f"Please run: ollama pull {settings.EMBEDDING_MODEL}"
                    )
                raise ValueError(
                    f"Ollama embedding request failed with status {e2.code}: {body}"
                ) from e
            except (urllib.error.URLError, TimeoutError) as e2:
                reason = getattr(e2, "reason", str(e2))
                raise ConnectionError(
                    f"Ollama embedding service is unreachable at {settings.OLLAMA_API_URL}. "
                    f"Details: {str(reason)}"
                ) from e
            except Exception as e2:
                raise ValueError(
                    f"Unexpected connection failure during Ollama embedding: {str(e2)}"
                ) from e

        embeddings = res.get("embeddings")
        if not embeddings or not isinstance(embeddings, list) or len(embeddings) != len(batch):
            raise ValueError(
                f"Ollama response did not contain expected embeddings array of size {len(batch)}."
            )
        all_embeddings.extend(embeddings)

    embeddings = all_embeddings
    if len(embeddings) != len(texts):
        raise ValueError(f"Ollama response did not contain expected standard embeddings array of size {len(texts)}.")
        
    for idx, embedding in enumerate(embeddings):
        if len(embedding) != settings.EMBEDDING_DIMENSIONS:
            raise ValueError(f"Incompatible embedding dimensions at index {idx}. Provider returned {len(embedding)} dimensions, expected {settings.EMBEDDING_DIMENSIONS}.")
            
    return embeddings


def ingest_raw_bytes(
    db: Session,
    uploaded_by: Any,
    title: str,
    category: str,
    version: str,
    contents: bytes,
    ext: str,
    scheme_name: Optional[str] = None,
    ministry: Optional[str] = None,
    state: Optional[str] = None,
    source: Optional[str] = None,
    language: Optional[str] = None,
    document_type: Optional[str] = None,
    extra_metadata: Optional[Dict[str, Any]] = None,
    document_hash: Optional[str] = None,
) -> RagDocument:
    """
    Shared ingestion entry used by manual upload and web ingestion.

    Reuses extract_text_from_bytes → chunk_text → get_embeddings_batch.
    Does not implement retrieval.
    """
    ext = ext.lower()
    if not ext.startswith("."):
        ext = f".{ext}"
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file type. Only {', '.join(ALLOWED_EXTENSIONS)} are allowed.",
        )

    file_size = len(contents)
    if file_size > MAX_FILE_SIZE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File exceeds maximum size of 10MB.",
        )
    if file_size == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty.",
        )

    uuid_str = str(uuid.uuid4())
    storage_path = f"knowledge-base/schemes/{uuid_str}{ext}"
    content_type = "application/pdf" if ext == ".pdf" else "text/plain"

    try:
        stored_path = upload_rag_document(storage_path, contents, content_type)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Storage upload failed: {str(e)}",
        )

    uploaded_in_storage = True
    cleanup_path = stored_path

    try:
        pages_data = extract_text_from_bytes(contents, ext)
        if not pages_data or all(not p.get("text", "").strip() for p in pages_data):
            raise ValueError("Document contains no readable text.")

        chunks = chunk_text(pages_data)
        if not chunks:
            raise ValueError("No clean chunks could be generated from document text.")

        # Live government PDFs can be huge — keep ingest fast and Ollama-stable.
        # Prefer chunks that overlap the citizen query so we do not drop the answer
        # that appears later in a long PDF (first-N truncation was a known failure).
        ingestion_type = (extra_metadata or {}).get("ingestion_type")
        if ingestion_type in ("live_web", "web") and len(chunks) > 48:
            live_query = str((extra_metadata or {}).get("live_query") or "")
            chunks = _select_chunks_for_query(chunks, live_query, max_chunks=48)

        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        resolved_hash = document_hash or (extra_metadata or {}).get("document_hash") or (
            (extra_metadata or {}).get("content_hash")
        )

        doc = RagDocument(
            hospital_id=None,
            uploaded_by=uploaded_by,
            title=title,
            file_url=stored_path,
            category=category,
            version=version,
            scheme_name=scheme_name or title,
            ministry=ministry,
            state=state,
            source=source,
            language=language,
            document_type=document_type,
            indexing_status="PROCESSING",
            document_hash=resolved_hash,
            last_ingested_at=now,
        )
        db.add(doc)
        db.flush()

        chunk_contents = [chk["content"] for chk in chunks]
        vectors = get_embeddings_batch(chunk_contents)

        for idx, chk in enumerate(chunks):
            meta = dict(chk["metadata"] or {})
            if scheme_name or title:
                meta.setdefault("scheme_name", scheme_name or title)
            if source:
                meta.setdefault("source", source)
            meta.setdefault("document", title)
            if ministry:
                meta.setdefault("ministry", ministry)
            if state:
                meta.setdefault("state", state)
            if category:
                meta.setdefault("category", category)
            if resolved_hash:
                meta.setdefault("document_hash", resolved_hash)
                meta.setdefault("version_hash", resolved_hash)
            if extra_metadata:
                meta.update({k: v for k, v in extra_metadata.items() if v is not None})
            chunk_record = DocumentChunk(
                document_id=doc.id,
                chunk_index=chk["chunk_index"],
                content=chk["content"],
                embedding=vectors[idx],
                metadata_dict=meta,
            )
            db.add(chunk_record)

        doc.indexing_status = "INDEXED"
        db.commit()
        db.refresh(doc)
        return doc

    except HTTPException as he:
        import traceback

        traceback.print_exc()
        db.rollback()
        if uploaded_in_storage:
            try:
                delete_rag_document(cleanup_path)
            except Exception as clean_err:
                print(
                    f"[ERROR] [RAG INGESTION] Compensating storage cleanup failed for {cleanup_path}: {clean_err}",
                    flush=True,
                )
        raise he
    except Exception as e:
        import traceback

        traceback.print_exc()
        db.rollback()
        if uploaded_in_storage:
            try:
                delete_rag_document(cleanup_path)
            except Exception as clean_err:
                print(
                    f"[ERROR] [RAG INGESTION] Compensating storage cleanup failed for {cleanup_path}: {clean_err}",
                    flush=True,
                )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Incomplete RAG Ingestion Pipeline. Database transaction rolled back. Error: {str(e)}",
        )


def ingest_document(
    db: Session,
    uploaded_by: Any,
    title: str,
    category: str,
    version: str,
    file: UploadFile,
    scheme_name: Optional[str] = None,
    ministry: Optional[str] = None,
    state: Optional[str] = None,
    source: Optional[str] = None,
    language: Optional[str] = None,
    document_type: Optional[str] = None,
    hospital_id: Any = None,  # ignored; retained for call-site compatibility
) -> RagDocument:
    """Upload path: read UploadFile then call shared ingest_raw_bytes."""
    filename = file.filename or "document.txt"
    ext = os.path.splitext(filename)[1].lower()
    contents = file.file.read()
    return ingest_raw_bytes(
        db=db,
        uploaded_by=uploaded_by,
        title=title,
        category=category,
        version=version,
        contents=contents,
        ext=ext,
        scheme_name=scheme_name,
        ministry=ministry,
        state=state,
        source=source,
        language=language,
        document_type=document_type,
    )


def _minmax_normalize(scores: Dict[str, float]) -> Dict[str, float]:
    if not scores:
        return {}
    vals = list(scores.values())
    lo, hi = min(vals), max(vals)
    if hi - lo < 1e-12:
        return {k: 1.0 for k in scores}
    return {k: (v - lo) / (hi - lo) for k, v in scores.items()}


def merge_results(
    faiss_results: List[Dict[str, Any]],
    bm25_results: List[Dict[str, Any]],
    *,
    faiss_weight: Optional[float] = None,
    bm25_weight: Optional[float] = None,
) -> List[Dict[str, Any]]:
    """
    Score-normalize FAISS + BM25 hits, weighted sum, then deduplicate by chunk_id.
    """
    w_f = float(faiss_weight if faiss_weight is not None else settings.HYBRID_FAISS_WEIGHT)
    w_b = float(bm25_weight if bm25_weight is not None else settings.HYBRID_BM25_WEIGHT)

    faiss_scores = {r["chunk_id"]: float(r["score"]) for r in faiss_results}
    bm25_scores = {r["chunk_id"]: float(r["score"]) for r in bm25_results}
    faiss_n = _minmax_normalize(faiss_scores)
    bm25_n = _minmax_normalize(bm25_scores)

    all_ids = set(faiss_n) | set(bm25_n)
    merged: List[Dict[str, Any]] = []
    for cid in all_ids:
        f = faiss_n.get(cid, 0.0)
        b = bm25_n.get(cid, 0.0)
        merged.append(
            {
                "chunk_id": cid,
                "faiss_score": faiss_scores.get(cid, 0.0),
                "bm25_score": bm25_scores.get(cid, 0.0),
                "faiss_norm": f,
                "bm25_norm": b,
                "hybrid_score": (w_f * f) + (w_b * b),
                "sources": [
                    s
                    for s, present in (("faiss", cid in faiss_scores), ("bm25", cid in bm25_scores))
                    if present
                ],
            }
        )
    merged.sort(key=lambda x: x["hybrid_score"], reverse=True)
    # Deduplicate (already unique by chunk_id; keep stable order)
    seen = set()
    deduped: List[Dict[str, Any]] = []
    for item in merged:
        if item["chunk_id"] in seen:
            continue
        seen.add(item["chunk_id"])
        deduped.append(item)
    return deduped


# Query-side embedding cache. Ingestion deliberately bypasses this so stored
# vectors always come from a fresh provider call.
_QUERY_EMBED_CACHE: "OrderedDict[str, List[float]]" = OrderedDict()


def get_query_embedding(query: str) -> List[float]:
    key = (
        f"{settings.EMBEDDING_MODEL}:{settings.EMBEDDING_DIMENSIONS}:"
        f"{(query or '').strip().lower()}"
    )
    cached = _QUERY_EMBED_CACHE.get(key)
    if cached is not None:
        _QUERY_EMBED_CACHE.move_to_end(key)
        return cached

    vector = get_embeddings(query)
    _QUERY_EMBED_CACHE[key] = vector
    while len(_QUERY_EMBED_CACHE) > max(1, int(settings.QUERY_EMBED_CACHE_SIZE)):
        _QUERY_EMBED_CACHE.popitem(last=False)
    return vector


def hybrid_retrieve(
    db: Session,
    query: str,
    *,
    top_k: Optional[int] = None,
    candidate_k: Optional[int] = None,
    use_rerank: Optional[bool] = None,
    query_embedding: Optional[List[float]] = None,
) -> List[Dict[str, Any]]:
    """
    FAISS (semantic) + BM25 (keyword) → merge → CrossEncoder rerank → top-k chunks.
    Uses indexes built from existing DB embeddings (no re-embedding).
    """
    from app.services.cross_encoder import get_reranker
    from app.services.index_builder import get_index_builder

    top_k = int(top_k if top_k is not None else settings.HYBRID_TOP_K)
    candidate_k = int(candidate_k if candidate_k is not None else settings.HYBRID_CANDIDATE_K)
    use_rerank = settings.HYBRID_RERANK_ENABLED if use_rerank is None else bool(use_rerank)

    builder = get_index_builder()
    if not builder.faiss.ids and not builder.bm25.ids:
        # Auto-build once from DB if indexes are empty
        builder.build_all(db)
        from app.services.index_builder import set_index_builder

        set_index_builder(builder)

    if query_embedding is None:
        query_embedding = get_query_embedding(query)

    faiss_hits = builder.faiss.search(query_embedding, top_k=candidate_k)
    bm25_hits = builder.bm25.search(query, top_k=candidate_k)
    combined = merge_results(faiss_hits, bm25_hits)

    # Hydrate chunk payload from lookup / DB
    hydrated: List[Dict[str, Any]] = []
    for item in combined[: max(candidate_k, top_k * 2)]:
        cid = item["chunk_id"]
        meta = builder.chunk_meta.get(cid)
        if not meta:
            row = db.query(DocumentChunk).filter(DocumentChunk.id == cid).first()
            if not row:
                continue
            doc = row.document
            meta = {
                "content": row.content,
                "document_title": doc.title if doc else None,
                "scheme_name": getattr(doc, "scheme_name", None) if doc else None,
                "metadata": row.metadata_dict,
            }
        hydrated.append(
            {
                **item,
                "content": meta.get("content"),
                "document_title": meta.get("document_title"),
                "scheme_name": meta.get("scheme_name"),
                "metadata": meta.get("metadata"),
                "source": meta.get("source"),
                "state": meta.get("state"),
                "ministry": meta.get("ministry"),
                "page": meta.get("page"),
                "similarity_score": float(item.get("hybrid_score") or 0.0),
                # Private: reused by the evidence validator so it never re-embeds.
                "_embedding": meta.get("embedding"),
            }
        )

    if use_rerank and hydrated:
        try:
            reranker = get_reranker(settings.CROSS_ENCODER_MODEL)
            reranked = reranker.rerank(query, hydrated, top_k=top_k)
            for r in reranked:
                r["similarity_score"] = float(r.get("ce_score", r.get("hybrid_score", 0.0)))
            return reranked
        except Exception:
            # Graceful degradation if CrossEncoder unavailable
            pass

    return hydrated[:top_k]


def _pgvector_retrieve(
    db: Session,
    query_text: str,
    limit: int = 5,
) -> List[Dict[str, Any]]:
    """Legacy pgvector path kept as fallback when hybrid indexes cannot run."""
    query_vector = get_embeddings(query_text)

    sql = text(
        """
        SELECT 
            c.id AS chunk_id, 
            c.content AS content, 
            d.title AS document_title,
            d.scheme_name AS scheme_name,
            c.metadata AS metadata,
            1 - (c.embedding <=> CAST(:query_vector AS vector)) AS similarity_score
        FROM document_chunks c
        JOIN rag_documents d ON c.document_id = d.id
        WHERE 1 - (c.embedding <=> CAST(:query_vector AS vector)) > 0.70
        ORDER BY similarity_score DESC
        LIMIT :limit
        """
    )

    vector_str = "[" + ",".join(map(str, query_vector)) + "]"
    params = {"query_vector": vector_str, "limit": limit}

    rs = db.execute(sql, params).fetchall()
    return [
        {
            "chunk_id": str(r.chunk_id),
            "content": r.content,
            "document_title": r.document_title,
            "scheme_name": getattr(r, "scheme_name", None),
            "metadata": getattr(r, "metadata", None),
            "similarity_score": float(r.similarity_score),
        }
        for r in rs
    ]


def retrieve_similar_chunks(
    db: Session,
    query_text: str,
    limit: int = 5,
    hospital_id: Any = None,  # ignored; retained for compatibility
) -> List[Dict[str, Any]]:
    """
    Public retrieval API — hybrid FAISS + BM25 + CrossEncoder when available,
    otherwise falls back to pgvector cosine search.
    """
    _ = hospital_id
    try:
        return hybrid_retrieve(db, query_text, top_k=limit)
    except Exception:
        # Preserve previous behaviour if hybrid stack fails (e.g. missing deps / SQLite)
        try:
            return _pgvector_retrieve(db, query_text, limit=limit)
        except Exception:
            return []


def strip_private_fields(docs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Drop internal keys (e.g. raw embeddings) before returning docs over the API."""
    return [{k: v for k, v in d.items() if not k.startswith("_")} for d in docs]


LLM_CONTROLLED_FAILURE_ANSWER = (
    "I could not generate an answer right now. Please try again shortly."
)


def _call_llm_after_validation(
    query: str,
    docs: List[Dict[str, Any]],
    *,
    language: Optional[str] = None,
    conversation_context: Any = None,
) -> Dict[str, Any]:
    """
    LLM entrypoint — MUST only be invoked after EvidenceValidator PASS.

    Returns the llm_service result dict (success/answer/error). Callers must
    not invent an ungrounded answer when success is False.
    """
    from app.services.evidence_validator import SAFE_FALLBACK_ANSWER
    from app.services.llm_service import generate_answer

    # Guardrail: refuse empty evidence even if caller bypasses gate
    if not docs:
        return {
            "success": False,
            "error": "No evidence provided",
            "answer": SAFE_FALLBACK_ANSWER,
        }

    return generate_answer(
        query=query,
        evidence=docs,
        language=language,
        conversation_context=conversation_context,
    )


def answer_with_evidence_gate(
    db: Session,
    query: str,
    *,
    top_k: Optional[int] = None,
    use_rerank: Optional[bool] = None,
    validator: Any = None,
    skip_llm: bool = False,
    language: Optional[str] = None,
    conversation_context: Any = None,
    enable_live_fallback: bool = False,
) -> Dict[str, Any]:
    """
    Retrieve → Validate Evidence → (PASS → LLM) | (FAIL → optional live gov fallback).

    Hard gate: LLM is never called when validation fails.
    Live government search runs ONLY when indexed evidence is insufficient and
    enable_live_fallback is True. Live path reuses existing ingestion + this gate
    (with live fallback disabled) — never PDF→LLM shortcuts.
    """
    from app.services.evidence_validator import (
        EvidenceValidator,
        SAFE_FALLBACK_ANSWER,
        ValidationResult,
    )

    q = (query or "").strip()
    v: EvidenceValidator = validator or EvidenceValidator()

    # Queries that can never pass the gate skip retrieval entirely (saves an embed call).
    if settings.EVIDENCE_GATE_ENABLED:
        pre = v.validate(q, [])
        if pre.reason in ("empty_query", "query_too_short"):
            return {
                "answer": SAFE_FALLBACK_ANSWER,
                "confidence": "low",
                "reason": pre.reason,
                "signals": pre.signals,
                "sources": [],
                "validated": False,
                "llm_invoked": False,
                "knowledge_source": "none",
            }

    docs: List[Dict[str, Any]] = []
    if q:
        try:
            docs = hybrid_retrieve(db, q, top_k=top_k, use_rerank=use_rerank)
        except Exception:
            try:
                docs = _pgvector_retrieve(db, q, limit=int(top_k or settings.HYBRID_TOP_K))
            except Exception:
                docs = []

    if not settings.EVIDENCE_GATE_ENABLED:
        # Still never invent: require at least one doc
        if not docs:
            return {
                "answer": SAFE_FALLBACK_ANSWER,
                "confidence": "low",
                "reason": "no_evidence",
                "sources": [],
                "validated": False,
                "llm_invoked": False,
                "knowledge_source": "none",
            }
        if skip_llm:
            return {
                "answer": None,
                "confidence": "medium",
                "reason": "gate_disabled",
                "sources": strip_private_fields(docs),
                "validated": True,
                "llm_invoked": False,
                "knowledge_source": "indexed",
            }
        llm_result = _call_llm_after_validation(
            q, docs, language=language, conversation_context=conversation_context
        )
        # Tests may mock this to return a plain string
        if isinstance(llm_result, str):
            return {
                "answer": llm_result,
                "confidence": "medium",
                "reason": "gate_disabled",
                "sources": strip_private_fields(docs),
                "validated": True,
                "llm_invoked": True,
                "knowledge_source": "indexed",
            }
        if llm_result.get("success"):
            return {
                "answer": llm_result.get("answer"),
                "confidence": "medium",
                "reason": "gate_disabled",
                "sources": strip_private_fields(docs),
                "validated": True,
                "llm_invoked": True,
                "llm_model": llm_result.get("model"),
                "llm_latency_ms": llm_result.get("latency_ms"),
                "knowledge_source": "indexed",
            }
        return {
            "answer": LLM_CONTROLLED_FAILURE_ANSWER,
            "confidence": "low",
            "reason": "llm_unavailable",
            "error": llm_result.get("error"),
            "sources": strip_private_fields(docs),
            "validated": True,
            "llm_invoked": True,
            "llm_model": llm_result.get("model"),
            "llm_latency_ms": llm_result.get("latency_ms"),
            "knowledge_source": "indexed",
        }

    result: ValidationResult = v.validate(q, docs)

    if not result.ok:
        # Indexed evidence insufficient — optional live government fallback
        if enable_live_fallback and settings.LIVE_GOV_FALLBACK_ENABLED and q:
            try:
                from app.services.live_gov_retrieval_service import (
                    LIVE_EVIDENCE_INSUFFICIENT,
                    LIVE_EVIDENCE_VALIDATED,
                    NO_TRUSTED_INFORMATION_FOUND,
                    NO_VERIFIED_INFORMATION,
                    try_live_gov_fallback,
                )

                print(
                    f"LIVE_FALLBACK_TRIGGERED validator_ok=False "
                    f"reason={result.reason} live_fallback_enabled=True "
                    f"query={q[:160]!r}",
                    flush=True,
                )
                live = try_live_gov_fallback(
                    db,
                    q,
                    language=language,
                    conversation_context=conversation_context,
                )
                live_rid = live.get("live_request_id")
                live_meta_base = {
                    "ingested": live.get("ingested"),
                    "latency_ms": live.get("latency_ms"),
                    "live_request_id": live_rid,
                    "evidence_ready": live.get("evidence_ready"),
                    "accepted_url": live.get("accepted_url"),
                    "index_stats": live.get("index_stats"),
                }
                if live.get("ingested"):
                    # Second pass through the SAME gate — never recurse into live again
                    second = answer_with_evidence_gate(
                        db,
                        q,
                        top_k=top_k,
                        use_rerank=use_rerank,
                        validator=validator,
                        skip_llm=skip_llm,
                        language=language,
                        conversation_context=conversation_context,
                        enable_live_fallback=False,
                    )
                    if second.get("validated"):
                        second["knowledge_source"] = "live_government"
                        second["live_status"] = LIVE_EVIDENCE_VALIDATED
                        second["live_meta"] = live_meta_base
                        second["live_request_id"] = live_rid
                        return second
                    return {
                        "answer": NO_VERIFIED_INFORMATION,
                        "confidence": "low",
                        "reason": "live_evidence_insufficient",
                        "signals": second.get("signals") or result.signals,
                        "sources": [],
                        "validated": False,
                        "llm_invoked": False,
                        "knowledge_source": "none",
                        "live_status": LIVE_EVIDENCE_INSUFFICIENT,
                        "live_meta": live_meta_base,
                        "live_request_id": live_rid,
                    }
                return {
                    "answer": NO_VERIFIED_INFORMATION,
                    "confidence": "low",
                    "reason": "no_trusted_information",
                    "signals": result.signals,
                    "sources": [],
                    "validated": False,
                    "llm_invoked": False,
                    "knowledge_source": "none",
                    "live_status": live.get("status") or NO_TRUSTED_INFORMATION_FOUND,
                    "live_meta": {
                        "latency_ms": live.get("latency_ms"),
                        "live_request_id": live_rid,
                    },
                    "live_request_id": live_rid,
                }
            except Exception as e:  # noqa: BLE001
                # Live failures must not crash the API
                print(f"Live gov fallback error: {type(e).__name__}: {e}", flush=True)
                from app.services.live_gov_retrieval_service import NO_VERIFIED_INFORMATION

                return {
                    "answer": NO_VERIFIED_INFORMATION,
                    "confidence": "low",
                    "reason": "live_fallback_error",
                    "signals": result.signals,
                    "sources": [],
                    "validated": False,
                    "llm_invoked": False,
                    "knowledge_source": "none",
                    "live_status": "LIVE_FALLBACK_ERROR",
                }

        return {
            "answer": SAFE_FALLBACK_ANSWER,
            "confidence": "low",
            "reason": result.reason,
            "signals": result.signals,
            "sources": [],
            "validated": False,
            "llm_invoked": False,
            "knowledge_source": "none",
        }

    # PASS — only now may LLM run, and only on the chunks that survived pruning
    evidence = result.evidence or docs
    if skip_llm:
        return {
            "answer": None,
            "confidence": result.confidence,
            "reason": result.reason,
            "signals": result.signals,
            "sources": strip_private_fields(evidence),
            "validated": True,
            "llm_invoked": False,
            "knowledge_source": "indexed",
        }

    llm_result = _call_llm_after_validation(
        q, evidence, language=language, conversation_context=conversation_context
    )
    # Tests may mock this helper to return a plain string
    if isinstance(llm_result, str):
        return {
            "answer": llm_result,
            "confidence": result.confidence,
            "reason": result.reason,
            "signals": result.signals,
            "sources": strip_private_fields(evidence),
            "validated": True,
            "llm_invoked": True,
            "knowledge_source": "indexed",
        }
    if llm_result.get("success"):
        return {
            "answer": llm_result.get("answer"),
            "confidence": result.confidence,
            "reason": result.reason,
            "signals": result.signals,
            "sources": strip_private_fields(evidence),
            "validated": True,
            "llm_invoked": True,
            "llm_model": llm_result.get("model"),
            "llm_latency_ms": llm_result.get("latency_ms"),
            "knowledge_source": "indexed",
        }
    return {
        "answer": LLM_CONTROLLED_FAILURE_ANSWER,
        "confidence": "low",
        "reason": "llm_unavailable",
        "error": llm_result.get("error"),
        "signals": result.signals,
        "sources": strip_private_fields(evidence),
        "validated": True,
        "llm_invoked": True,
        "llm_model": llm_result.get("model"),
        "llm_latency_ms": llm_result.get("latency_ms"),
        "knowledge_source": "indexed",
    }