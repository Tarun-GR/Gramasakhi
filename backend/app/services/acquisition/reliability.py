"""Live acquisition reliability: health cooldowns, capabilities, rate limits, taxonomy."""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from app.services.acquisition.base import AcquisitionMethod, SourceHealth


class FailureCode(str, Enum):
    NETWORK_ERROR = "NETWORK_ERROR"
    TIMEOUT = "TIMEOUT"
    DNS_ERROR = "DNS_ERROR"
    TLS_ERROR = "TLS_ERROR"
    HTTP_4XX = "HTTP_4XX"
    HTTP_5XX = "HTTP_5XX"
    RATE_LIMITED = "RATE_LIMITED"
    CAPTCHA_BLOCKED = "CAPTCHA_BLOCKED"
    LOGIN_REQUIRED = "LOGIN_REQUIRED"
    UNAUTHORIZED = "UNAUTHORIZED"
    UNTRUSTED_REDIRECT = "UNTRUSTED_REDIRECT"
    SSRF_BLOCKED = "SSRF_BLOCKED"
    JS_RENDER_FAILED = "JS_RENDER_FAILED"
    PDF_NOT_FOUND = "PDF_NOT_FOUND"
    INVALID_PDF = "INVALID_PDF"
    HTML_SHELL = "HTML_SHELL"
    EMPTY_CONTENT = "EMPTY_CONTENT"
    OCR_FAILED = "OCR_FAILED"
    PARSE_FAILED = "PARSE_FAILED"
    API_FAILED = "API_FAILED"
    IRRELEVANT_DOCUMENT = "IRRELEVANT_DOCUMENT"
    SUPABASE_FAILED = "SUPABASE_FAILED"
    INDEX_FAILED = "INDEX_FAILED"
    VALIDATOR_FAILED = "VALIDATOR_FAILED"
    COOLDOWN_ACTIVE = "COOLDOWN_ACTIVE"
    BROWSER_UNAVAILABLE = "BROWSER_UNAVAILABLE"
    UNKNOWN = "UNKNOWN"


# Health states that should cool down (not permanent blacklist)
_COOLDOWN_SECONDS: Dict[SourceHealth, float] = {
    SourceHealth.CAPTCHA_BLOCKED: 3600.0,
    SourceHealth.LOGIN_REQUIRED: 3600.0,
    SourceHealth.PUBLIC_ACCESS_BLOCKED: 1800.0,
    SourceHealth.SSRF_BLOCKED: 86400.0,
    SourceHealth.TEMPORARILY_UNAVAILABLE: 120.0,
    SourceHealth.JS_REQUIRED: 300.0,
    SourceHealth.PARSER_FAILED: 300.0,
    SourceHealth.DOCUMENT_UNAVAILABLE: 300.0,
}


@dataclass
class HealthRecord:
    health: SourceHealth
    until_ts: float
    failure_code: Optional[str] = None
    last_error: Optional[str] = None


@dataclass
class DomainCapability:
    domain: str
    preferred_strategy: str = "static_http"  # static_http | browser_js | public_api
    supports_static: bool = True
    supports_browser: bool = True
    supports_api: bool = False
    supports_pdf: bool = True
    success_count: int = 0
    failure_count: int = 0
    static_success: int = 0
    browser_success: int = 0
    api_success: int = 0
    total_latency_ms: float = 0.0
    last_success: Optional[float] = None
    last_failure: Optional[float] = None
    last_failure_code: Optional[str] = None

    @property
    def average_latency_ms(self) -> float:
        n = self.success_count + self.failure_count
        return (self.total_latency_ms / n) if n else 0.0


_LOCK = threading.Lock()
_HEALTH: Dict[str, HealthRecord] = {}
_CAPABILITIES: Dict[str, DomainCapability] = {}
_DOMAIN_LAST_REQUEST: Dict[str, float] = {}
_DOMAIN_INFLIGHT: Dict[str, int] = defaultdict(int)
_ACQUIRE_STATS: Dict[str, Any] = {
    "attempts": 0,
    "successes": 0,
    "failures": 0,
    "by_method": defaultdict(int),
    "by_failure_code": defaultdict(int),
    "latency_ms_total": 0.0,
}

# Seed known preferences from real-world validation (overridable by learning)
_SEED_PREFERENCES: Dict[str, str] = {
    "nha.gov.in": "browser_js",
    "pmkisan.gov.in": "static_http",
    "pmfby.gov.in": "static_http",
    "food.karnataka.gov.in": "static_http",
    "wcd.karnataka.gov.in": "static_http",
    "rdpr.karnataka.gov.in": "static_http",
    "myscheme.gov.in": "browser_js",
}


def host_key(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower().strip(".")
    except Exception:
        return ""


def url_key(url: str) -> str:
    return (url or "").split("?")[0]


def classify_exception(exc: BaseException) -> FailureCode:
    name = type(exc).__name__.lower()
    msg = str(exc).lower()
    if "timeout" in name or "timeout" in msg:
        return FailureCode.TIMEOUT
    if "dns" in msg or "name or service not known" in msg or "getaddrinfo" in msg:
        return FailureCode.DNS_ERROR
    if "ssl" in msg or "certificate" in msg or "tls" in msg:
        return FailureCode.TLS_ERROR
    if "429" in msg:
        return FailureCode.RATE_LIMITED
    if any(c in msg for c in ("502", "503", "504", "500")):
        return FailureCode.HTTP_5XX
    if any(c in msg for c in ("401", "403", "404", "400")):
        return FailureCode.HTTP_4XX
    return FailureCode.NETWORK_ERROR


def get_health(url: str) -> Optional[SourceHealth]:
    key = url_key(url)
    with _LOCK:
        rec = _HEALTH.get(key)
        if not rec:
            return None
        if time.time() >= rec.until_ts:
            del _HEALTH[key]
            return None
        return rec.health


def _set_health_unlocked(
    url: str,
    health: SourceHealth,
    *,
    failure_code: Optional[FailureCode] = None,
    error: Optional[str] = None,
    cooldown_seconds: Optional[float] = None,
) -> None:
    """Caller must hold `_LOCK` when invoking this helper."""
    if health == SourceHealth.HEALTHY:
        _HEALTH.pop(url_key(url), None)
        return
    cool = cooldown_seconds
    if cool is None:
        cool = _COOLDOWN_SECONDS.get(health, 180.0)
    _HEALTH[url_key(url)] = HealthRecord(
        health=health,
        until_ts=time.time() + float(cool),
        failure_code=failure_code.value if failure_code else None,
        last_error=(error or "")[:200] or None,
    )


def set_health(
    url: str,
    health: SourceHealth,
    *,
    failure_code: Optional[FailureCode] = None,
    error: Optional[str] = None,
    cooldown_seconds: Optional[float] = None,
) -> None:
    with _LOCK:
        _set_health_unlocked(
            url,
            health,
            failure_code=failure_code,
            error=error,
            cooldown_seconds=cooldown_seconds,
        )


def get_capability(url: str) -> DomainCapability:
    host = host_key(url)
    with _LOCK:
        cap = _CAPABILITIES.get(host)
        if cap:
            return cap
        preferred = _SEED_PREFERENCES.get(host, "static_http")
        cap = DomainCapability(domain=host, preferred_strategy=preferred)
        _CAPABILITIES[host] = cap
        return cap


def record_acquire(
    url: str,
    *,
    method: AcquisitionMethod,
    ok: bool,
    latency_ms: float,
    health: SourceHealth,
    failure_code: Optional[FailureCode] = None,
) -> None:
    host = host_key(url)
    with _LOCK:
        cap = _CAPABILITIES.get(host) or DomainCapability(
            domain=host,
            preferred_strategy=_SEED_PREFERENCES.get(host, "static_http"),
        )
        _CAPABILITIES[host] = cap
        cap.total_latency_ms += float(latency_ms)
        _ACQUIRE_STATS["attempts"] += 1
        _ACQUIRE_STATS["latency_ms_total"] += float(latency_ms)
        _ACQUIRE_STATS["by_method"][method.value] += 1
        if ok:
            cap.success_count += 1
            cap.last_success = time.time()
            _ACQUIRE_STATS["successes"] += 1
            if method in (AcquisitionMethod.STATIC_HTTP, AcquisitionMethod.DIRECT_DOCUMENT):
                cap.static_success += 1
                cap.supports_static = True
            elif method in (
                AcquisitionMethod.BROWSER_JS,
                AcquisitionMethod.DYNAMIC_DOWNLOAD,
            ):
                cap.browser_success += 1
                cap.supports_browser = True
            elif method == AcquisitionMethod.PUBLIC_API:
                cap.api_success += 1
                cap.supports_api = True
            # Prefer strategy that has clear majority of successes
            if cap.browser_success >= max(3, cap.static_success + 2):
                cap.preferred_strategy = "browser_js"
            elif cap.static_success >= max(2, cap.browser_success):
                cap.preferred_strategy = "static_http"
            elif cap.api_success >= 2 and cap.api_success >= cap.static_success:
                cap.preferred_strategy = "public_api"
        else:
            cap.failure_count += 1
            cap.last_failure = time.time()
            cap.last_failure_code = failure_code.value if failure_code else None
            _ACQUIRE_STATS["failures"] += 1
            if failure_code:
                _ACQUIRE_STATS["by_failure_code"][failure_code.value] += 1
        if health != SourceHealth.HEALTHY:
            # Use unlocked setter — we already hold `_LOCK`
            _set_health_unlocked(url, health, failure_code=failure_code)


def acquire_stats_snapshot() -> Dict[str, Any]:
    with _LOCK:
        caps = []
        for cap in list(_CAPABILITIES.values())[:80]:
            caps.append(
                {
                    "domain": cap.domain,
                    "preferred_strategy": cap.preferred_strategy,
                    "supports_static": cap.supports_static,
                    "supports_browser": cap.supports_browser,
                    "supports_api": cap.supports_api,
                    "success_count": cap.success_count,
                    "failure_count": cap.failure_count,
                    "average_latency_ms": round(cap.average_latency_ms, 1),
                    "last_success": cap.last_success,
                    "last_failure": cap.last_failure,
                    "last_failure_code": cap.last_failure_code,
                }
            )
        health = [
            {
                "url": u,
                "health": r.health.value,
                "until_ts": r.until_ts,
                "failure_code": r.failure_code,
            }
            for u, r in list(_HEALTH.items())[-100:]
        ]
        return {
            "attempts": _ACQUIRE_STATS["attempts"],
            "successes": _ACQUIRE_STATS["successes"],
            "failures": _ACQUIRE_STATS["failures"],
            "by_method": dict(_ACQUIRE_STATS["by_method"]),
            "by_failure_code": dict(_ACQUIRE_STATS["by_failure_code"]),
            "capabilities": caps,
            "recent_health": health,
        }


def rate_limit_wait(url: str, *, min_interval: float = 0.6, max_inflight: int = 2) -> float:
    """Block briefly for per-domain politeness. Returns seconds waited."""
    host = host_key(url) or "unknown"
    waited = 0.0
    while True:
        with _LOCK:
            inflight = _DOMAIN_INFLIGHT.get(host, 0)
            last = _DOMAIN_LAST_REQUEST.get(host, 0.0)
            now = time.time()
            gap = now - last
            if inflight < max_inflight and gap >= min_interval:
                _DOMAIN_INFLIGHT[host] = inflight + 1
                _DOMAIN_LAST_REQUEST[host] = now
                return waited
            sleep_for = max(0.05, min_interval - gap) if gap < min_interval else 0.05
        time.sleep(sleep_for)
        waited += sleep_for
        if waited > 10.0:
            # Fail open after long wait — do not deadlock live path
            with _LOCK:
                _DOMAIN_INFLIGHT[host] = _DOMAIN_INFLIGHT.get(host, 0) + 1
                _DOMAIN_LAST_REQUEST[host] = time.time()
            return waited


def rate_limit_release(url: str) -> None:
    host = host_key(url) or "unknown"
    with _LOCK:
        _DOMAIN_INFLIGHT[host] = max(0, _DOMAIN_INFLIGHT.get(host, 0) - 1)


def reset_reliability_state_for_tests() -> None:
    """Test helper — clears in-process reliability caches."""
    with _LOCK:
        _HEALTH.clear()
        _CAPABILITIES.clear()
        _DOMAIN_LAST_REQUEST.clear()
        _DOMAIN_INFLIGHT.clear()
        _ACQUIRE_STATS["attempts"] = 0
        _ACQUIRE_STATS["successes"] = 0
        _ACQUIRE_STATS["failures"] = 0
        _ACQUIRE_STATS["by_method"] = defaultdict(int)
        _ACQUIRE_STATS["by_failure_code"] = defaultdict(int)
        _ACQUIRE_STATS["latency_ms_total"] = 0.0
