"""Conversation orchestration for GramSakhi chat (Phase 6).

Loads history, stores messages, rewrites follow-ups, then calls the existing
RAG evidence-gated pipeline with the rewritten retrieval query.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.conversation import Conversation, Message
from app.models.family_account import FamilyAccount
from app.services import rag as rag_service
from app.services.query_rewriter import rewrite_query

logger = logging.getLogger("gramsakhi.conversation")


def _as_uuid_str(value: Any) -> str:
    return str(value) if value is not None else ""


def get_owned_conversation(
    db: Session,
    conversation_id: str,
    citizen_account_id: str,
) -> Conversation:
    """
    Load conversation only if owned by the citizen.

    Missing OR foreign ownership → 404 (do not reveal existence).
    """
    conv = (
        db.query(Conversation)
        .filter(Conversation.id == conversation_id)
        .first()
    )
    if not conv or _as_uuid_str(conv.citizen_account_id) != _as_uuid_str(citizen_account_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found.",
        )
    return conv


def create_conversation(
    db: Session,
    citizen: FamilyAccount,
    *,
    language: Optional[str] = None,
    title: Optional[str] = None,
) -> Conversation:
    conv = Conversation(
        citizen_account_id=citizen.id,
        language=language or "en",
        title=title,
        is_active=True,
    )
    db.add(conv)
    db.flush()
    return conv


def load_recent_messages(
    db: Session,
    conversation_id: str,
    *,
    limit: Optional[int] = None,
) -> List[Message]:
    lim = int(limit if limit is not None else settings.CONVERSATION_HISTORY_LIMIT)
    lim = max(1, lim)
    rows = (
        db.query(Message)
        .filter(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.desc())
        .limit(lim)
        .all()
    )
    rows.reverse()  # chronological
    return rows


def messages_as_history(messages: List[Message]) -> List[Dict[str, str]]:
    return [{"role": m.role, "content": m.content} for m in messages]


def store_message(
    db: Session,
    conversation_id: str,
    *,
    role: str,
    content: str,
    rewritten_query: Optional[str] = None,
    language: Optional[str] = None,
    evidence_status: Optional[str] = None,
) -> Message:
    msg = Message(
        conversation_id=conversation_id,
        role=role,
        content=content,
        rewritten_query=rewritten_query,
        language=language,
        evidence_status=evidence_status,
    )
    db.add(msg)
    db.flush()
    return msg


def handle_citizen_chat(
    db: Session,
    citizen: FamilyAccount,
    *,
    message: str,
    conversation_id: Optional[str] = None,
    language: Optional[str] = None,
    skip_llm: bool = False,
) -> Dict[str, Any]:
    """
    Full Phase 6 turn:

    ownership → load history → store user msg → rewrite → RAG(rewritten)
    → store assistant → return response
    """
    original_query = (message or "").strip()
    if not original_query:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Message cannot be empty.",
        )

    created_new = False
    if conversation_id:
        conv = get_owned_conversation(db, conversation_id, str(citizen.id))
    else:
        conv = create_conversation(db, citizen, language=language)
        created_new = True

    # History BEFORE the new user turn (for rewriting)
    prior = load_recent_messages(db, str(conv.id))
    history = messages_as_history(prior)

    user_msg = store_message(
        db,
        str(conv.id),
        role="user",
        content=original_query,  # store exactly what the user typed
        language=language or conv.language,
    )

    rewrite = rewrite_query(
        original_query,
        history,
        language=language or conv.language,
    )
    rewritten_query = rewrite["rewritten_query"] or original_query
    user_msg.rewritten_query = rewritten_query if rewrite.get("was_rewritten") else None

    if rewrite.get("active_scheme"):
        conv.active_scheme_context = rewrite["active_scheme"]
    if not conv.title:
        conv.title = original_query[:120]
    conv.updated_at = datetime.now(timezone.utc)

    logger.info(
        "chat conversation_id=%s user_message_id=%s rewritten=%s method=%s",
        conv.id,
        user_msg.id,
        rewritten_query if rewrite.get("was_rewritten") else "(unchanged)",
        rewrite.get("method"),
    )

    # Commit conversation + user turn BEFORE long RAG/live work so a failed
    # live ingest rollback cannot wipe the conversation row (FK on messages).
    db.commit()
    db.refresh(conv)
    db.refresh(user_msg)

    # Retrieval / validation / generation use the REWRITTEN query only.
    # Live gov fallback activates only if indexed evidence is insufficient.
    rag_result = rag_service.answer_with_evidence_gate(
        db,
        rewritten_query,
        language=language or conv.language,
        conversation_context=history,
        skip_llm=skip_llm,
        enable_live_fallback=bool(settings.LIVE_GOV_FALLBACK_ENABLED),
    )

    answer = rag_result.get("answer") or (
        "I don't have enough reliable information to answer that."
    )
    validated = bool(rag_result.get("validated"))
    llm_invoked = bool(rag_result.get("llm_invoked"))
    evidence_status = "SUPPORTED" if validated and llm_invoked else (
        "SUPPORTED" if validated else "UNSUPPORTED"
    )
    if rag_result.get("reason") == "llm_unavailable":
        evidence_status = "SUPPORTED"  # validator passed; generation failed

    try:
        assistant_msg = store_message(
            db,
            str(conv.id),
            role="assistant",
            content=answer,
            language=language or conv.language,
            evidence_status=evidence_status,
        )
        db.commit()
        db.refresh(assistant_msg)
    except Exception as e:  # noqa: BLE001
        db.rollback()
        logger.warning("assistant message persist failed: %s", type(e).__name__)
        # Still return the grounded answer even if history write fails
        assistant_msg = type("M", (), {"id": None})()

    db.refresh(conv)
    db.refresh(user_msg)

    return {
        "conversation_id": str(conv.id),
        "created_new_conversation": created_new,
        "message_id": str(user_msg.id),
        "assistant_message_id": str(assistant_msg.id),
        "original_query": original_query,
        "rewritten_query": rewritten_query,
        "was_rewritten": bool(rewrite.get("was_rewritten")),
        "rewrite_method": rewrite.get("method"),
        "answer": answer,
        "confidence": rag_result.get("confidence"),
        "reason": rag_result.get("reason"),
        "signals": rag_result.get("signals"),
        "sources": rag_result.get("sources") or [],
        "validated": validated,
        "llm_invoked": llm_invoked,
        "llm_model": rag_result.get("llm_model"),
        "llm_latency_ms": rag_result.get("llm_latency_ms"),
        "knowledge_source": rag_result.get("knowledge_source"),
        "live_status": rag_result.get("live_status"),
        "active_scheme_context": conv.active_scheme_context,
        "error": rag_result.get("error"),
    }
