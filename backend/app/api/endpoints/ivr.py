"""IVR telephony endpoints — Exotel Gather adapter (A1: inbound language selection)."""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.schemas.ivr import (
    IvrChatRequest,
    IvrChatResponse,
    IvrContinueRequest,
    IvrContinueResponse,
    IvrGatherResponse,
    IvrTranscribeResponse,
    IvrTtsRequest,
    IvrTtsResponse,
)
from app.services.ivr.audio_token_store import get_audio_token_store, validate_audio_token
from app.services.ivr.call_sid_validation import mask_call_sid
from app.services.ivr.chat_adapter import IvrChatFailure, process_ivr_chat
from app.services.ivr.continue_flow import build_continue_response
from app.services.ivr.ivr_guard import (
    guard_audio_fetch,
    parse_and_guard_call_sid,
    require_ivr_webhook_access,
)
from app.services.ivr.language_flow import build_language_gather_response, mask_caller_phone
from app.services.ivr.language_session import get_session_store
from app.services.ivr.stt_adapter import transcribe_ivr_audio
from app.services.ivr.tts_adapter import IvrTtsFailure, process_ivr_tts

router = APIRouter()
_logger = logging.getLogger("gramsakhi.ivr")


@router.get(
    "/language",
    response_model=IvrGatherResponse,
    summary="Exotel IVR language selection (Gather)",
    response_description="Exotel Gather JSON — menu, retry, confirmation, or goodbye prompt.",
)
def ivr_language_selection(
    request: Request,
    CallSid: Optional[str] = Query(
        None,
        description="Exotel call identifier. Required — used as the IVR session key.",
    ),
    digits: Optional[str] = Query(
        None,
        description='DTMF input from Gather (1=Kannada, 2=Hindi, 3=English). May be quoted by Exotel.',
    ),
    CallFrom: Optional[str] = Query(None, description="Caller phone number (never returned in response)."),
    CallTo: Optional[str] = Query(None, description="Called Exotel number."),
    From: Optional[str] = Query(None, description="Caller alias field from Exotel."),
    To: Optional[str] = Query(None, description="Called number alias from Exotel."),
    ivr_secret: Optional[str] = Query(None, description="Optional operator-configured webhook secret."),
) -> IvrGatherResponse:
    """
    **IVR-A1 — inbound call language menu**

    Exotel Flow should configure a Gather applet with this URL as the *Application URL*.

    | DTMF | Language |
    |------|----------|
    | 1    | Kannada (kn) |
    | 2    | Hindi (hi) |
    | 3    | English (en) |

    **Flow behavior**

    - No / empty `digits` → language menu (bounded timeout retries).
    - Valid digit → language stored for `CallSid`, confirmation prompt, then end (Flow → Hangup).
    - Invalid digit → retry prompt (bounded); after max retries → goodbye.

    **Errors**

    - `400` — missing or blank `CallSid`.

    **Session storage (development)**

    In-memory map keyed by `CallSid`. Restart clears state; production multi-instance
    deployments should use shared storage (e.g. Redis).
    """
    require_ivr_webhook_access(request, ivr_secret_query=ivr_secret)
    call_sid = parse_and_guard_call_sid(CallSid, request=request, require_active_session=False)
    caller = CallFrom or From

    try:
        return build_language_gather_response(
            call_sid=call_sid,
            digits=digits,
            caller_phone=caller,
        )
    except ValueError as exc:
        _logger.warning("ivr_language_invalid call_sid=%s err=%s", mask_call_sid(call_sid), type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid IVR request.",
        ) from exc


@router.get(
    "/transcribe",
    response_model=IvrTranscribeResponse,
    summary="Exotel IVR speech-to-text (Voicemail/RecordingUrl callback)",
    response_description="Exotel JSON prompt — success, retry, or goodbye (no transcript in response).",
)
def ivr_transcribe_from_recording(
    request: Request,
    CallSid: Optional[str] = Query(
        None,
        description="Exotel call identifier. Required — language is read from the A1 session.",
    ),
    RecordingUrl: Optional[str] = Query(
        None,
        description="Temporary Exotel recording URL from the preceding Voicemail/Record applet.",
    ),
    CallFrom: Optional[str] = Query(None, description="Caller phone number (logged masked only)."),
    From: Optional[str] = Query(None, description="Caller alias field from Exotel."),
    language_hint: Optional[str] = Query(
        None,
        description="Ignored — language is derived from CallSid session (A1).",
    ),
    lang: Optional[str] = Query(None, description="Ignored — language is derived from CallSid session (A1)."),
    language: Optional[str] = Query(None, description="Ignored — language is derived from CallSid session (A1)."),
    ivr_secret: Optional[str] = Query(None, description="Optional operator-configured webhook secret."),
) -> IvrTranscribeResponse:
    """
    **IVR-A2 — caller speech → existing GramSakhi STT**

    Exotel Flow (after A1 language selection):

    1. Prompt caller to speak (Say applet).
    2. **Voicemail** applet captures speech → provides `RecordingUrl` on the next GET.
    3. Point the next applet Application URL here with `CallSid` and `RecordingUrl`.

    Language hint (`KN` / `HI` / `EN`) is derived from the A1 session — query overrides are ignored.

    Transcription is stored server-side on the CallSid session. The HTTP response contains only
    a speech-friendly prompt for Exotel playback (no transcript body).

    **Errors (mapped to retry/goodbye prompts, HTTP 200)**

    Missing `CallSid`, unknown session, missing language, missing/invalid audio, STT failures.
    """
    _ = (language_hint, lang, language)
    require_ivr_webhook_access(request, ivr_secret_query=ivr_secret)
    call_sid = parse_and_guard_call_sid(
        CallSid, request=request, require_active_session=True, allow_create=False
    )
    caller = CallFrom or From
    store = get_session_store()
    if not store.has_language(call_sid):
        if not store.session_exists(call_sid):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Unknown CallSid — complete language selection first.",
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No language selected for this CallSid.",
        )

    _logger.info(
        "ivr_transcribe call_sid=%s caller=%s has_recording=%s",
        mask_call_sid(call_sid),
        mask_caller_phone(caller),
        bool(RecordingUrl and RecordingUrl.strip()),
    )

    outcome = transcribe_ivr_audio(call_sid, recording_url=RecordingUrl)
    return outcome.response


@router.post(
    "/transcribe",
    response_model=IvrTranscribeResponse,
    summary="IVR STT with direct audio upload (dev/test; same STT contract as /api/chat/voice/transcribe)",
)
async def ivr_transcribe_upload(
    request: Request,
    CallSid: str = Query(..., min_length=1, description="Exotel call identifier."),
    audio: UploadFile = File(..., description="Audio file — same multipart field name as voice/transcribe."),
    language_hint: Optional[str] = Query(None, description="Ignored — derived from CallSid session."),
    ivr_secret: Optional[str] = Query(None, description="Optional operator-configured webhook secret."),
) -> IvrTranscribeResponse:
    """
    Development/test path: upload audio directly without Exotel `RecordingUrl`.

    Uses the same `audio` multipart field and internal STT service as `POST /api/chat/voice/transcribe`,
    but language_hint is always taken from the A1 IVR session, not from the request.

    Not part of the Exotel production contract — disabled in production unless
    `IVR_DIRECT_UPLOAD_IN_PRODUCTION=true`.
    """
    _ = language_hint
    from app.core.config import settings

    if settings.APP_ENV.strip().lower() == "production" and not settings.IVR_DIRECT_UPLOAD_IN_PRODUCTION:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")
    require_ivr_webhook_access(request, ivr_secret_query=ivr_secret)
    call_sid = parse_and_guard_call_sid(
        CallSid, request=request, require_active_session=True, allow_create=False
    )
    store = get_session_store()
    if not store.has_language(call_sid):
        if not store.session_exists(call_sid):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Unknown CallSid — complete language selection first.",
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No language selected for this CallSid.",
        )

    max_bytes = int(settings.STT_MAX_AUDIO_SIZE_MB * 1024 * 1024)
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await audio.read(65536)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="Audio too large for IVR STT.",
            )
        chunks.append(chunk)
    raw = b"".join(chunks)

    outcome = transcribe_ivr_audio(
        call_sid,
        audio_bytes=raw,
        content_type=audio.content_type,
        filename=audio.filename,
    )
    return outcome.response


@router.post(
    "/chat",
    response_model=IvrChatResponse,
    summary="IVR chat — transcription into existing GramSakhi RAG pipeline",
)
def ivr_chat(
    body: IvrChatRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> IvrChatResponse:
    """
    **IVR-A3 — STT transcription → existing `/api/chat` service layer**

    - `CallSid` required; must have completed A1 language selection.
    - `transcription` from A2 STT (or omitted to use session-stored transcript).
    - `language`, `conversation_id`, `account_id` in body are **ignored** if sent.
    - Language mapped: kn→KN, hi→HI, en→EN (passed to `handle_citizen_chat`).
    - One CallSid → one server-managed conversation (reused on repeat calls).
    - Uses dedicated IVR bridge CitizenAccount (`IVR_CITIZEN_ACCOUNT_ID` / `IVR_SYSTEM_ACCOUNT_PHONE`).

    Returns grounded `response_text`, `evidence_status`, and `sources` from the existing pipeline.
    No JWT, no transcript logging, no TTS/audio output (A4+).
    """
    _ = (body.language, body.lang, body.conversation_id, body.account_id, body.citizen_id)

    require_ivr_webhook_access(
        request,
        ivr_secret_query=request.headers.get("x-gramsakhi-ivr-secret"),
    )
    call_sid = parse_and_guard_call_sid(
        body.CallSid, request=request, require_active_session=True, allow_create=False
    )
    store = get_session_store()
    if not store.has_language(call_sid):
        if not store.session_exists(call_sid):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Unknown CallSid — complete language selection first.",
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No language selected for this CallSid.",
        )

    if body.transcription is not None and len(body.transcription) > 8000:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Transcription exceeds maximum length.",
        )

    outcome = process_ivr_chat(db, call_sid, transcription=body.transcription)

    if outcome.failure in {
        IvrChatFailure.MISSING_TRANSCRIPTION,
        IvrChatFailure.EMPTY_TRANSCRIPTION,
    }:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Transcription is required for IVR chat.",
        )
    if outcome.failure == IvrChatFailure.OVERSIZED_TRANSCRIPTION:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Transcription exceeds maximum length.",
        )
    if outcome.failure == IvrChatFailure.CHAT_CLIENT_ERROR:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="IVR is not ready for chat on this CallSid.",
        )
    if outcome.failure in {
        IvrChatFailure.UNAUTHORIZED,
        IvrChatFailure.CONVERSATION_FAILURE,
        IvrChatFailure.CHAT_TIMEOUT,
        IvrChatFailure.CHAT_SERVER_ERROR,
        IvrChatFailure.MALFORMED_CHAT_RESPONSE,
    }:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="GramSakhi could not complete your IVR request. Please try again.",
        )

    return outcome.response


@router.post(
    "/tts",
    response_model=IvrTtsResponse,
    summary="IVR TTS — A3 response text to Exotel playback URL",
)
def ivr_tts(
    body: IvrTtsRequest,
    request: Request,
) -> IvrTtsResponse:
    """
    **IVR-A4 — existing TTS → temporary audio URL for Exotel**

    - Uses A3 `last_response_text` from the CallSid session (caller cannot override).
    - Language from session: kn→KN, hi→HI, en→EN.
    - Returns `audio_url` and `start_call_playback` for Exotel Connect dynamic JSON.
    """
    _ = (body.response_text, body.language, body.lang)

    require_ivr_webhook_access(
        request,
        ivr_secret_query=request.headers.get("x-gramsakhi-ivr-secret"),
    )
    call_sid = parse_and_guard_call_sid(
        body.CallSid, request=request, require_active_session=True, allow_create=False
    )
    store = get_session_store()
    if not store.has_language(call_sid):
        if not store.session_exists(call_sid):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Unknown CallSid — complete language selection first.",
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No language selected for this CallSid.",
        )

    outcome = process_ivr_tts(call_sid)

    if outcome.failure in {
        IvrTtsFailure.MISSING_RESPONSE,
        IvrTtsFailure.EMPTY_RESPONSE,
    }:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No A3 response available for TTS.",
        )
    if outcome.failure == IvrTtsFailure.RESPONSE_TOO_LONG:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Response text exceeds TTS limit for IVR playback.",
        )
    if outcome.failure == IvrTtsFailure.TTS_CLIENT_ERROR:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="IVR is not ready for TTS on this CallSid.",
        )
    if outcome.failure is not None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Voice playback is unavailable right now.",
        )

    return outcome.response


@router.get(
    "/continue",
    response_model=IvrContinueResponse,
    summary="IVR-A5 continue/end menu (Exotel Gather after playback)",
)
def ivr_continue_get(
    request: Request,
    CallSid: Optional[str] = Query(None, description="Exotel call identifier."),
    digits: Optional[str] = Query(None, description="DTMF: 1=continue, 2=end."),
    ivr_secret: Optional[str] = Query(None, description="Optional operator-configured webhook secret."),
) -> IvrContinueResponse:
    """
    **IVR-A5 — multi-turn loop**

    After A4 playback, Exotel Flow should call this URL (Gather applet).

    - No digits → continue/end menu (or transition from PLAYING_RESPONSE → ASK_CONTINUE).
    - `1` → next question (READY_FOR_INPUT).
    - `2` → goodbye and session cleanup (ENDING).
    """
    require_ivr_webhook_access(request, ivr_secret_query=ivr_secret)
    call_sid = parse_and_guard_call_sid(
        CallSid, request=request, require_active_session=True, allow_create=False
    )
    return build_continue_response(call_sid=call_sid, digits=digits)


@router.post(
    "/continue",
    response_model=IvrContinueResponse,
    summary="IVR-A5 continue/end (JSON body for tests)",
)
def ivr_continue_post(body: IvrContinueRequest, request: Request) -> IvrContinueResponse:
    _ = (body.language, body.conversation_id)
    require_ivr_webhook_access(
        request,
        ivr_secret_query=request.headers.get("x-gramsakhi-ivr-secret"),
    )
    call_sid = parse_and_guard_call_sid(
        body.CallSid, request=request, require_active_session=True, allow_create=False
    )
    return build_continue_response(call_sid=call_sid, digits=body.digits)


def _serve_ivr_audio(token: str, *, consume: bool = True) -> Response:
    if not validate_audio_token(token) or ".." in token or "/" in token or "\\" in token:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Audio not found.")
    store = get_audio_token_store()
    entry = store.consume(token) if consume else store.get(token)
    if not entry:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Audio not found.")
    try:
        with open(entry.path, "rb") as handle:
            data = handle.read()
    finally:
        if consume:
            store.delete(token)
    if not data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Audio not found.")
    return Response(
        content=data if consume else b"",
        media_type=entry.mime_type or "audio/mpeg",
        headers={
            "Cache-Control": "no-store, max-age=0",
            "Content-Length": str(len(data)),
        },
    )


@router.get(
    "/audio/{token}",
    summary="IVR temporary audio fetch (Exotel playback, opaque token)",
    response_class=Response,
)
def ivr_audio_get(token: str, request: Request) -> Response:
    """Single-use, short-lived audio for Exotel `start_call_playback` audio_url fetch."""
    guard_audio_fetch(request)
    return _serve_ivr_audio(token)


@router.head(
    "/audio/{token}",
    summary="IVR temporary audio HEAD (Exotel compatibility)",
    response_class=Response,
)
def ivr_audio_head(token: str, request: Request) -> Response:
    guard_audio_fetch(request)
    return _serve_ivr_audio(token, consume=False)
