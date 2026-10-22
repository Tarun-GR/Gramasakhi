"""Production-safe FYP demo login (allowlisted demo citizen phone only)."""

from __future__ import annotations

import sys
from typing import Any, Dict, List

from app.core.config import settings

DEMO_OTP_NOTICE = (
    "FYP demonstration login — this one-time code is shown only for the designated "
    "demo citizen account. It is not sent by SMS and does not apply to other numbers."
)


def _normalize_phone(phone: str) -> str:
    s = (phone or "").replace(" ", "").replace("-", "").strip()
    if s.startswith("+91"):
        s = s[3:]
    return s


def demo_login_enabled() -> bool:
    return bool(settings.DEMO_LOGIN_ENABLED)


def demo_phone_allowlist() -> List[str]:
    raw = (settings.DEMO_LOGIN_PHONES or "").strip()
    if not raw:
        return []
    parts = [p.strip() for p in raw.replace(";", ",").split(",") if p.strip()]
    return [_normalize_phone(p) for p in parts]


def is_demo_login_phone(phone: str) -> bool:
    normalized = _normalize_phone(phone)
    if not normalized:
        return False
    return normalized in set(demo_phone_allowlist())


def demo_otp_may_be_returned(phone: str) -> bool:
    """True when POST /otp/send may include demo_otp for this phone (login send only)."""
    return demo_login_enabled() and is_demo_login_phone(phone)


def validate_demo_login_config() -> None:
    """Refuse startup when demo mode is enabled without an allowlist."""
    if any(name in sys.modules for name in ("pytest", "unittest")):
        return
    if not demo_login_enabled():
        return
    phones = demo_phone_allowlist()
    if not phones:
        print(
            "FATAL: DEMO_LOGIN_ENABLED=true but DEMO_LOGIN_PHONES is empty. "
            "Set one dedicated demo mobile (10 digits) in Render env.",
            flush=True,
        )
        sys.exit(1)
    if len(phones) > 3:
        print(
            "FATAL: DEMO_LOGIN_PHONES has too many entries; use at most 3 demo numbers.",
            flush=True,
        )
        sys.exit(1)


def public_demo_info() -> Dict[str, Any]:
    """Public metadata for the login UI (no OTP, no secrets)."""
    if not demo_login_enabled():
        return {"enabled": False}
    phones = demo_phone_allowlist()
    if not phones:
        return {"enabled": False}
    primary = phones[0]
    label = (settings.DEMO_LOGIN_LABEL or "FYP demo citizen").strip()
    return {
        "enabled": True,
        "demo_phone": primary,
        "demo_phones": phones,
        "label": label,
        "notice": DEMO_OTP_NOTICE,
    }
