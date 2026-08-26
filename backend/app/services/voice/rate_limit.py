"""Simple per-user sliding-window rate limit for voice endpoints."""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from typing import Deque, Dict

from app.core.config import settings

_LOCK = threading.Lock()
_HITS: Dict[str, Deque[float]] = defaultdict(deque)


def voice_rate_limit_ok(user_id: str, *, bucket: str) -> bool:
    """
    Return True if the request is allowed.
    Window: VOICE_RATE_LIMIT_WINDOW_SECONDS, max: VOICE_RATE_LIMIT_PER_WINDOW.
    """
    window = float(getattr(settings, "VOICE_RATE_LIMIT_WINDOW_SECONDS", 60.0))
    max_hits = int(getattr(settings, "VOICE_RATE_LIMIT_PER_WINDOW", 30))
    if max_hits <= 0:
        return True
    key = f"{bucket}:{user_id}"
    now = time.monotonic()
    with _LOCK:
        q = _HITS[key]
        while q and now - q[0] > window:
            q.popleft()
        if len(q) >= max_hits:
            return False
        q.append(now)
        return True
