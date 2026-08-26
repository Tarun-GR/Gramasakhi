from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form, Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from typing import Optional
from uuid import UUID
import os

from app.database.session import get_db
from app.models.user import User
from app.models.rag import RagDocument, DocumentChunk
from app.core import security
from app.core.config import settings
from app.services.audit import log_audit
from app.services import rag as rag_service
from app.services.storage import delete_rag_document, create_signed_url
from app.schemas.super_admin_schema import (
    SuperAdminLoginRequest,
    SuperAdminTokenResponse,
    DashboardSummaryResponse,
    KnowledgeDocumentDetailResponse,
    KnowledgeDocumentListResponse,
    WebIngestRequest,
    WebIngestResponse,
)
from app.services.web_ingestion_service import WebIngestionService
from app.services.auth_rate_limit import auth_rate_limit_ok, client_ip

router = APIRouter()
security_scheme = HTTPBearer()


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security_scheme),
    db: Session = Depends(get_db),
) -> User:
    from jose import JWTError

    token = credentials.credentials
    try:
        payload = security.decode_access_token(token)
        if not security.token_use_allowed(payload, "admin"):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token credentials.",
            )
        user_id: str = payload.get("sub")
        if user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token credentials.",
            )
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found.",
            )
        if not user.is_active or user.deleted_at is not None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This user account is inactive or has been deleted.",
            )
        return user
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication token is expired or invalid.",
        )


def get_current_super_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role not in ("SUPER_ADMIN", "ADMIN"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden. Access is restricted to platform admins.",
        )
    return current_user


def _doc_response(
    doc: RagDocument, db: Session, uploader_name: Optional[str] = None
) -> KnowledgeDocumentDetailResponse:
    if uploader_name is None and doc.uploaded_by:
        u = db.query(User).filter(User.id == doc.uploaded_by).first()
        if u:
            uploader_name = f"{u.first_name} {u.last_name}"
    chunks_count = db.query(DocumentChunk).filter(DocumentChunk.document_id == doc.id).count()
    return KnowledgeDocumentDetailResponse(
        id=doc.id,
        uploaded_by=doc.uploaded_by,
        uploader_name=uploader_name,
        title=doc.title,
        file_url=f"/api/v1/super-admin/knowledge-base/{doc.id}/download",
        category=doc.category,
        version=doc.version,
        scheme_name=getattr(doc, "scheme_name", None),
        ministry=getattr(doc, "ministry", None),
        state=getattr(doc, "state", None),
        source=getattr(doc, "source", None),
        language=getattr(doc, "language", None),
        document_type=getattr(doc, "document_type", None),
        indexing_status=getattr(doc, "indexing_status", None) or "INDEXED",
        created_at=doc.created_at,
        updated_at=doc.updated_at,
        chunk_count=chunks_count,
    )


@router.post("/auth/login", response_model=SuperAdminTokenResponse)
def super_admin_login(request: SuperAdminLoginRequest, http_request: Request, db: Session = Depends(get_db)):
    rate_key = f"{client_ip(http_request)}:{(request.email or '').lower()}"
    generic = "Incorrect email or password."

    user = db.query(User).filter(User.email == request.email).first()
    if (
        not user
        or not user.is_active
        or user.deleted_at is not None
        or user.role not in ("SUPER_ADMIN", "ADMIN")
        or not security.verify_password(request.password, user.password_hash)
    ):
        if not auth_rate_limit_ok(rate_key, bucket="login"):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many attempts. Please wait before trying again.",
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=generic,
        )

    token = security.create_access_token(subject=str(user.id), token_use="admin")
    return {
        "accessToken": token,
        "user": {
            "id": user.id,
            "email": user.email,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "role": user.role,
        },
    }


@router.get("/dashboard/summary", response_model=DashboardSummaryResponse)
def get_dashboard_summary(
    current_admin: User = Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    total_docs = db.query(RagDocument).count()
    indexed = db.query(RagDocument).filter(RagDocument.indexing_status == "INDEXED").count()
    processing = (
        db.query(RagDocument)
        .filter(RagDocument.indexing_status.in_(["UPLOADED", "PROCESSING"]))
        .count()
    )
    failed = db.query(RagDocument).filter(RagDocument.indexing_status == "FAILED").count()
    return {
        "total_documents": total_docs,
        "indexed_documents": indexed,
        "processing_documents": processing,
        "failed_documents": failed,
    }


@router.get("/knowledge-base", response_model=KnowledgeDocumentListResponse)
def list_knowledge_base(
    page: int = 1,
    limit: int = 20,
    search: Optional[str] = None,
    category: Optional[str] = None,
    current_admin: User = Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    query = db.query(RagDocument)
    if search:
        query = query.filter(RagDocument.title.ilike(f"%{search}%"))
    if category and category != "all":
        query = query.filter(RagDocument.category == category)

    query = query.order_by(RagDocument.created_at.desc())
    total = query.count()
    total_pages = (total + limit - 1) // limit if total > 0 else 0
    items = query.offset((page - 1) * limit).limit(limit).all()

    return {
        "items": [_doc_response(doc, db) for doc in items],
        "page": page,
        "limit": limit,
        "total": total,
        "total_pages": total_pages,
    }


@router.post(
    "/knowledge-base/upload",
    response_model=KnowledgeDocumentDetailResponse,
    status_code=status.HTTP_201_CREATED,
)
def upload_knowledge_document(
    title: str = Form(...),
    category: str = Form(...),
    version: str = Form("1.0"),
    scheme_name: Optional[str] = Form(None),
    ministry: Optional[str] = Form(None),
    state: Optional[str] = Form(None),
    source: Optional[str] = Form(None),
    language: Optional[str] = Form(None),
    document_type: Optional[str] = Form(None),
    file: UploadFile = File(...),
    current_admin: User = Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    try:
        doc = rag_service.ingest_document(
            db=db,
            uploaded_by=current_admin.id,
            title=title,
            category=category,
            version=version,
            file=file,
            scheme_name=scheme_name,
            ministry=ministry,
            state=state,
            source=source,
            language=language,
            document_type=document_type,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to complete ingestion pipeline.",
        )

    log_audit(
        db=db,
        user_id=current_admin.id,
        action="CREATE",
        table_name="rag_documents",
        record_id=doc.id,
        new_values={
            "title": doc.title,
            "category": doc.category,
            "version": doc.version,
            "scheme_name": scheme_name,
            "file_url": doc.file_url,
        },
    )

    up_name = f"{current_admin.first_name} {current_admin.last_name}"
    return _doc_response(doc, db, uploader_name=up_name)


@router.get("/knowledge-base/{document_id}", response_model=KnowledgeDocumentDetailResponse)
def get_knowledge_document(
    document_id: UUID,
    current_admin: User = Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    doc = db.query(RagDocument).filter(RagDocument.id == str(document_id)).first()
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")
    return _doc_response(doc, db)


@router.get("/knowledge-base/{document_id}/chunks")
def get_document_chunks(
    document_id: UUID,
    current_admin: User = Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    doc = db.query(RagDocument).filter(RagDocument.id == str(document_id)).first()
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")

    chunks = (
        db.query(DocumentChunk)
        .filter(DocumentChunk.document_id == doc.id)
        .order_by(DocumentChunk.chunk_index.asc())
        .all()
    )
    return [
        {
            "id": c.id,
            "chunk_index": c.chunk_index,
            "content": c.content,
            "metadata": c.metadata_dict,
            "created_at": c.created_at,
        }
        for c in chunks
    ]


@router.delete("/knowledge-base/{document_id}", status_code=status.HTTP_200_OK)
def delete_knowledge_document(
    document_id: UUID,
    current_admin: User = Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    doc = db.query(RagDocument).filter(RagDocument.id == str(document_id)).first()
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")

    file_url = doc.file_url
    if file_url.startswith("knowledge-base/"):
        try:
            delete_rag_document(file_url)
        except Exception as e:
            print(f"[RAG SERVICE] Failed to delete Supabase storage object {file_url}: {e}")
    elif file_url.startswith("/static/uploads/"):
        filename = file_url.split("/")[-1]
        file_path = os.path.join("static/uploads", filename)
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception as e:
                print(f"[RAG SERVICE] Failed to delete file {file_path}: {e}")

    log_audit(
        db=db,
        user_id=current_admin.id,
        action="DELETE",
        table_name="rag_documents",
        record_id=doc.id,
        old_values={"title": doc.title, "file_url": doc.file_url, "category": doc.category},
    )

    db.delete(doc)
    db.commit()
    return {"message": "Document and all associated chunks deleted successfully."}


@router.get("/knowledge-base/{document_id}/download")
def download_knowledge_document(
    document_id: UUID,
    current_admin: User = Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    doc = db.query(RagDocument).filter(RagDocument.id == str(document_id)).first()
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")

    file_url = doc.file_url
    if file_url.startswith("knowledge-base/"):
        try:
            signed_url = create_signed_url(file_url, expires_in=60)
            return RedirectResponse(signed_url, status_code=307)
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to generate download URL from storage: {str(e)}",
            )
    elif file_url.startswith("/static/uploads/"):
        name = file_url.rstrip("/").split("/")[-1]
        if not name or ".." in name or "/" in name or "\\" in name:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid file path.")
        local_path = os.path.abspath(os.path.join("static", "uploads", name))
        root = os.path.abspath(os.path.join("static", "uploads"))
        if not (local_path == root or local_path.startswith(root + os.sep)):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid file path.")
        if not os.path.isfile(local_path):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document file not found.")
        return FileResponse(local_path, filename=name, media_type="application/octet-stream")

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Unknown file URL storage scheme.",
    )


@router.get("/ingest/sources")
def list_ingest_sources(current_admin: User = Depends(get_current_super_admin)):
    """List high-level government portal sources and curated catalog schemes."""
    return {
        "sources": GOV_SOURCES,
        "catalog_count": len(list_catalog_schemes()),
        "schemes": list_catalog_schemes(),
    }


@router.get("/gov-registry")
def get_gov_source_registry(current_admin: User = Depends(get_current_super_admin)):
    """View trusted government source registry (IGOD-backed + curated)."""
    from app.services import gov_source_registry as registry

    registry.ensure_curated_hosts_merged()
    return {
        "stats": registry.registry_stats(),
        "sources": registry.list_sources(enabled_only=False),
        "rejected": (registry.load_registry().get("rejected") or [])[-50:],
    }


@router.post("/gov-registry/refresh")
def refresh_gov_source_registry(
    current_admin: User = Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    """Refresh trusted registry from IGOD. Does not run on citizen queries."""
    from app.services import gov_source_registry as registry

    try:
        summary = registry.refresh_registry_from_igod()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(
            status_code=502,
            detail=f"Registry refresh failed: {type(e).__name__}",
        ) from e
    log_audit(
        db=db,
        user_id=current_admin.id,
        action="UPDATE",
        table_name="gov_source_registry",
        record_id=str(current_admin.id),
        new_values={"operation": "igod_registry_refresh", **(summary or {})},
    )
    return {"status": "ok", "summary": summary, "stats": registry.registry_stats()}


@router.get("/gov-registry/health")
def gov_registry_health(current_admin: User = Depends(get_current_super_admin)):
    """Inspect registry freshness, per-source health, and live acquisition status."""
    from app.core.config import settings
    from app.services import gov_source_registry as registry
    from app.services.acquisition.browser_playwright import playwright_available
    from app.services.acquisition.reliability import acquire_stats_snapshot

    sources = registry.list_sources(enabled_only=False)
    by_health: dict = {}
    for s in sources:
        h = s.get("health") or ("active" if s.get("enabled", True) else "disabled")
        by_health.setdefault(h, 0)
        by_health[h] += 1
    snap = acquire_stats_snapshot()
    return {
        "stats": registry.registry_stats(),
        "health_counts": by_health,
        "acquisition": {
            "browser_enabled": bool(getattr(settings, "LIVE_GOV_BROWSER_ENABLED", True)),
            "browser_runtime_available": playwright_available(),
            "max_browser_actions": int(
                getattr(settings, "LIVE_GOV_MAX_BROWSER_ACTIONS", 8)
            ),
            "max_pages": int(getattr(settings, "LIVE_GOV_MAX_PAGES", 6)),
            "max_documents": int(getattr(settings, "LIVE_GOV_MAX_DOCUMENTS", 6)),
            "attempts": snap.get("attempts"),
            "successes": snap.get("successes"),
            "failures": snap.get("failures"),
            "by_method": snap.get("by_method"),
            "by_failure_code": snap.get("by_failure_code"),
            "capabilities": snap.get("capabilities"),
            "recent_source_health": snap.get("recent_health"),
        },
        "sources": [
            {
                "id": s.get("id"),
                "name": s.get("name"),
                "domain": s.get("domain"),
                "enabled": s.get("enabled"),
                "health": s.get("health"),
                "level": s.get("level"),
                "source_directory": s.get("source_directory"),
            }
            for s in sources
        ],
    }


@router.patch("/gov-registry/{source_id}")
def update_gov_source(
    source_id: str,
    payload: dict,
    current_admin: User = Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    """Enable/disable a trusted source (admin only)."""
    from app.services import gov_source_registry as registry

    if "enabled" not in (payload or {}):
        raise HTTPException(status_code=422, detail="enabled boolean is required")
    try:
        updated = registry.set_source_enabled(source_id, bool(payload.get("enabled")))
    except KeyError:
        raise HTTPException(status_code=404, detail="Unknown source_id") from None
    log_audit(
        db=db,
        user_id=current_admin.id,
        action="UPDATE",
        table_name="gov_source_registry",
        record_id=source_id,
        new_values={"enabled": updated.get("enabled"), "health": updated.get("health")},
    )
    return {"status": "ok", "source": updated}


@router.post("/ingest/web", response_model=WebIngestResponse)
def ingest_from_web(
    request: WebIngestRequest,
    current_admin: User = Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    """
    Fetch allowlisted central/state government pages and index them via the
    existing RAG ingest pipeline (extract → chunk → embed → store).
    """
    service = WebIngestionService(db=db, uploaded_by=current_admin.id)
    result = service.ingest_source(
        source=request.source,
        max_docs=request.max_docs,
        query=request.query,
        urls=request.urls,
        crawl_links=request.crawl_links,
    )
    log_audit(
        db=db,
        user_id=current_admin.id,
        action="CREATE",
        table_name="rag_documents",
        record_id=str(current_admin.id),
        new_values={
            "ingestion_type": "web",
            "source": request.source,
            "query": request.query,
            "summary": result.get("summary"),
        },
    )
    return result


@router.post("/indexes/rebuild")
def rebuild_hybrid_indexes(
    current_admin: User = Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    """
    Rebuild FAISS + BM25 indexes from existing document_chunks embeddings.
    Does not re-embed documents.
    """
    from app.services.index_builder import IndexBuilder, set_index_builder

    builder = IndexBuilder()
    stats = builder.build_all(db)
    set_index_builder(builder)
    log_audit(
        db=db,
        user_id=current_admin.id,
        action="UPDATE",
        table_name="document_chunks",
        record_id=str(current_admin.id),
        new_values={"operation": "hybrid_index_rebuild", **stats},
    )
    return {"status": "ok", **stats}


@router.post("/retrieve/hybrid")
def retrieve_hybrid(
    payload: dict,
    current_admin: User = Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    """Admin/debug endpoint for hybrid retrieval (FAISS + BM25 + CrossEncoder)."""
    query = (payload or {}).get("query") or ""
    if not query.strip():
        raise HTTPException(status_code=422, detail="query is required")
    top_k = int((payload or {}).get("top_k") or 5)
    use_rerank = (payload or {}).get("use_rerank")
    results = rag_service.hybrid_retrieve(
        db,
        query,
        top_k=top_k,
        use_rerank=use_rerank if use_rerank is not None else None,
    )
    results = rag_service.strip_private_fields(results)
    return {"query": query, "count": len(results), "results": results}


@router.post("/query")
def grounded_query(
    payload: dict,
    current_admin: User = Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    """
    Grounded Q&A: hybrid retrieve → evidence sufficiency gate → LLM (or safe fallback).
    LLM is never invoked when validation fails.
    """
    query = (payload or {}).get("query") or (payload or {}).get("question") or ""
    if not query.strip():
        raise HTTPException(status_code=422, detail="query is required")
    top_k = int((payload or {}).get("top_k") or 5)
    result = rag_service.answer_with_evidence_gate(db, query, top_k=top_k)
    return {
        "query": query,
        "answer": result.get("answer"),
        "confidence": result.get("confidence"),
        "reason": result.get("reason"),
        "validated": result.get("validated"),
        "llm_invoked": result.get("llm_invoked"),
        "sources": result.get("sources") or [],
        "signals": result.get("signals"),
    }


# Alias matching master-prompt path style (same handler)
@router.post("/admin/ingest/web", response_model=WebIngestResponse, include_in_schema=False)
def ingest_from_web_alias(
    request: WebIngestRequest,
    current_admin: User = Depends(get_current_super_admin),
    db: Session = Depends(get_db),
):
    return ingest_from_web(request, current_admin, db)
