"""IVR-A2 STT adapter — Exotel audio → existing GramSakhi STT service."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional

from app.schemas.ivr import GatherPromptText, IvrTranscribeResponse
from app.services.ivr.constants import (
    IVR_TO_STT_LANGUAGE,
    MAX_SILENCE_ATTEMPTS,
    MAX_STT_RETRY_ATTEMPTS,
    SILENCE_FIRST_PROMPT,
    SILENCE_GOODBYE_PROMPT,
    STT_EMPTY_PROMPT,
    STT_GOODBYE_PROMPT,
    STT_LOW_CONFIDENCE_PROMPT,
    STT_SUCCESS_PROMPT,
    STT_UNAVAILABLE_PROMPT,
)
from app.services.ivr.call_state import (
    IvrCallState,
    StateTransitionError,
    assert_turn_available,
    begin_turn,
    end_turn,
    require_states,
    set_state,
    transition,
)
from app.services.ivr.exotel_recording import (
    cleanup_recording_temp,
    fetch_exotel_recording_to_temp,
)
from app.services.ivr.language_session import get_session_store
from app.services.ivr.session_cleanup import terminate_ivr_session
from app.services.voice.stt_service import transcribe_audio_entry

logger = logging.getLogger("gramsakhi.ivr.stt")


class IvrSttFailure(str, Enum):
    MISSING_CALL_SID = "missing_call_sid"
    UNKNOWN_CALL_SID = "unknown_call_sid"
    NO_LANGUAGE = "no_language"
    MISSING_AUDIO = "missing_audio"
    INVALID_AUDIO = "invalid_audio"
    UNSUPPORTED_FORMAT = "unsupported_format"
    AUDIO_TOO_LARGE = "audio_too_large"
    AUDIO_TOO_LONG = "audio_too_long"
    RECORDING_UNAVAILABLE = "recording_unavailable"
    RECORDING_TIMEOUT = "recording_timeout"
    STT_TIMEOUT = "stt_timeout"
    STT_CLIENT_ERROR = "stt_client_error"
    STT_SERVER_ERROR = "stt_server_error"
    MALFORMED_STT_RESPONSE = "malformed_stt_response"
    EMPTY_TRANSCRIPTION = "empty_transcription"
    LOW_CONFIDENCE = "low_confidence"


@dataclass
class IvrSttOutcome:
    response: IvrTranscribeResponse
    failure: Optional[IvrSttFailure] = None
    transcription: Optional[str] = None
    low_confidence: bool = False
    language_hint: Optional[str] = None
    request_id: Optional[str] = None


def resolve_stt_language_hint(call_sid: str) -> Optional[str]:
    lang = get_session_store().get_language(call_sid)
    if not lang:
        return None
    return IVR_TO_STT_LANGUAGE.get(lang)


def _prompt_response(text: str, *, success: bool, low_confidence: bool = False) -> IvrTranscribeResponse:
    return IvrTranscribeResponse(
        gather_prompt=GatherPromptText(text=text),
        success=success,
        low_confidence=low_confidence,
    )


def _map_stt_service_error(error: Optional[str]) -> IvrSttFailure:
    mapping = {
        "empty_audio": IvrSttFailure.EMPTY_TRANSCRIPTION,
        "empty_transcript": IvrSttFailure.EMPTY_TRANSCRIPTION,
        "unsupported_audio_format": IvrSttFailure.UNSUPPORTED_FORMAT,
        "audio_too_large": IvrSttFailure.AUDIO_TOO_LARGE,
        "audio_too_long": IvrSttFailure.AUDIO_TOO_LONG,
        "stt_busy": IvrSttFailure.STT_TIMEOUT,
        "stt_failed": IvrSttFailure.STT_SERVER_ERROR,
        "stt_disabled": IvrSttFailure.STT_SERVER_ERROR,
        "unreliable_transcript": IvrSttFailure.LOW_CONFIDENCE,
    }
    return mapping.get(error or "", IvrSttFailure.STT_SERVER_ERROR)


def validate_stt_service_result(result: Any) -> tuple[bool, Optional[IvrSttFailure]]:
    if not isinstance(result, dict):
        return False, IvrSttFailure.MALFORMED_STT_RESPONSE
    if "success" not in result:
        return False, IvrSttFailure.MALFORMED_STT_RESPONSE
    if result.get("success") is True:
        text = result.get("text")
        if not isinstance(text, str) or not text.strip():
            return False, IvrSttFailure.EMPTY_TRANSCRIPTION
    return True, None


def transcribe_ivr_audio(
    call_sid: str,
    *,
    recording_url: Optional[str] = None,
    audio_bytes: Optional[bytes] = None,
    content_type: Optional[str] = None,
    filename: Optional[str] = None,
) -> IvrSttOutcome:
    """
    Obtain temporary audio, derive language from CallSid session, invoke existing STT service.
    """
    sid = (call_sid or "").strip()
    if not sid:
        return IvrSttOutcome(
            response=_prompt_response(STT_UNAVAILABLE_PROMPT, success=False),
            failure=IvrSttFailure.MISSING_CALL_SID,
        )

    store = get_session_store()
    if not store.has_language(sid):
        failure = (
            IvrSttFailure.UNKNOWN_CALL_SID
            if not store.session_exists(sid)
            else IvrSttFailure.NO_LANGUAGE
        )
        return IvrSttOutcome(
            response=_prompt_response(STT_UNAVAILABLE_PROMPT, success=False),
            failure=failure,
        )

    language_hint = resolve_stt_language_hint(sid)
    if not language_hint:
        return IvrSttOutcome(
            response=_prompt_response(STT_UNAVAILABLE_PROMPT, success=False),
            failure=IvrSttFailure.NO_LANGUAGE,
        )

    try:
        require_states(sid, {IvrCallState.READY_FOR_INPUT})
    except StateTransitionError:
        return IvrSttOutcome(
            response=_prompt_response(STT_UNAVAILABLE_PROMPT, success=False),
            failure=IvrSttFailure.STT_CLIENT_ERROR,
            language_hint=language_hint,
        )

    temp_path: Optional[str] = None
    data: Optional[bytes] = audio_bytes
    audio_content_type = content_type

    if data is None and (not recording_url or not recording_url.strip()):
        session = store.get_session(sid)
        session.silence_attempts += 1
        if session.silence_attempts >= MAX_SILENCE_ATTEMPTS:
            set_state(sid, IvrCallState.ENDING)
            terminate_ivr_session(sid)
            return IvrSttOutcome(
                response=_prompt_response(SILENCE_GOODBYE_PROMPT, success=False),
                failure=IvrSttFailure.MISSING_AUDIO,
                language_hint=language_hint,
            )
        return IvrSttOutcome(
            response=_prompt_response(SILENCE_FIRST_PROMPT, success=False),
            failure=IvrSttFailure.MISSING_AUDIO,
            language_hint=language_hint,
        )

    try:
        assert_turn_available(sid)
        begin_turn(sid)
        transition(sid, IvrCallState.TRANSCRIBING, from_allowed={IvrCallState.READY_FOR_INPUT})
    except StateTransitionError:
        return IvrSttOutcome(
            response=_prompt_response(STT_UNAVAILABLE_PROMPT, success=False),
            failure=IvrSttFailure.STT_CLIENT_ERROR,
            language_hint=language_hint,
        )

    try:
        if data is None:
            fetch = fetch_exotel_recording_to_temp(recording_url.strip())
            temp_path = fetch.temp_path
            if not fetch.ok or not fetch.data:
                err = fetch.error or "recording_unavailable"
                failure_map = {
                    "missing_recording_url": IvrSttFailure.MISSING_AUDIO,
                    "blocked_scheme": IvrSttFailure.INVALID_AUDIO,
                    "invalid_scheme": IvrSttFailure.INVALID_AUDIO,
                    "blocked_host": IvrSttFailure.INVALID_AUDIO,
                    "untrusted_host": IvrSttFailure.INVALID_AUDIO,
                    "invalid_host": IvrSttFailure.INVALID_AUDIO,
                    "audio_too_large": IvrSttFailure.AUDIO_TOO_LARGE,
                    "audio_too_long": IvrSttFailure.AUDIO_TOO_LONG,
                    "unsupported_audio_format": IvrSttFailure.UNSUPPORTED_FORMAT,
                    "recording_fetch_failed": IvrSttFailure.RECORDING_UNAVAILABLE,
                }
                failure = failure_map.get(err, IvrSttFailure.RECORDING_UNAVAILABLE)
                return _finish_stt_failure(
                    sid,
                    store,
                    failure=failure,
                    prompt=_retry_or_goodbye(store.increment_stt_attempts(sid), STT_EMPTY_PROMPT),
                    language_hint=language_hint,
                )
            data = fetch.data
            audio_content_type = fetch.content_type

        request_id = str(uuid.uuid4())
        result = transcribe_audio_entry(
            data,
            content_type=audio_content_type,
            filename=filename,
            request_id=request_id,
            language_hint=language_hint,
        )

        ok_shape, shape_failure = validate_stt_service_result(result)
        if not ok_shape:
            return _finish_stt_failure(
                sid,
                store,
                failure=shape_failure,
                prompt=_retry_or_goodbye(store.increment_stt_attempts(sid), STT_UNAVAILABLE_PROMPT),
                language_hint=language_hint,
                request_id=result.get("request_id") if isinstance(result, dict) else request_id,
            )

        if not result.get("success"):
            failure = _map_stt_service_error(result.get("error"))
            return _finish_stt_failure(
                sid,
                store,
                failure=failure,
                prompt=_retry_or_goodbye(
                    store.increment_stt_attempts(sid),
                    STT_LOW_CONFIDENCE_PROMPT if failure == IvrSttFailure.LOW_CONFIDENCE else STT_EMPTY_PROMPT,
                ),
                language_hint=language_hint,
                low_confidence=failure == IvrSttFailure.LOW_CONFIDENCE,
                request_id=result.get("request_id"),
            )

        transcript = (result.get("text") or "").strip()
        low_confidence = bool(result.get("low_confidence"))
        if not transcript:
            return _finish_stt_failure(
                sid,
                store,
                failure=IvrSttFailure.EMPTY_TRANSCRIPTION,
                prompt=_retry_or_goodbye(store.increment_stt_attempts(sid), STT_EMPTY_PROMPT),
                language_hint=language_hint,
                request_id=result.get("request_id"),
            )

        if low_confidence:
            return _finish_stt_failure(
                sid,
                store,
                failure=IvrSttFailure.LOW_CONFIDENCE,
                prompt=_retry_or_goodbye(store.increment_stt_attempts(sid), STT_LOW_CONFIDENCE_PROMPT),
                language_hint=language_hint,
                low_confidence=True,
                request_id=result.get("request_id"),
            )

        store.set_transcription(
            sid,
            transcription=transcript,
            low_confidence=False,
            request_id=result.get("request_id"),
        )
        session = store.get_session(sid)
        session.silence_attempts = 0
        logger.info("ivr_stt_ok call_sid=%s request_id=%s", sid[:4] + "…", result.get("request_id"))
        return IvrSttOutcome(
            response=_prompt_response(STT_SUCCESS_PROMPT, success=True),
            transcription=transcript,
            low_confidence=False,
            language_hint=language_hint,
            request_id=result.get("request_id"),
        )
    finally:
        cleanup_recording_temp(temp_path)


def _finish_stt_failure(
    sid: str,
    store,
    *,
    failure: IvrSttFailure,
    prompt: str,
    language_hint: Optional[str],
    low_confidence: bool = False,
    request_id: Optional[str] = None,
) -> IvrSttOutcome:
    store.set_transcription(sid, transcription=None, low_confidence=low_confidence, request_id=request_id)
    end_turn(sid)
    if prompt == STT_GOODBYE_PROMPT:
        set_state(sid, IvrCallState.ENDING)
        terminate_ivr_session(sid)
    else:
        set_state(sid, IvrCallState.READY_FOR_INPUT)
    return IvrSttOutcome(
        response=_prompt_response(prompt, success=False, low_confidence=low_confidence),
        failure=failure,
        language_hint=language_hint,
        request_id=request_id,
    )


def _retry_or_goodbye(attempts: int, retry_prompt: str) -> str:
    if attempts > MAX_STT_RETRY_ATTEMPTS:
        return STT_GOODBYE_PROMPT
    return retry_prompt
