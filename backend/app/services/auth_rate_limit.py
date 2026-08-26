"""Simple sliding-window rate limits for auth endpoints."""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from typing import Deque, Dict

from app.core.config import settings

_LOCK = threading.Lock()
_HITS: Dict[str, Deque[float]] = defaultdict(deque)


def reset_auth_rate_limits() -> None:
    """Clear in-memory auth rate-limit buckets (tests only)."""
    with _LOCK:
        _HITS.clear()


def auth_rate_limit_ok(key: str, *, bucket: str) -> bool:
    """Return True when the auth request is within configured limits."""
    window = float(getattr(settings, "AUTH_RATE_LIMIT_WINDOW_SECONDS", 3600.0))
    if bucket == "otp_send":
        max_hits = int(getattr(settings, "AUTH_OTP_SEND_MAX_PER_WINDOW", 5))
    else:
        max_hits = int(getattr(settings, "AUTH_RATE_LIMIT_MAX_PER_WINDOW", 30))
    if max_hits <= 0:
        return True
    composite = f"{bucket}:{key}"
    now = time.monotonic()
    with _LOCK:
        q = _HITS[composite]
        while q and now - q[0] > window:
            q.popleft()
        if len(q) >= max_hits:
            return False
        q.append(now)
        return True
