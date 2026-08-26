"""Speech-to-Text adapter (Phase 7).

Uses faster-whisper when installed. Never stores audio in RAG buckets.
Text chat continues if STT is unavailable.
"""

from __future__ import annotations

import logging
import os
import threading
import time
import uuid
from typing import Any, Dict, Optional

from app.core.config import settings
from app.services.language_service import (
    detect_script_language,
    normalize_language_code,
)
from app.services.voice.audio_utils import validate_audio_bytes, write_temp_audio

logger = logging.getLogger(__name__)

_MODEL = None
_MODEL_LOCK = threading.Lock()
_MODEL_ERROR: Optional[str] = None
_SEM = threading.Semaphore(max(1, int(getattr(settings, "STT_MAX_CONCURRENT", 2))))

# Whisper lang codes → GramSakhi
_WHISPER_TO_CODE = {
    "en": "EN",
    "english": "EN",
    "kn": "KN",
    "kannada": "KN",
    "hi": "HI",
    "hindi": "HI",
}


def _map_lang(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    return _WHISPER_TO_CODE.get(str(raw).strip().lower()) or normalize_language_code(raw)


def get_stt_health() -> Dict[str, Any]:
    configured = bool(getattr(settings, "STT_ENABLED", True))
    model_name = getattr(settings, "STT_MODEL", "base")
    device = getattr(settings, "STT_DEVICE", "cpu")
    info = {
        "configured": configured,
        "available": False,
        "model": model_name,
        "model_loaded": _MODEL is not None,
        "device": device,
        "supported_languages": ["EN", "KN", "HI"],
        "version": None,
        "runtime": "faster-whisper",
        "approximate_size": "base ~150MB (download on first use)",
        "detail": None,
    }
    if not configured:
        info["detail"] = "STT_ENABLED=false"
        return info
    try:
        import faster_whisper  # noqa: F401

        info["version"] = getattr(faster_whisper, "__version__", "installed")
        info["available"] = True
        if _MODEL_ERROR:
            info["detail"] = _MODEL_ERROR
            info["available"] = _MODEL is not None
        else:
            info["detail"] = "ok" if _MODEL is not None else "lazy_load"
    except Exception as e:  # noqa: BLE001
        info["detail"] = f"faster-whisper not installed: {type(e).__name__}"
        info["available"] = False
    return info


def _load_model():
    global _MODEL, _MODEL_ERROR
    if _MODEL is not None:
        return _MODEL
    with _MODEL_LOCK:
        if _MODEL is not None:
            return _MODEL
        try:
            from faster_whisper import WhisperModel

            device = (settings.STT_DEVICE or "cpu").strip().lower()
            if device.startswith("cuda"):
                device = "cuda"
            else:
                device = "cpu"
            compute = settings.STT_COMPUTE_TYPE or ("float16" if device == "cuda" else "int8")
            _MODEL = WhisperModel(
                settings.STT_MODEL or "base",
                device=device,
                compute_type=compute,
            )
            _MODEL_ERROR = None
            logger.info(
                "STT model loaded model=%s device=%s", settings.STT_MODEL, device
            )
            return _MODEL
        except Exception as e:  # noqa: BLE001
            _MODEL_ERROR = f"{type(e).__name__}: {e}"
            logger.warning("STT model load failed: %s", _MODEL_ERROR)
            raise


def resolve_transcript_language(
    transcript: str,
    stt_lang: Optional[str],
) -> str:
    """Prefer script + transliteration cues over a wrong Whisper English tag.

    Always pass the ORIGINAL transcript (not retrieval-normalized text) so
    Kannada/Hindi cue words are not erased before detection.
    """
    from app.services.language_service import detect_lexical_language

    raw = transcript or ""
    script = detect_script_language(raw)
    if script:
        return script
    lexical = detect_lexical_language(raw)
    if lexical in ("KN", "HI", "EN"):
        return lexical
    mapped = _map_lang(stt_lang)
    return mapped or "EN"


def _whisper_language_arg(language_hint: Optional[str]) -> Optional[str]:
    """Map EN/KN/HI hint to Whisper codes; None = auto-detect."""
    code = normalize_language_code(language_hint) if language_hint else None
    return {"EN": "en", "KN": "kn", "HI": "hi"}.get(code or "")


def transcribe_audio(
    data: bytes,
    *,
    content_type: Optional[str] = None,
    filename: Optional[str] = None,
    request_id: Optional[str] = None,
    language_hint: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Transcribe microphone audio to text. Temporary files are deleted.

    Returns success payload or controlled error (never raises to RAG).
    Always uses Whisper task=transcribe (never translate).
    """
    rid = request_id or str(uuid.uuid4())
    started = time.perf_counter()

    if not getattr(settings, "STT_ENABLED", True):
        return {
            "success": False,
            "error": "stt_disabled",
            "message_key": "stt_unavailable",
            "request_id": rid,
        }

    validation = validate_audio_bytes(
        data,
        max_size_mb=float(settings.STT_MAX_AUDIO_SIZE_MB),
        max_duration_seconds=float(settings.STT_MAX_DURATION_SECONDS),
        content_type=content_type,
    )
    if not validation.ok:
        return {
            "success": False,
            "error": validation.error,
            "message_key": validation.error or "stt_failed",
            "request_id": rid,
            "latency_ms": int((time.perf_counter() - started) * 1000),
        }

    suffix = {
        "wav": ".wav",
        "webm": ".webm",
        "ogg": ".ogg",
        "mp3": ".mp3",
    }.get(validation.format_hint or "", ".bin")

    # Ignore client filename for security
    _ = filename
    path = None
    acquired = _SEM.acquire(timeout=float(settings.STT_TIMEOUT_SECONDS))
    if not acquired:
        return {
            "success": False,
            "error": "stt_busy",
            "message_key": "stt_busy",
            "request_id": rid,
        }

    try:
        from app.services.multilingual_retrieval_service import normalize_transcript

        path = write_temp_audio(data, suffix)
        model = _load_model()
        whisper_lang = _whisper_language_arg(language_hint)
        segments, info = model.transcribe(
            path,
            language=whisper_lang,  # hint only; script still overrides later
            task="transcribe",  # never translate into English
            beam_size=1,
            vad_filter=True,
        )
        parts = []
        for seg in segments:
            t = (seg.text or "").strip()
            if t:
                parts.append(t)
        raw_text = " ".join(parts).strip()
        original_transcript, normalized_transcript = normalize_transcript(raw_text)
        # Chat / language path keeps cues; retrieval may use normalized form.
        text = original_transcript or normalized_transcript
        stt_lang = getattr(info, "language", None)
        conf = None
        try:
            lp = getattr(info, "language_probability", None)
            if lp is not None:
                conf = float(lp)
        except Exception:
            conf = None

        # Language from ORIGINAL transcript; UI language_hint must NOT lock STT.
        detected = resolve_transcript_language(original_transcript, stt_lang)
        _ = language_hint
        latency_ms = int((time.perf_counter() - started) * 1000)

        if not text:
            return {
                "success": False,
                "error": "empty_transcript",
                "message_key": "empty_audio",
                "detected_language": detected,
                "confidence": conf,
                "request_id": rid,
                "latency_ms": latency_ms,
                "failure_category": "STT_FAILED",
            }

        # Reject obvious Whisper garbage before RAG sees it
        tokens = [t for t in text.split() if t]
        if len(text.strip()) < 2 or (
            len(tokens) >= 4 and len(set(w.lower() for w in tokens)) <= 1
        ):
            return {
                "success": False,
                "error": "unreliable_transcript",
                "message_key": "low_confidence",
                "detected_language": detected,
                "confidence": conf,
                "request_id": rid,
                "latency_ms": latency_ms,
                "failure_category": "STT_LOW_CONFIDENCE",
            }

        min_c = float(getattr(settings, "STT_MIN_CONFIDENCE", 0.35))
        low_conf = conf is not None and conf < min_c

        logger.info(
            "STT ok request_id=%s lang=%s stt_lang=%s hint=%s chars=%s latency_ms=%s low_conf=%s",
            rid,
            detected,
            stt_lang,
            language_hint,
            len(text),
            latency_ms,
            low_conf,
        )
        return {
            "success": True,
            "text": text,
            "original_transcript": original_transcript,
            "normalized_transcript": normalized_transcript,
            "detected_language": detected,
            "confidence": conf,
            "low_confidence": low_conf,
            "stt_model": settings.STT_MODEL,
            "request_id": rid,
            "latency_ms": latency_ms,
            "audio_duration_seconds": validation.duration_seconds,
            "failure_category": "STT_LOW_CONFIDENCE" if low_conf else None,
        }
    except Exception as e:  # noqa: BLE001
        logger.warning("STT failed request_id=%s err=%s", rid, type(e).__name__)
        return {
            "success": False,
            "error": "stt_failed",
            "message_key": "stt_unavailable",
            "request_id": rid,
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "detail": type(e).__name__,
        }
    finally:
        _SEM.release()
        if path:
            try:
                os.unlink(path)
            except OSError:
                pass


# Allow tests to inject a fake engine
_TEST_TRANSCRIBE_HOOK = None


def set_test_transcribe_hook(fn) -> None:
    global _TEST_TRANSCRIBE_HOOK
    _TEST_TRANSCRIBE_HOOK = fn


def transcribe_audio_entry(
    data: bytes,
    *,
    content_type: Optional[str] = None,
    filename: Optional[str] = None,
    request_id: Optional[str] = None,
    language_hint: Optional[str] = None,
) -> Dict[str, Any]:
    if _TEST_TRANSCRIBE_HOOK is not None:
        return _TEST_TRANSCRIBE_HOOK(
            data,
            content_type=content_type,
            filename=filename,
            request_id=request_id,
            language_hint=language_hint,
        )
    return transcribe_audio(
        data,
        content_type=content_type,
        filename=filename,
        request_id=request_id,
        language_hint=language_hint,
    )
