"""IVR-A4 TTS adapter — A3 response text → existing TTS → Exotel playback URL."""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional

from app.core.config import settings
from app.schemas.ivr import IvrExotelPlayback, IvrTtsResponse
from app.services.ivr.audio_token_store import get_audio_token_store
from app.services.ivr.constants import (
    IVR_SUPPORTED_AUDIO_MIME,
    IVR_TO_TTS_LANGUAGE,
    MAX_IVR_TTS_TEXT_LENGTH,
    MAX_TTS_RETRY_ATTEMPTS,
    TTS_FAILURE_GOODBYE_PROMPT,
    TTS_FAILURE_RETRY_PROMPT,
    TTS_MISSING_RESPONSE_PROMPT,
    TTS_RESPONSE_TOO_LONG_PROMPT,
    TTS_UNAVAILABLE_PROMPT,
)
from app.services.ivr.call_state import (
    IvrCallState,
    StateTransitionError,
    end_turn,
    require_states,
    set_state,
)
from app.services.ivr.language_session import get_session_store
from app.services.ivr.public_url import build_ivr_audio_url
from app.services.ivr.session_cleanup import terminate_ivr_session
from app.services.voice.tts_service import synthesize_speech_entry

logger = logging.getLogger("gramsakhi.ivr.tts")


class IvrTtsFailure(str, Enum):
    MISSING_CALL_SID = "missing_call_sid"
    UNKNOWN_CALL_SID = "unknown_call_sid"
    NO_LANGUAGE = "no_language"
    MISSING_RESPONSE = "missing_response"
    EMPTY_RESPONSE = "empty_response"
    RESPONSE_TOO_LONG = "response_too_long"
    TTS_TIMEOUT = "tts_timeout"
    TTS_CLIENT_ERROR = "tts_client_error"
    TTS_SERVER_ERROR = "tts_server_error"
    MALFORMED_TTS_RESPONSE = "malformed_tts_response"
    UNSUPPORTED_AUDIO_FORMAT = "unsupported_audio_format"
    AUDIO_TOO_LARGE = "audio_too_large"
    EMPTY_AUDIO = "empty_audio"
    STORAGE_FAILURE = "storage_failure"
    PUBLIC_URL_FAILURE = "public_url_failure"


@dataclass
class IvrTtsOutcome:
    response: IvrTtsResponse
    failure: Optional[IvrTtsFailure] = None


def resolve_tts_language(call_sid: str) -> Optional[str]:
    store = get_session_store()
    resp_lang = store.get_last_response_language(call_sid)
    if resp_lang:
        code = (resp_lang or "").strip().upper()
        if code in {"KN", "HI", "EN"}:
            return code
    ivr_lang = store.get_language(call_sid)
    if not ivr_lang:
        return None
    return IVR_TO_TTS_LANGUAGE.get(ivr_lang)


def validate_tts_service_result(result: Any) -> tuple[bool, Optional[IvrTtsFailure]]:
    if not isinstance(result, dict) or not result.get("success"):
        return False, IvrTtsFailure.MALFORMED_TTS_RESPONSE
    audio = result.get("audio")
    if not isinstance(audio, (bytes, bytearray)) or len(audio) == 0:
        return False, IvrTtsFailure.EMPTY_AUDIO
    mime = (result.get("mime_type") or "").lower()
    if mime and mime not in IVR_SUPPORTED_AUDIO_MIME:
        return False, IvrTtsFailure.UNSUPPORTED_AUDIO_FORMAT
    max_bytes = int(getattr(settings, "IVR_AUDIO_MAX_BYTES", 10 * 1024 * 1024))
    if len(audio) > max_bytes:
        return False, IvrTtsFailure.AUDIO_TOO_LARGE
    return True, None


def _mask_call_sid(call_sid: str) -> str:
    sid = (call_sid or "").strip()
    if len(sid) <= 8:
        return "***"
    return f"{sid[:4]}…{sid[-4:]}"


def _failure(
    *,
    call_sid: str,
    language: Optional[str],
    failure: IvrTtsFailure,
) -> IvrTtsOutcome:
    return IvrTtsOutcome(
        response=IvrTtsResponse(
            call_sid=call_sid,
            language=language or "",
            success=False,
            message=TTS_UNAVAILABLE_PROMPT,
        ),
        failure=failure,
    )


def process_ivr_tts(call_sid: str) -> IvrTtsOutcome:
    sid = (call_sid or "").strip()
    if not sid:
        return _failure(call_sid="", language=None, failure=IvrTtsFailure.MISSING_CALL_SID)

    store = get_session_store()
    if not store.has_language(sid):
        failure = (
            IvrTtsFailure.UNKNOWN_CALL_SID
            if not store.session_exists(sid)
            else IvrTtsFailure.NO_LANGUAGE
        )
        return _failure(call_sid=sid, language=store.get_language(sid), failure=failure)

    ivr_lang = store.get_language(sid) or ""
    tts_language = resolve_tts_language(sid)
    if not tts_language:
        return _failure(call_sid=sid, language=ivr_lang, failure=IvrTtsFailure.NO_LANGUAGE)

    response_text = store.get_last_response_text(sid)
    if response_text is None:
        return IvrTtsOutcome(
            response=IvrTtsResponse(
                call_sid=sid,
                language=ivr_lang,
                success=False,
                message=TTS_MISSING_RESPONSE_PROMPT,
            ),
            failure=IvrTtsFailure.MISSING_RESPONSE,
        )
    text = response_text.strip()
    if not text:
        return IvrTtsOutcome(
            response=IvrTtsResponse(
                call_sid=sid,
                language=ivr_lang,
                success=False,
                message=TTS_MISSING_RESPONSE_PROMPT,
            ),
            failure=IvrTtsFailure.EMPTY_RESPONSE,
        )
    if len(text) > MAX_IVR_TTS_TEXT_LENGTH:
        end_turn(sid)
        set_state(sid, IvrCallState.READY_FOR_INPUT)
        return IvrTtsOutcome(
            response=IvrTtsResponse(
                call_sid=sid,
                language=ivr_lang,
                success=False,
                message=TTS_RESPONSE_TOO_LONG_PROMPT,
            ),
            failure=IvrTtsFailure.RESPONSE_TOO_LONG,
        )

    try:
        require_states(sid, {IvrCallState.SYNTHESIZING})
    except StateTransitionError:
        return _failure(call_sid=sid, language=ivr_lang, failure=IvrTtsFailure.TTS_CLIENT_ERROR)

    started = time.perf_counter()
    request_id = str(uuid.uuid4())
    token: Optional[str] = None
    entry_path: Optional[str] = None

    try:
        tts_result = synthesize_speech_entry(
            text,
            language=tts_language,
            request_id=request_id,
        )
        if not tts_result.get("success"):
            err = (tts_result.get("error") or "").lower()
            if err == "tts_busy":
                failure = IvrTtsFailure.TTS_TIMEOUT
            elif err in {"empty_text", "tts_empty"}:
                failure = IvrTtsFailure.EMPTY_AUDIO
            else:
                failure = IvrTtsFailure.TTS_SERVER_ERROR
            return _finish_tts_failure(sid, store, language=ivr_lang, failure=failure)

        ok, shape_failure = validate_tts_service_result(tts_result)
        if not ok:
            return _finish_tts_failure(sid, store, language=ivr_lang, failure=shape_failure)

        audio_bytes = bytes(tts_result["audio"])
        mime_type = tts_result.get("mime_type") or "audio/mpeg"
        audio_store = get_audio_token_store()
        prior = getattr(store.get_session(sid), "active_audio_token", None)
        if prior:
            audio_store.delete(prior)
        audio_store.revoke_for_call_sid(sid)
        token = audio_store.issue(call_sid=sid, data=audio_bytes, mime_type=mime_type)
        session = store.get_session(sid)
        session.active_audio_token = token
        entry = audio_store.get(token)
        entry_path = entry.path if entry else None

        try:
            audio_url = build_ivr_audio_url(token)
        except ValueError:
            audio_store.delete(token)
            session.active_audio_token = None
            return _finish_tts_failure(
                sid,
                store,
                language=ivr_lang,
                failure=IvrTtsFailure.PUBLIC_URL_FAILURE,
            )

        playback = IvrExotelPlayback(
            playback_to="both",
            type="audio_url",
            value=audio_url,
        )
        latency_ms = int((time.perf_counter() - started) * 1000)
        set_state(sid, IvrCallState.PLAYING_RESPONSE)
        end_turn(sid)
        session.tts_failure_attempts = 0
        logger.info(
            "ivr_tts_ok call_sid=%s lang=%s bytes=%s latency_ms=%s",
            _mask_call_sid(sid),
            ivr_lang,
            len(audio_bytes),
            latency_ms,
        )
        return IvrTtsOutcome(
            response=IvrTtsResponse(
                call_sid=sid,
                language=ivr_lang,
                success=True,
                audio_url=audio_url,
                start_call_playback=playback,
                mime_type=mime_type,
            ),
        )
    except Exception:
        if token:
            get_audio_token_store().delete(token)
            store.get_session(sid).active_audio_token = None
        logger.warning("ivr_tts_failed call_sid=%s err=internal", _mask_call_sid(sid))
        return _finish_tts_failure(sid, store, language=ivr_lang, failure=IvrTtsFailure.STORAGE_FAILURE)
    finally:
        _ = entry_path


def _finish_tts_failure(
    sid: str,
    store,
    *,
    language: str,
    failure: IvrTtsFailure,
) -> IvrTtsOutcome:
    session = store.get_session(sid)
    session.tts_failure_attempts += 1
    end_turn(sid)
    if session.tts_failure_attempts > MAX_TTS_RETRY_ATTEMPTS:
        set_state(sid, IvrCallState.ENDING)
        terminate_ivr_session(sid)
        message = TTS_FAILURE_GOODBYE_PROMPT
    else:
        set_state(sid, IvrCallState.SYNTHESIZING)
        message = TTS_FAILURE_RETRY_PROMPT
    return IvrTtsOutcome(
        response=IvrTtsResponse(
            call_sid=sid,
            language=language,
            success=False,
            message=message,
        ),
        failure=failure,
    )
