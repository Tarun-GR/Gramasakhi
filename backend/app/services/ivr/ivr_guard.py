"""IVR-A6 centralized endpoint guards — CallSid, webhook, rate limits, session."""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import HTTPException, Request, status

from app.services.ivr.call_sid_validation import CallSidValidationError, normalize_call_sid
from app.services.ivr.ivr_rate_limit import ivr_rate_limit_ok
from app.services.ivr.language_session import SessionCapacityError, SessionExpiredError, SessionNotFoundError, get_session_store
from app.services.ivr.webhook_auth import verify_webhook_secret, webhook_secret_required

logger = logging.getLogger("gramsakhi.ivr.guard")


def _client_ip(request: Optional[Request]) -> str:
    if request is None:
        return "unknown"
    from app.core.config import settings

    if bool(getattr(settings, "IVR_TRUST_PROXY_HEADERS", False)):
        forwarded = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
        if forwarded:
            return forwarded
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def require_ivr_webhook_access(
    request: Optional[Request],
    *,
    ivr_secret_query: Optional[str] = None,
) -> None:
    ip = _client_ip(request)
    if not ivr_rate_limit_ok("ip", ip):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many requests.")

    header_secret = request.headers.get("x-gramsakhi-ivr-secret") if request else None
    if webhook_secret_required() and not verify_webhook_secret(
        header_value=header_secret,
        query_value=ivr_secret_query,
    ):
        logger.warning("ivr_webhook_auth_failed category=secret")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden.")


def parse_and_guard_call_sid(
    raw: Optional[str],
    *,
    request: Optional[Request] = None,
    require_active_session: bool = False,
    allow_create: bool = True,
) -> str:
    ip = _client_ip(request)
    try:
        sid = normalize_call_sid(raw)
    except CallSidValidationError:
        ivr_rate_limit_ok("invalid", ip)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid CallSid.",
        ) from None

    if not ivr_rate_limit_ok("call_sid", sid):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many requests.")

    store = get_session_store()
    try:
        if require_active_session or not allow_create:
            store.require_active_session(sid)
        else:
            store.touch_or_create(sid)
    except SessionNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unknown CallSid — complete language selection first.",
        ) from None
    except SessionExpiredError:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="IVR session expired.",
        ) from None
    except SessionCapacityError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="IVR capacity reached. Please try again later.",
        ) from None

    return sid


def guard_audio_fetch(request: Optional[Request]) -> None:
    ip = _client_ip(request)
    if not ivr_rate_limit_ok("audio", ip):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many requests.")
