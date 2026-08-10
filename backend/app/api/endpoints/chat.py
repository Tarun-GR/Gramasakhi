"""Citizen chat API — conversation memory + rewritten-query RAG (Phase 6)."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.core.config import settings
from app.database.session import get_db
from app.models.family_account import FamilyAccount
from app.schemas.chat import (
    ChatRequest,
    ChatResponse,
    ConversationHistoryResponse,
    ConversationMessageOut,
)
from app.services import conversation_service

router = APIRouter()
security_scheme = HTTPBearer()


def get_current_citizen(
    credentials: HTTPAuthorizationCredentials = Depends(security_scheme),
    db: Session = Depends(get_db),
) -> FamilyAccount:
    token = credentials.credentials
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        account_id: Optional[str] = payload.get("sub")
        if not account_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token credentials.",
            )
        account = db.query(FamilyAccount).filter(FamilyAccount.id == account_id).first()
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


@router.post("", response_model=ChatResponse)
@router.post("/", response_model=ChatResponse)
def citizen_chat(
    body: ChatRequest,
    db: Session = Depends(get_db),
    citizen: FamilyAccount = Depends(get_current_citizen),
):
    """
    Process a citizen message with conversation memory.

    Retrieval uses the rewritten query; the stored/displayed message is original.
    """
    conv_id = str(body.conversation_id) if body.conversation_id else None
    result = conversation_service.handle_citizen_chat(
        db,
        citizen,
        message=body.message,
        conversation_id=conv_id,
        language=body.language,
    )
    return ChatResponse(**{k: result[k] for k in ChatResponse.model_fields if k in result})


@router.get("/{conversation_id}", response_model=ConversationHistoryResponse)
def get_conversation_history(
    conversation_id: str,
    db: Session = Depends(get_db),
    citizen: FamilyAccount = Depends(get_current_citizen),
):
    conv = conversation_service.get_owned_conversation(
        db, conversation_id, str(citizen.id)
    )
    messages = conversation_service.load_recent_messages(
        db,
        str(conv.id),
        limit=max(settings.CONVERSATION_HISTORY_LIMIT * 5, 50),
    )
    return ConversationHistoryResponse(
        conversation_id=str(conv.id),
        active_scheme_context=conv.active_scheme_context,
        messages=[
            ConversationMessageOut(
                id=str(m.id),
                role=m.role,
                content=m.content,
                rewritten_query=m.rewritten_query,
                evidence_status=m.evidence_status,
                created_at=m.created_at.isoformat() if m.created_at else None,
            )
            for m in messages
        ],
    )
