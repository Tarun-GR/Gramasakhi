"""IVR-A6 CallSid validation — single canonical representation."""

from __future__ import annotations

import re

from app.core.config import settings

_CALL_SID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


class CallSidValidationError(ValueError):
    pass


def normalize_call_sid(raw: str | None) -> str:
    """Validate Exotel CallSid; return stripped canonical form or raise."""
    if raw is None:
        raise CallSidValidationError("missing_call_sid")
    sid = raw.strip()
    if not sid:
        raise CallSidValidationError("empty_call_sid")
    max_len = int(getattr(settings, "IVR_MAX_CALL_SID_LENGTH", 64))
    if len(sid) > max_len:
        raise CallSidValidationError("call_sid_too_long")
    if _CONTROL_CHARS.search(sid):
        raise CallSidValidationError("call_sid_control_chars")
    if ".." in sid or "/" in sid or "\\" in sid:
        raise CallSidValidationError("call_sid_path_chars")
    if not _CALL_SID_PATTERN.match(sid):
        raise CallSidValidationError("call_sid_invalid_chars")
    return sid


def is_valid_call_sid(raw: str | None) -> bool:
    try:
        normalize_call_sid(raw)
        return True
    except CallSidValidationError:
        return False


def mask_call_sid(call_sid: str | None) -> str:
    """Privacy-safe CallSid form for logs: first 4 + last 4 characters only."""
    sid = (call_sid or "").strip()
    if len(sid) <= 8:
        return "***"
    return f"{sid[:4]}…{sid[-4:]}"
