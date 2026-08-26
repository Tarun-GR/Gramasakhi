"""Voice STT/TTS endpoints — adapters around existing chat pipeline."""

from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy.orm import Session

from app.core import security as jwt_security
from app.core.config import settings
from app.database.session import get_db
from app.models.citizen_account import CitizenAccount
from app.schemas.voice import SynthesizeRequest, TranscribeResponse
from app.services.voice.messages import voice_message
from app.services.voice.rate_limit import voice_rate_limit_ok
from app.services.voice.stt_service import get_stt_health, transcribe_audio_entry
from app.services.voice.tts_service import get_tts_health, synthesize_speech_entry

router = APIRouter()
security_scheme = HTTPBearer()


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


@router.get("/health/stt")
def health_stt():
    return get_stt_health()


@router.get("/health/tts")
def health_tts():
    return get_tts_health()


@router.post("/voice/transcribe", response_model=TranscribeResponse)
async def voice_transcribe(
    audio: UploadFile = File(...),
    language_hint: Optional[str] = Form(None),
    citizen: CitizenAccount = Depends(get_current_citizen),
):
    """
    Microphone audio → transcript. Does NOT run RAG.
    Client should preview text, then call existing POST /api/chat.
    """
    if not voice_rate_limit_ok(str(citizen.id), bucket="stt"):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=voice_message("stt_busy", "EN"),
        )
    request_id = str(uuid.uuid4())
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
                detail=voice_message("audio_too_large", "EN"),
            )
        chunks.append(chunk)
    raw = b"".join(chunks)
    result = transcribe_audio_entry(
        raw,
        content_type=audio.content_type,
        filename=audio.filename,
        request_id=request_id,
        language_hint=language_hint,
    )
    lang = result.get("detected_language") or "EN"
    if not result.get("success"):
        key = result.get("message_key") or "stt_unavailable"
        return TranscribeResponse(
            success=False,
            detected_language=lang,
            confidence=result.get("confidence"),
            request_id=request_id,
            latency_ms=result.get("latency_ms"),
            error=result.get("error"),
            message=voice_message(key, lang),
        )
    msg = None
    if result.get("low_confidence"):
        msg = voice_message("low_confidence", lang)
    return TranscribeResponse(
        success=True,
        text=result.get("text"),
        original_transcript=result.get("original_transcript"),
        normalized_transcript=result.get("normalized_transcript"),
        detected_language=result.get("detected_language"),
        confidence=result.get("confidence"),
        low_confidence=bool(result.get("low_confidence")),
        request_id=request_id,
        latency_ms=result.get("latency_ms"),
        stt_model=result.get("stt_model"),
        message=msg,
    )


@router.post("/voice/synthesize")
def voice_synthesize(
    body: SynthesizeRequest,
    citizen: CitizenAccount = Depends(get_current_citizen),
):
    """Grounded text → audio. Never generates factual content."""
    if not voice_rate_limit_ok(str(citizen.id), bucket="tts"):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=voice_message("tts_busy", body.response_language),
        )
    result = synthesize_speech_entry(
        body.text,
        language=body.response_language,
        request_id=body.request_id,
    )
    if not result.get("success"):
        key = result.get("message_key") or "tts_unavailable"
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=voice_message(key, body.response_language),
        )
    headers = {
        "X-Request-Id": result.get("request_id") or "",
        "X-Response-Language": result.get("language") or body.response_language,
        "X-TTS-Voice": result.get("voice") or "",
        "X-TTS-Cached": "1" if result.get("cached") else "0",
    }
    return Response(
        content=result["audio"],
        media_type=result.get("mime_type") or "audio/mpeg",
        headers=headers,
    )
