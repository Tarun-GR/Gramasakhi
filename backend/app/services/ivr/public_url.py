"""IVR-A4 public playback URL builder — never trusts request Host headers."""

from __future__ import annotations

import re
from urllib.parse import urlparse

from app.core.config import settings

_PRIVATE_HOST = re.compile(
    r"^(localhost|127\.0\.0\.1|::1|0\.0\.0\.0|"
    r"10\.\d+\.\d+\.\d+|192\.168\.\d+\.\d+|172\.(?:1[6-9]|2\d|3[01])\.\d+\.\d+)$",
    re.IGNORECASE,
)


def validate_ivr_public_base_url(base: str, *, app_env: str | None = None) -> None:
    """Validate configured public base URL; raise ValueError on failure."""
    env = (app_env or settings.APP_ENV or "").strip().lower()
    raw = (base or "").strip().rstrip("/")
    if not raw:
        raise ValueError("ivr_public_base_missing")
    parsed = urlparse(raw)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError("ivr_public_base_invalid")
    host = (parsed.hostname or "").lower()
    if _PRIVATE_HOST.match(host):
        if env == "production":
            raise ValueError("ivr_public_base_private")
        return
    if env == "production" and parsed.scheme != "https":
        raise ValueError("ivr_public_base_https_required")


def build_ivr_public_url(path: str) -> str:
    """
    Build Exotel-fetchable URL from configured IVR_PUBLIC_BASE_URL only.
    """
    validate_ivr_public_base_url(settings.IVR_PUBLIC_BASE_URL, app_env=settings.APP_ENV)
    base = (settings.IVR_PUBLIC_BASE_URL or "").strip().rstrip("/")
    suffix = path if path.startswith("/") else f"/{path}"
    return f"{base}{suffix}"


def build_ivr_audio_url(token: str) -> str:
    return build_ivr_public_url(f"/api/ivr/audio/{token}")
