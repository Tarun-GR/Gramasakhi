"""Text-to-Speech adapter (Phase 7).

Synthesizes ONLY grounded assistant text. Never answers questions.
Uses edge-tts when installed (KN/HI/EN neural voices).
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import threading
import time
import uuid
from collections import OrderedDict
from typing import Any, Dict, Optional, Tuple

from app.core.config import settings
from app.services.language_service import normalize_language_code
from app.services.voice.pronunciation import build_tts_text

logger = logging.getLogger(__name__)

_SEM = threading.Semaphore(max(1, int(getattr(settings, "TTS_MAX_CONCURRENT", 2))))
_CACHE: "OrderedDict[str, bytes]" = OrderedDict()
_CACHE_LOCK = threading.Lock()
_TEST_SYNTH_HOOK = None


def _voice_for(lang: str) -> str:
    code = normalize_language_code(lang) or "EN"
    if code == "KN":
        return settings.TTS_VOICE_KN
    if code == "HI":
        return settings.TTS_VOICE_HI
    return settings.TTS_VOICE_EN


def get_tts_health() -> Dict[str, Any]:
    configured = bool(getattr(settings, "TTS_ENABLED", True))
    info = {
        "configured": configured,
        "available": False,
        "model": settings.TTS_MODEL,
        "model_loaded": False,  # edge-tts is network/API; no heavy local load
        "device": settings.TTS_DEVICE,
        "supported_languages": ["EN", "KN", "HI"],
        "voices": {
            "EN": settings.TTS_VOICE_EN,
            "KN": settings.TTS_VOICE_KN,
            "HI": settings.TTS_VOICE_HI,
        },
        "version": None,
        "runtime": "edge-tts",
        "audio_format": "audio/mpeg",
        "detail": None,
    }
    if not configured:
        info["detail"] = "TTS_ENABLED=false"
        return info
    try:
        import edge_tts  # noqa: F401

        info["version"] = getattr(edge_tts, "__version__", "installed")
        info["available"] = True
        info["model_loaded"] = True
        info["detail"] = "ok"
    except Exception as e:  # noqa: BLE001
        info["detail"] = f"edge-tts not installed: {type(e).__name__}"
        info["available"] = False
        info["model_loaded"] = False
    return info


def _cache_key(text: str, language: str, voice: str) -> str:
    raw = f"{text}|{language}|{voice}|{settings.TTS_MODEL}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _cache_get(key: str) -> Optional[bytes]:
    if not settings.TTS_CACHE_ENABLED:
        return None
    with _CACHE_LOCK:
        val = _CACHE.get(key)
        if val is not None:
            _CACHE.move_to_end(key)
        return val


def _cache_put(key: str, audio: bytes) -> None:
    if not settings.TTS_CACHE_ENABLED:
        return
    with _CACHE_LOCK:
        _CACHE[key] = audio
        _CACHE.move_to_end(key)
        while len(_CACHE) > int(settings.TTS_CACHE_MAX_ENTRIES):
            _CACHE.popitem(last=False)


async def _edge_synthesize(text: str, voice: str) -> bytes:
    import edge_tts

    communicate = edge_tts.Communicate(text, voice)
    chunks = []
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            chunks.append(chunk["data"])
    return b"".join(chunks)


def _run_async(coro, timeout: float) -> bytes:
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # Nested: run in new loop in thread
            result: Dict[str, Any] = {}

            def runner():
                result["v"] = asyncio.run(asyncio.wait_for(coro, timeout=timeout))

            t = threading.Thread(target=runner, daemon=True)
            t.start()
            t.join(timeout=timeout + 1)
            if "v" not in result:
                raise TimeoutError("TTS timed out")
            return result["v"]
        return loop.run_until_complete(asyncio.wait_for(coro, timeout=timeout))
    except RuntimeError:
        return asyncio.run(asyncio.wait_for(coro, timeout=timeout))


def synthesize_speech(
    text: str,
    *,
    language: str,
    request_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Synthesize speech for grounded assistant text.

    Returns audio bytes + metadata, or controlled failure.
    """
    rid = request_id or str(uuid.uuid4())
    started = time.perf_counter()
    code = normalize_language_code(language) or "EN"

    if not getattr(settings, "TTS_ENABLED", True):
        return {
            "success": False,
            "error": "tts_disabled",
            "message_key": "tts_unavailable",
            "request_id": rid,
        }

    display, tts_text = build_tts_text(text or "", code)
    if not tts_text.strip():
        return {
            "success": False,
            "error": "empty_text",
            "message_key": "tts_failed",
            "request_id": rid,
        }

    voice = _voice_for(code)
    key = _cache_key(tts_text, code, voice)
    cached = _cache_get(key)
    if cached:
        return {
            "success": True,
            "audio": cached,
            "mime_type": "audio/mpeg",
            "language": code,
            "voice": voice,
            "cached": True,
            "display_text": display,
            "tts_text": tts_text,
            "request_id": rid,
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "tts_model": settings.TTS_MODEL,
        }

    acquired = _SEM.acquire(timeout=float(settings.TTS_TIMEOUT_SECONDS))
    if not acquired:
        return {
            "success": False,
            "error": "tts_busy",
            "message_key": "tts_busy",
            "request_id": rid,
        }

    try:
        audio = _run_async(
            _edge_synthesize(tts_text, voice),
            timeout=float(settings.TTS_TIMEOUT_SECONDS),
        )
        if not audio:
            return {
                "success": False,
                "error": "tts_empty",
                "message_key": "tts_failed",
                "request_id": rid,
                "latency_ms": int((time.perf_counter() - started) * 1000),
            }
        _cache_put(key, audio)
        latency_ms = int((time.perf_counter() - started) * 1000)
        logger.info(
            "TTS ok request_id=%s lang=%s voice=%s bytes=%s latency_ms=%s",
            rid,
            code,
            voice,
            len(audio),
            latency_ms,
        )
        return {
            "success": True,
            "audio": audio,
            "mime_type": "audio/mpeg",
            "language": code,
            "voice": voice,
            "cached": False,
            "display_text": display,
            "tts_text": tts_text,
            "request_id": rid,
            "latency_ms": latency_ms,
            "tts_model": settings.TTS_MODEL,
        }
    except Exception as e:  # noqa: BLE001
        logger.warning("TTS failed request_id=%s err=%s", rid, type(e).__name__)
        return {
            "success": False,
            "error": "tts_failed",
            "message_key": "tts_unavailable",
            "request_id": rid,
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "detail": type(e).__name__,
        }
    finally:
        _SEM.release()


def set_test_synthesize_hook(fn) -> None:
    global _TEST_SYNTH_HOOK
    _TEST_SYNTH_HOOK = fn


def synthesize_speech_entry(
    text: str,
    *,
    language: str,
    request_id: Optional[str] = None,
) -> Dict[str, Any]:
    if _TEST_SYNTH_HOOK is not None:
        return _TEST_SYNTH_HOOK(text, language=language, request_id=request_id)
    return synthesize_speech(text, language=language, request_id=request_id)
