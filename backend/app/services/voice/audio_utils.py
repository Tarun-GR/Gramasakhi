"""Audio validation / normalization for STT (no RAG storage)."""

from __future__ import annotations

import io
import logging
import struct
import wave
from dataclasses import dataclass
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

# Magic signatures (do not trust Content-Type alone)
_WAV_MAGIC = b"RIFF"
_WEBM_MAGIC = b"\x1a\x45\xdf\xa3"
_OGG_MAGIC = b"OggS"
_MP3_ID3 = b"ID3"
_MP3_FF = b"\xff\xfb"


@dataclass
class AudioValidation:
    ok: bool
    error: Optional[str] = None
    format_hint: Optional[str] = None
    duration_seconds: Optional[float] = None
    sample_rate: Optional[int] = None


def sniff_format(data: bytes) -> Optional[str]:
    if not data or len(data) < 12:
        return None
    if data[:4] == _WAV_MAGIC and data[8:12] == b"WAVE":
        return "wav"
    if data[:4] == _WEBM_MAGIC:
        return "webm"
    if data[:4] == _OGG_MAGIC:
        return "ogg"
    if data[:3] == _MP3_ID3 or data[:2] == _MP3_FF:
        return "mp3"
    return None


def _wav_duration(data: bytes) -> Tuple[Optional[float], Optional[int]]:
    try:
        with wave.open(io.BytesIO(data), "rb") as wf:
            frames = wf.getnframes()
            rate = wf.getframerate() or 1
            return frames / float(rate), rate
    except Exception:
        return None, None


def validate_audio_bytes(
    data: bytes,
    *,
    max_size_mb: float,
    max_duration_seconds: float,
    content_type: Optional[str] = None,
) -> AudioValidation:
    if not data:
        return AudioValidation(ok=False, error="empty_audio")
    max_bytes = int(max(0.1, max_size_mb) * 1024 * 1024)
    if len(data) > max_bytes:
        return AudioValidation(ok=False, error="audio_too_large")

    fmt = sniff_format(data)
    # Allow browser webm/ogg even if sniff fails but content-type is audio/*
    ct = (content_type or "").lower()
    if not fmt:
        if "webm" in ct:
            fmt = "webm"
        elif "ogg" in ct:
            fmt = "ogg"
        elif "wav" in ct or "wave" in ct:
            fmt = "wav"
        elif "mpeg" in ct or "mp3" in ct:
            fmt = "mp3"
        else:
            return AudioValidation(ok=False, error="unsupported_audio_format")

    duration = None
    rate = None
    if fmt == "wav":
        duration, rate = _wav_duration(data)
        if duration is not None and duration > max_duration_seconds + 0.5:
            return AudioValidation(
                ok=False,
                error="audio_too_long",
                format_hint=fmt,
                duration_seconds=duration,
                sample_rate=rate,
            )
        # Near-silence / tiny wav
        if duration is not None and duration < 0.05:
            return AudioValidation(
                ok=False,
                error="empty_audio",
                format_hint=fmt,
                duration_seconds=duration,
                sample_rate=rate,
            )

    return AudioValidation(
        ok=True,
        format_hint=fmt,
        duration_seconds=duration,
        sample_rate=rate,
    )


def write_temp_audio(data: bytes, suffix: str) -> str:
    """Write bytes to a secure temp file; caller must delete."""
    import os
    import tempfile

    fd, path = tempfile.mkstemp(prefix="gramsakhi_voice_", suffix=suffix)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
    except Exception:
        try:
            os.close(fd)
        except Exception:
            pass
        raise
    return path


def make_silence_wav(duration_sec: float = 1.0, sample_rate: int = 16000) -> bytes:
    """Deterministic silent WAV fixture for tests."""
    n_frames = int(duration_sec * sample_rate)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(b"\x00\x00" * n_frames)
    return buf.getvalue()


def make_tone_wav(
    duration_sec: float = 0.5,
    sample_rate: int = 16000,
    freq: float = 440.0,
) -> bytes:
    """Simple tone WAV (not speech) for invalid/noisy fixture tests."""
    import math

    n_frames = int(duration_sec * sample_rate)
    frames = bytearray()
    for i in range(n_frames):
        val = int(12000 * math.sin(2 * math.pi * freq * (i / sample_rate)))
        frames += struct.pack("<h", val)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(bytes(frames))
    return buf.getvalue()
