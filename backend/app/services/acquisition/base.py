"""Shared types for adaptive government source acquisition."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class AcquisitionMethod(str, Enum):
    STATIC_HTTP = "static_http"
    DIRECT_DOCUMENT = "direct_document"
    BROWSER_JS = "browser_js"
    DYNAMIC_DOWNLOAD = "dynamic_download"
    PUBLIC_API = "public_api"
    EMBEDDED_VIEWER = "embedded_viewer"
    OCR = "ocr"


class SourceHealth(str, Enum):
    HEALTHY = "healthy"
    TEMPORARILY_UNAVAILABLE = "temporarily_unavailable"
    JS_REQUIRED = "js_required"
    CAPTCHA_BLOCKED = "captcha_blocked"
    LOGIN_REQUIRED = "login_required"
    PUBLIC_ACCESS_BLOCKED = "public_access_blocked"
    PARSER_FAILED = "parser_failed"
    DOCUMENT_UNAVAILABLE = "document_unavailable"
    SSRF_BLOCKED = "ssrf_blocked"
    UNTRUSTED = "untrusted"


class AccessBlockedError(Exception):
    """Raised when login/CAPTCHA/authorization blocks public retrieval."""

    def __init__(self, reason: str, health: SourceHealth = SourceHealth.PUBLIC_ACCESS_BLOCKED):
        super().__init__(reason)
        self.reason = reason
        self.health = health


@dataclass
class AcquisitionResult:
    url: str
    content: Optional[bytes] = None
    content_type: Optional[str] = None
    final_url: Optional[str] = None
    method: AcquisitionMethod = AcquisitionMethod.STATIC_HTTP
    health: SourceHealth = SourceHealth.HEALTHY
    error: Optional[str] = None
    discovered_links: List[Dict[str, Any]] = field(default_factory=list)
    rendered_text: Optional[str] = None
    meta: Dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.content is not None and self.error is None


# Login / CAPTCHA heuristics (public detection only — never bypass)
_LOGIN_MARKERS = (
    "sign in",
    "log in",
    "login",
    "username",
    "password",
    "otp",
    "one time password",
    "unauthorized",
    "access denied",
    "authentication required",
)

_CAPTCHA_MARKERS = (
    "captcha",
    "recaptcha",
    "hcaptcha",
    "verify you are human",
    "are you a robot",
    "cf-challenge",
    "challenge-platform",
    "browser verification",
)


def detect_access_block(html_or_text: str) -> Optional[SourceHealth]:
    blob = (html_or_text or "").lower()
    if not blob:
        return None
    if any(m in blob for m in _CAPTCHA_MARKERS):
        return SourceHealth.CAPTCHA_BLOCKED
    # Require stronger login signal than the bare word "login" in nav chrome
    # Strong login signals only — bare "otp"/"login" in SPA chrome is common on
    # public gov portals and must not abort public retrieval.
    strong_login = (
        'type="password"' in blob
        or 'name="password"' in blob
        or 'id="password"' in blob
        or "authentication required" in blob
        or "access denied" in blob
        or "unauthorized" in blob
        or "enter otp" in blob
        or "enter the otp" in blob
        or "one time password" in blob
        or "one-time password" in blob
        or ("otp" in blob and 'type="tel"' in blob and "verify" in blob)
    )
    if strong_login:
        return SourceHealth.LOGIN_REQUIRED
    return None
