"""Simple sliding-window rate limits for auth endpoints."""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from typing import Deque, Dict, Optional

from fastapi import Request

from app.core.config import settings

_LOCK = threading.Lock()
_HITS: Dict[str, Deque[float]] = defaultdict(deque)


def reset_auth_rate_limits() -> None:
    """Clear in-memory auth rate-limit buckets (tests only)."""
    with _LOCK:
        _HITS.clear()


def client_ip(request: Optional[Request]) -> str:
    if request is None or request.client is None:
        return "unknown"
    return request.client.host or "unknown"


def _max_keys() -> int:
    return int(getattr(settings, "AUTH_RATE_LIMIT_MAX_KEYS", 4096))


def _window_and_max(bucket: str) -> tuple[float, int]:
    if bucket == "otp_send":
        return (
            float(getattr(settings, "AUTH_RATE_LIMIT_WINDOW_SECONDS", 3600.0)),
            int(getattr(settings, "AUTH_OTP_SEND_MAX_PER_WINDOW", 5)),
        )
    if bucket == "login":
        return (
            float(getattr(settings, "AUTH_LOGIN_WINDOW_SECONDS", 900.0)),
            int(getattr(settings, "AUTH_LOGIN_MAX_PER_WINDOW", 10)),
        )
    return (
        float(getattr(settings, "AUTH_RATE_LIMIT_WINDOW_SECONDS", 3600.0)),
        int(getattr(settings, "AUTH_RATE_LIMIT_MAX_PER_WINDOW", 30)),
    )


def _purge_stale_locked(now: float, window: float) -> None:
    stale = [key for key, q in _HITS.items() if not q or now - q[-1] > window]
    for key in stale:
        _HITS.pop(key, None)
    cap = _max_keys()
    overflow = len(_HITS) - cap
    if overflow <= 0:
        return
    oldest = sorted(_HITS.items(), key=lambda item: item[1][-1] if item[1] else 0.0)
    for key, _ in oldest[:overflow]:
        _HITS.pop(key, None)


def auth_rate_limit_ok(key: str, *, bucket: str) -> bool:
    """Return True when the auth request is within configured limits."""
    window, max_hits = _window_and_max(bucket)
    if max_hits <= 0:
        return True
    composite = f"{bucket}:{key}"
    now = time.monotonic()
    with _LOCK:
        _purge_stale_locked(now, window)
        q = _HITS[composite]
        while q and now - q[0] > window:
            q.popleft()
        if len(q) >= max_hits:
            return False
        q.append(now)
        overflow = len(_HITS) - _max_keys()
        if overflow > 0:
            oldest = sorted(
                ((k, v) for k, v in _HITS.items() if k != composite),
                key=lambda item: item[1][-1] if item[1] else 0.0,
            )
            for stale_key, _ in oldest[:overflow]:
                _HITS.pop(stale_key, None)
        return True
