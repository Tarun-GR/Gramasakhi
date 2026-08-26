"""IVR-A3 chat adapter — transcription → existing handle_citizen_chat pipeline."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional

from fastapi import HTTPException
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.schemas.ivr import IvrChatResponse
from app.services import conversation_service
from app.services.ivr.constants import (
    CHAT_FAILURE_GOODBYE_PROMPT,
    CHAT_FAILURE_RETRY_PROMPT,
    CHAT_MISSING_TRANSCRIPTION_PROMPT,
    CHAT_UNAVAILABLE_PROMPT,
    IVR_TO_CHAT_LANGUAGE,
    MAX_CHAT_RETRY_ATTEMPTS,
    MAX_IVR_TRANSCRIPTION_LENGTH,
)
from app.services.ivr.call_state import (
    IvrCallState,
    StateTransitionError,
    can_accept_question,
    end_turn,
    increment_turn,
    require_states,
    set_state,
    transition,
)
from app.services.ivr.ivr_auth import IvrAuthError, get_ivr_citizen
from app.services.ivr.language_session import get_session_store
from app.services.ivr.session_cleanup import terminate_ivr_session

logger = logging.getLogger("gramsakhi.ivr.chat")


class IvrChatFailure(str, Enum):
    MISSING_CALL_SID = "missing_call_sid"
    UNKNOWN_CALL_SID = "unknown_call_sid"
    NO_LANGUAGE = "no_language"
    MISSING_TRANSCRIPTION = "missing_transcription"
    EMPTY_TRANSCRIPTION = "empty_transcription"
    OVERSIZED_TRANSCRIPTION = "oversized_transcription"
    UNAUTHORIZED = "unauthorized"
    CONVERSATION_FAILURE = "conversation_failure"
    CHAT_TIMEOUT = "chat_timeout"
    CHAT_CLIENT_ERROR = "chat_client_error"
    CHAT_SERVER_ERROR = "chat_server_error"
    MALFORMED_CHAT_RESPONSE = "malformed_chat_response"


@dataclass
class IvrChatOutcome:
    response: IvrChatResponse
    failure: Optional[IvrChatFailure] = None


def resolve_chat_language(call_sid: str) -> Optional[str]:
    lang = get_session_store().get_language(call_sid)
    if not lang:
        return None
    return IVR_TO_CHAT_LANGUAGE.get(lang)


def map_chat_evidence_status(chat_result: dict[str, Any]) -> str:
    """Preserve backend evidence semantics (SUPPORTED / PARTIAL / UNSUPPORTED)."""
    validated = bool(chat_result.get("validated"))
    llm_invoked = bool(chat_result.get("llm_invoked"))
    if chat_result.get("reason") == "llm_unavailable" and validated:
        return "SUPPORTED"
    if validated and llm_invoked:
        return "SUPPORTED"
    if validated:
        return "SUPPORTED"
    live_status = (chat_result.get("live_status") or "").upper()
    if live_status == "FAILED":
        return "UNSUPPORTED"
    sources = chat_result.get("sources") or []
    if sources and not validated:
        return "PARTIAL"
    return "UNSUPPORTED"


def validate_chat_service_result(result: Any) -> tuple[bool, Optional[IvrChatFailure]]:
    if not isinstance(result, dict):
        return False, IvrChatFailure.MALFORMED_CHAT_RESPONSE
    if "conversation_id" not in result or "answer" not in result:
        return False, IvrChatFailure.MALFORMED_CHAT_RESPONSE
    answer = result.get("answer")
    if not isinstance(answer, str):
        return False, IvrChatFailure.MALFORMED_CHAT_RESPONSE
    return True, None


def _mask_call_sid(call_sid: str) -> str:
    sid = (call_sid or "").strip()
    if len(sid) <= 8:
        return "***"
    return f"{sid[:4]}…{sid[-4:]}"


def _failure_response(
    *,
    call_sid: str,
    language: Optional[str],
    conversation_id: Optional[str],
    message: str,
    failure: IvrChatFailure,
) -> IvrChatOutcome:
    return IvrChatOutcome(
        response=IvrChatResponse(
            call_sid=call_sid,
            language=language or "",
            conversation_id=conversation_id or "",
            response_text=message,
            evidence_status="UNSUPPORTED",
            sources=[],
            success=False,
        ),
        failure=failure,
    )


def process_ivr_chat(
    db: Session,
    call_sid: str,
    *,
    transcription: Optional[str] = None,
) -> IvrChatOutcome:
    sid = (call_sid or "").strip()
    if not sid:
        return _failure_response(
            call_sid="",
            language=None,
            conversation_id=None,
            message=CHAT_UNAVAILABLE_PROMPT,
            failure=IvrChatFailure.MISSING_CALL_SID,
        )

    store = get_session_store()
    if not store.has_language(sid):
        failure = (
            IvrChatFailure.UNKNOWN_CALL_SID
            if not store.session_exists(sid)
            else IvrChatFailure.NO_LANGUAGE
        )
        return _failure_response(
            call_sid=sid,
            language=None,
            conversation_id=store.get_conversation_id(sid),
            message=CHAT_UNAVAILABLE_PROMPT,
            failure=failure,
        )

    ivr_lang = store.get_language(sid) or ""
    chat_language = resolve_chat_language(sid)
    if not chat_language:
        return _failure_response(
            call_sid=sid,
            language=ivr_lang,
            conversation_id=store.get_conversation_id(sid),
            message=CHAT_UNAVAILABLE_PROMPT,
            failure=IvrChatFailure.NO_LANGUAGE,
        )

    text = transcription if transcription is not None else store.get_transcription(sid)
    if text is None:
        return _failure_response(
            call_sid=sid,
            language=ivr_lang,
            conversation_id=store.get_conversation_id(sid),
            message=CHAT_MISSING_TRANSCRIPTION_PROMPT,
            failure=IvrChatFailure.MISSING_TRANSCRIPTION,
        )
    if not isinstance(text, str):
        return _failure_response(
            call_sid=sid,
            language=ivr_lang,
            conversation_id=store.get_conversation_id(sid),
            message=CHAT_MISSING_TRANSCRIPTION_PROMPT,
            failure=IvrChatFailure.MISSING_TRANSCRIPTION,
        )
    cleaned = text.strip()
    if not cleaned:
        return _failure_response(
            call_sid=sid,
            language=ivr_lang,
            conversation_id=store.get_conversation_id(sid),
            message=CHAT_MISSING_TRANSCRIPTION_PROMPT,
            failure=IvrChatFailure.EMPTY_TRANSCRIPTION,
        )
    if len(cleaned) > MAX_IVR_TRANSCRIPTION_LENGTH:
        return _failure_response(
            call_sid=sid,
            language=ivr_lang,
            conversation_id=store.get_conversation_id(sid),
            message=CHAT_UNAVAILABLE_PROMPT,
            failure=IvrChatFailure.OVERSIZED_TRANSCRIPTION,
        )

    ok_turn, turn_reason = can_accept_question(sid)
    if not ok_turn and turn_reason == "turn_limit":
        set_state(sid, IvrCallState.ENDING)
        terminate_ivr_session(sid)
        return _failure_response(
            call_sid=sid,
            language=ivr_lang,
            conversation_id=store.get_conversation_id(sid),
            message=CHAT_UNAVAILABLE_PROMPT,
            failure=IvrChatFailure.CHAT_CLIENT_ERROR,
        )

    try:
        require_states(sid, {IvrCallState.TRANSCRIBING})
        transition(sid, IvrCallState.PROCESSING_CHAT, from_allowed={IvrCallState.TRANSCRIBING})
    except StateTransitionError:
        return _failure_response(
            call_sid=sid,
            language=ivr_lang,
            conversation_id=store.get_conversation_id(sid),
            message=CHAT_UNAVAILABLE_PROMPT,
            failure=IvrChatFailure.CHAT_CLIENT_ERROR,
        )

    started = time.perf_counter()
    try:
        citizen = get_ivr_citizen(db)
    except IvrAuthError:
        logger.warning("ivr_chat_auth_failed call_sid=%s", _mask_call_sid(sid))
        return _failure_response(
            call_sid=sid,
            language=ivr_lang,
            conversation_id=store.get_conversation_id(sid),
            message=CHAT_UNAVAILABLE_PROMPT,
            failure=IvrChatFailure.UNAUTHORIZED,
        )

    conversation_id = store.get_conversation_id(sid)
    stt_request_id = store.get_session(sid).last_stt_request_id

    try:
        chat_result = conversation_service.handle_citizen_chat(
            db,
            citizen,
            message=cleaned,
            conversation_id=conversation_id,
            language=chat_language,
            stt_language=chat_language,
            input_mode="voice",
            voice_request_id=stt_request_id,
        )
    except HTTPException as exc:
        status = exc.status_code
        failure = (
            IvrChatFailure.CHAT_CLIENT_ERROR
            if 400 <= status < 500
            else IvrChatFailure.CHAT_SERVER_ERROR
        )
        logger.warning(
            "ivr_chat_http_failed call_sid=%s status=%s err=%s",
            _mask_call_sid(sid),
            status,
            type(exc).__name__,
        )
        return _finish_chat_failure(
            sid,
            store,
            language=ivr_lang,
            conversation_id=conversation_id,
            failure=failure,
        )
    except SQLAlchemyError:
        logger.warning("ivr_chat_db_failed call_sid=%s", _mask_call_sid(sid))
        return _finish_chat_failure(
            sid,
            store,
            language=ivr_lang,
            conversation_id=conversation_id,
            failure=IvrChatFailure.CONVERSATION_FAILURE,
        )
    except Exception:
        logger.warning("ivr_chat_failed call_sid=%s err=internal", _mask_call_sid(sid))
        return _finish_chat_failure(
            sid,
            store,
            language=ivr_lang,
            conversation_id=conversation_id,
            failure=IvrChatFailure.CHAT_SERVER_ERROR,
        )

    ok_shape, shape_failure = validate_chat_service_result(chat_result)
    if not ok_shape:
        return _finish_chat_failure(
            sid,
            store,
            language=ivr_lang,
            conversation_id=conversation_id,
            failure=shape_failure,
        )

    conv_id = str(chat_result.get("conversation_id") or "")
    if conv_id:
        store.set_conversation_id(sid, conv_id)
    response_language = chat_result.get("response_language")
    if response_language:
        store.set_last_response_language(sid, str(response_language))
    answer_text = chat_result.get("answer") or ""
    if answer_text.strip():
        store.set_last_response_text(sid, answer_text.strip())

    increment_turn(sid)
    set_state(sid, IvrCallState.SYNTHESIZING)

    evidence_status = map_chat_evidence_status(chat_result)
    sources = chat_result.get("sources") or []
    if not isinstance(sources, list):
        sources = []

    latency_ms = int((time.perf_counter() - started) * 1000)
    logger.info(
        "ivr_chat_ok call_sid=%s lang=%s evidence=%s latency_ms=%s",
        _mask_call_sid(sid),
        ivr_lang,
        evidence_status,
        latency_ms,
    )

    return IvrChatOutcome(
        response=IvrChatResponse(
            call_sid=sid,
            language=ivr_lang,
            conversation_id=conv_id,
            response_text=chat_result.get("answer") or "",
            evidence_status=evidence_status,
            sources=sources,
            response_language=chat_result.get("response_language"),
            success=True,
        ),
    )


def _finish_chat_failure(
    sid: str,
    store,
    *,
    language: str,
    conversation_id: Optional[str],
    failure: IvrChatFailure,
) -> IvrChatOutcome:
    session = store.get_session(sid)
    session.chat_failure_attempts += 1
    end_turn(sid)
    if session.chat_failure_attempts > MAX_CHAT_RETRY_ATTEMPTS:
        set_state(sid, IvrCallState.ENDING)
        terminate_ivr_session(sid)
        message = CHAT_FAILURE_GOODBYE_PROMPT
    else:
        set_state(sid, IvrCallState.READY_FOR_INPUT)
        message = CHAT_FAILURE_RETRY_PROMPT
    return _failure_response(
        call_sid=sid,
        language=language,
        conversation_id=conversation_id,
        message=message,
        failure=failure,
    )
