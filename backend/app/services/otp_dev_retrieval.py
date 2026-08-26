"""Development-only OTP retrieval helpers (never active in production)."""

from __future__ import annotations

import secrets
from datetime import datetime

from app.core import security
from app.core.config import settings


def otp_dev_retrieval_active() -> bool:
    """True only when every development gate is explicitly satisfied."""
    if settings.APP_ENV.strip().lower() == "production":
        return False
    if not settings.OTP_DEV_RETRIEVAL_ENABLED:
        return False
    return bool((settings.OTP_DEV_RETRIEVAL_KEY or "").strip())


def otp_dev_key_valid(provided: str | None) -> bool:
    if not otp_dev_retrieval_active():
        return False
    expected = (settings.OTP_DEV_RETRIEVAL_KEY or "").strip()
    if not provided or not expected:
        return False
    return secrets.compare_digest(provided.strip(), expected)


def mask_phone_number(phone_number: str) -> str:
    digits = (phone_number or "").strip()
    if len(digits) <= 4:
        return "***"
    return f"***{digits[-4:]}"


def recover_otp_from_hash(otp_hash: str) -> str | None:
    """Reverse a 6-digit OTP hash for dev retrieval (read-only, dev-gated callers only)."""
    for value in range(1_000_000):
        candidate = f"{value:06d}"
        if security.verify_otp_hash(candidate, otp_hash):
            return candidate
    return None


def dev_retrieval_openapi_visible() -> bool:
    return otp_dev_retrieval_active()
