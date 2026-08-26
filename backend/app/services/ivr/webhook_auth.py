"""IVR-A6 optional operator-configured webhook gate (not Exotel-native signature)."""

from __future__ import annotations

import secrets
from typing import Optional

from app.core.config import settings


def webhook_secret_required() -> bool:
    secret = (getattr(settings, "IVR_WEBHOOK_SHARED_SECRET", "") or "").strip()
    if not secret:
        return False
    if settings.APP_ENV.strip().lower() == "production":
        return True
    return bool(secret)


def verify_webhook_secret(
    *,
    header_value: Optional[str] = None,
    query_value: Optional[str] = None,
) -> bool:
    """
    Optional shared secret configured by the operator in Exotel Flow URL or header.

    Exotel Passthru/Gather callbacks do not document HMAC signatures; this is
    deployment hardening only — not a substitute for IP allowlisting.
    """
    expected = (getattr(settings, "IVR_WEBHOOK_SHARED_SECRET", "") or "").strip()
    if not expected:
        return True
    allow_query = bool(getattr(settings, "IVR_WEBHOOK_SECRET_ALLOW_QUERY", True))
    provided = (header_value or (query_value if allow_query else None) or "").strip()
    if not provided:
        return False
    return secrets.compare_digest(provided, expected)
