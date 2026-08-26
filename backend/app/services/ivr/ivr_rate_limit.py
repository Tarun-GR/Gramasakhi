"""IVR-A6 lightweight in-memory rate limiting for public telephony endpoints."""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from typing import Deque, Dict

from app.core.config import settings

_LOCK = threading.Lock()
_HITS: Dict[str, Deque[float]] = defaultdict(deque)


def _max_keys() -> int:
    return int(getattr(settings, "IVR_RATE_LIMIT_MAX_KEYS", 4096))


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


def ivr_rate_limit_ok(bucket: str, key: str) -> bool:
    window = float(getattr(settings, "IVR_RATE_LIMIT_WINDOW_SECONDS", 60.0))
    limits = {
        "call_sid": int(getattr(settings, "IVR_RATE_LIMIT_PER_CALLSID", 120)),
        "ip": int(getattr(settings, "IVR_RATE_LIMIT_PER_IP", 300)),
        "invalid": int(getattr(settings, "IVR_RATE_LIMIT_INVALID_PER_IP", 60)),
        "audio": int(getattr(settings, "IVR_RATE_LIMIT_AUDIO_PER_IP", 120)),
    }
    max_hits = limits.get(bucket, limits["ip"])
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


def ivr_rate_limit_key_count() -> int:
    with _LOCK:
        return len(_HITS)


def reset_ivr_rate_limits() -> None:
    with _LOCK:
        _HITS.clear()
