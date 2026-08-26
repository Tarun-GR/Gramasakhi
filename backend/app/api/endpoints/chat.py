"""Citizen chat API — conversation memory + history UX + rewritten-query RAG."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core import security as jwt_security
from app.core.config import settings
from app.database.session import get_db
from app.models.citizen_account import CitizenAccount
from app.schemas.chat import (
    ChatRequest,
    ChatResponse,
    ConversationCreateRequest,
    ConversationCreateResponse,
    ConversationHistoryResponse,
    ConversationListResponse,
    ConversationMessageOut,
    ConversationAssistanceStateOut,
    ConversationRenameRequest,
    ConversationSummaryOut,
    ConversationUpdateResponse,
)
from app.services import conversation_service

router = APIRouter()
security_scheme = HTTPBearer()
logger = logging.getLogger("gramsakhi.chat")


def get_current_citizen(
    credentials: HTTPAuthorizationCredentials = Depends(security_scheme),
    db: Session = Depends(get_db),
) -> CitizenAccount:
    token = credentials.credentials
    try:
        payload = jwt_security.decode_access_token(token)
        if not jwt_security.token_use_allowed(payload, "citizen"):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token credentials.",
            )
        account_id: Optional[str] = payload.get("sub")
        if not account_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token credentials.",
            )
        account = db.query(CitizenAccount).filter(CitizenAccount.id == account_id).first()
        if not account or not account.is_active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Citizen account not found or inactive.",
            )
        return account
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication token is expired or invalid.",
        )


def _message_out(m) -> ConversationMessageOut:
    d = conversation_service.message_to_dict(m)
    return ConversationMessageOut(**d)


# ---------------------------------------------------------------------------
# Conversation history management (must be registered before /{conversation_id})
# ---------------------------------------------------------------------------


@router.get("/conversations", response_model=ConversationListResponse)
def list_conversations(
    limit: int = Query(30, ge=1, le=50),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    citizen: CitizenAccount = Depends(get_current_citizen),
):
    rows, total = conversation_service.list_conversations(
        db, str(citizen.id), limit=limit, offset=offset
    )
    return ConversationListResponse(
        conversations=[
            ConversationSummaryOut(**conversation_service.conversation_to_summary(c))
            for c in rows
        ],
        total=total,
        limit=limit,
        offset=offset,
        has_more=(offset + len(rows)) < total,
    )


@router.get("/conversations/search", response_model=ConversationListResponse)
def search_conversations(
    q: str = Query("", max_length=200),
    limit: int = Query(30, ge=1, le=50),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    citizen: CitizenAccount = Depends(get_current_citizen),
):
    rows, total = conversation_service.search_conversations(
        db, str(citizen.id), q, limit=limit, offset=offset
    )
    return ConversationListResponse(
        conversations=[
            ConversationSummaryOut(**conversation_service.conversation_to_summary(c))
            for c in rows
        ],
        total=total,
        limit=limit,
        offset=offset,
        has_more=(offset + len(rows)) < total,
    )


@router.post("/conversations", response_model=ConversationCreateResponse)
def create_empty_conversation(
    body: ConversationCreateRequest,
    db: Session = Depends(get_db),
    citizen: CitizenAccount = Depends(get_current_citizen),
):
    conv = conversation_service.create_conversation(
        db, citizen, language=body.language, title=body.title
    )
    db.commit()
    db.refresh(conv)
    return ConversationCreateResponse(
        id=str(conv.id),
        title=conv.title,
        language=conv.language,
        created_at=conv.created_at.isoformat() if conv.created_at else None,
    )


@router.get("/conversations/{conversation_id}", response_model=ConversationHistoryResponse)
def get_conversation_detail(
    conversation_id: str,
    limit: int = Query(50, ge=1, le=100),
    before: Optional[str] = Query(None, description="ISO timestamp cursor for older messages"),
    db: Session = Depends(get_db),
    citizen: CitizenAccount = Depends(get_current_citizen),
):
    """Read-only history load — does not run RAG / live / Ollama."""
    conv = conversation_service.get_owned_conversation(
        db, conversation_id, str(citizen.id)
    )
    before_dt = None
    if before:
        try:
            before_dt = datetime.fromisoformat(before.replace("Z", "+00:00"))
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid before cursor.",
            ) from exc
    messages, has_more = conversation_service.load_messages_page(
        db, str(conv.id), limit=limit, before=before_dt
    )
    activity = conv.last_message_at or conv.updated_at
    assistance_state = conversation_service.build_assistance_state_for_history(conv, messages)
    from app.services.assistance_continuity import sanitize_assistance_state_for_api

    safe_state = sanitize_assistance_state_for_api(assistance_state)
    return ConversationHistoryResponse(
        conversation_id=str(conv.id),
        title=conv.title,
        language=conv.language,
        active_scheme_context=conv.active_scheme_context,
        updated_at=conv.updated_at.isoformat() if conv.updated_at else None,
        last_message_at=activity.isoformat() if activity else None,
        messages=[_message_out(m) for m in messages],
        has_more=has_more,
        assistance_state=(
            ConversationAssistanceStateOut(**safe_state) if safe_state else None
        ),
    )


@router.patch("/conversations/{conversation_id}", response_model=ConversationUpdateResponse)
def rename_conversation(
    conversation_id: str,
    body: ConversationRenameRequest,
    db: Session = Depends(get_db),
    citizen: CitizenAccount = Depends(get_current_citizen),
):
    conv = conversation_service.rename_conversation(
        db, conversation_id, str(citizen.id), body.title
    )
    return ConversationUpdateResponse(
        id=str(conv.id),
        title=conv.title or "",
        updated_at=conv.updated_at.isoformat() if conv.updated_at else None,
    )


@router.delete("/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_conversation(
    conversation_id: str,
    db: Session = Depends(get_db),
    citizen: CitizenAccount = Depends(get_current_citizen),
):
    conversation_service.soft_delete_conversation(
        db, conversation_id, str(citizen.id)
    )
    return None


@router.post("", response_model=ChatResponse)
@router.post("/", response_model=ChatResponse)
def citizen_chat(
    body: ChatRequest,
    db: Session = Depends(get_db),
    citizen: CitizenAccount = Depends(get_current_citizen),
):
    """
    Process a citizen message with conversation memory.

    Retrieval uses the rewritten query; the stored/displayed message is original.
    """
    conv_id = str(body.conversation_id) if body.conversation_id else None
    try:
        result = conversation_service.handle_citizen_chat(
            db,
            citizen,
            message=body.message,
            conversation_id=conv_id,
            language=body.language,
            stt_language=body.stt_language,
            input_mode=body.input_mode,
            voice_request_id=body.voice_request_id,
        )
    except HTTPException:
        raise
    except SQLAlchemyError:
        raise
    except Exception as exc:
        logger.exception("chat_pipeline_failed err=%s", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="GramSakhi could not complete your request. Please try again.",
        ) from exc
    return ChatResponse(**{k: result[k] for k in ChatResponse.model_fields if k in result})


@router.get("/{conversation_id}", response_model=ConversationHistoryResponse)
def get_conversation_history(
    conversation_id: str,
    db: Session = Depends(get_db),
    citizen: CitizenAccount = Depends(get_current_citizen),
):
    """Legacy alias for GET /conversations/{id} — read-only, no AI pipeline."""
    return get_conversation_detail(
        conversation_id=conversation_id,
        limit=max(settings.CONVERSATION_HISTORY_LIMIT * 5, 50),
        before=None,
        db=db,
        citizen=citizen,
    )
