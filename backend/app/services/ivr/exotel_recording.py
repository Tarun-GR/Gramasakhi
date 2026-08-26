"""Narrow Exotel recording URL fetcher with SSRF protection (IVR-A2)."""

from __future__ import annotations

import ipaddress
import logging
import os
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable, Optional
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from app.core.config import settings
from app.services.voice.audio_utils import validate_audio_bytes

logger = logging.getLogger("gramsakhi.ivr.recording")

FetchHook = Callable[[str, float], tuple[bytes, Optional[str]]]
_FETCH_HOOK: Optional[FetchHook] = None

_BLOCKED_METADATA_HOSTS = frozenset(
    {
        "169.254.169.254",
        "169.254.170.2",
        "metadata.google.internal",
    }
)


@dataclass
class RecordingFetchResult:
    ok: bool
    data: Optional[bytes] = None
    content_type: Optional[str] = None
    temp_path: Optional[str] = None
    error: Optional[str] = None


def set_recording_fetch_hook(fn: Optional[FetchHook]) -> None:
    global _FETCH_HOOK
    _FETCH_HOOK = fn


def _allowed_host(host: str) -> bool:
    host = host.lower().rstrip(".")
    suffixes = settings.EXOTEL_RECORDING_ALLOWED_HOST_SUFFIXES or []
    for suffix in suffixes:
        s = suffix.lower().lstrip(".")
        if host == s or host.endswith(f".{s}"):
            return True
    return False


def validate_exotel_recording_url(url: str) -> None:
    """Reject URLs outside the documented Exotel recording contract."""
    raw = (url or "").strip().strip('"').strip("'")
    if not raw:
        raise ValueError("missing_recording_url")
    max_len = int(getattr(settings, "IVR_MAX_RECORDING_URL_LENGTH", 2048))
    if len(raw) > max_len:
        raise ValueError("recording_url_too_long")
    if raw.startswith("file:") or raw.startswith("data:"):
        raise ValueError("blocked_scheme")
    parsed = urlparse(raw)
    scheme = (parsed.scheme or "").lower()
    if scheme != "https":
        raise ValueError("invalid_scheme")
    host = (parsed.hostname or "").lower()
    if not host:
        raise ValueError("invalid_host")
    if host in _BLOCKED_METADATA_HOSTS or host.endswith(".internal"):
        raise ValueError("blocked_host")
    if host in {"localhost", "127.0.0.1", "::1", "0.0.0.0"}:
        raise ValueError("blocked_host")
    try:
        ip = ipaddress.ip_address(host)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            raise ValueError("blocked_host")
    except ValueError as exc:
        if str(exc) == "blocked_host":
            raise
    if not _allowed_host(host):
        raise ValueError("untrusted_host")


class _GuardedRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_exotel_recording_url(newurl)
        return HTTPRedirectHandler.redirect_request(self, req, fp, code, msg, headers, newurl)


def _default_fetch(url: str, timeout: float) -> tuple[bytes, Optional[str]]:
    validate_exotel_recording_url(url)
    max_bytes = int(float(settings.STT_MAX_AUDIO_SIZE_MB) * 1024 * 1024) + 1
    opener = build_opener(_GuardedRedirectHandler())
    req = Request(url, method="GET")
    try:
        with opener.open(req, timeout=timeout) as resp:
            content_type = resp.headers.get("Content-Type")
            chunks: list[bytes] = []
            total = 0
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise ValueError("audio_too_large")
                chunks.append(chunk)
            return b"".join(chunks), content_type
    except urllib.error.URLError as exc:
        raise ValueError("recording_fetch_failed") from exc


def fetch_exotel_recording_to_temp(url: str) -> RecordingFetchResult:
    """
    Download Exotel recording into a temp file; caller must delete temp_path in finally.
    """
    timeout = float(settings.EXOTEL_RECORDING_FETCH_TIMEOUT_SECONDS)
    temp_path: Optional[str] = None
    try:
        validate_exotel_recording_url(url)
        if _FETCH_HOOK is not None:
            data, content_type = _FETCH_HOOK(url, timeout)
        else:
            data, content_type = _default_fetch(url, timeout)

        validation = validate_audio_bytes(
            data,
            max_size_mb=float(settings.STT_MAX_AUDIO_SIZE_MB),
            max_duration_seconds=float(settings.STT_MAX_DURATION_SECONDS),
            content_type=content_type,
        )
        if not validation.ok:
            return RecordingFetchResult(ok=False, error=validation.error or "invalid_audio")

        suffix = {
            "wav": ".wav",
            "webm": ".webm",
            "ogg": ".ogg",
            "mp3": ".mp3",
        }.get(validation.format_hint or "", ".bin")
        fd, temp_path = tempfile.mkstemp(prefix="gramsakhi_ivr_rec_", suffix=suffix)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
        except Exception:
            try:
                os.close(fd)
            except OSError:
                pass
            raise

        return RecordingFetchResult(
            ok=True,
            data=data,
            content_type=content_type,
            temp_path=temp_path,
        )
    except ValueError as exc:
        if temp_path:
            _safe_unlink(temp_path)
        return RecordingFetchResult(ok=False, error=str(exc))
    except Exception:
        if temp_path:
            _safe_unlink(temp_path)
        logger.warning("exotel_recording_fetch_failed err=%s", "fetch_error")
        return RecordingFetchResult(ok=False, error="recording_fetch_failed")


def cleanup_recording_temp(path: Optional[str]) -> None:
    _safe_unlink(path)


def _safe_unlink(path: Optional[str]) -> None:
    if not path:
        return
    try:
        os.unlink(path)
    except OSError:
        pass
