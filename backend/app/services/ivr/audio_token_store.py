"""IVR-A4 opaque temporary audio token store (single-use, short-lived)."""

from __future__ import annotations

import os
import re
import secrets
import tempfile
import threading
import time
from dataclasses import dataclass
from typing import Optional

from app.core.config import settings

_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{32,128}$")


@dataclass
class IvrAudioEntry:
    token: str
    call_sid: str
    path: str
    mime_type: str
    expires_at: float
    consumed: bool = False


class IvrAudioTokenStore:
    """Non-enumerable, CallSid-scoped temporary audio files."""

    def __init__(self) -> None:
        self._entries: dict[str, IvrAudioEntry] = {}
        self._lock = threading.Lock()

    def issue(
        self,
        *,
        call_sid: str,
        data: bytes,
        mime_type: str,
        ttl_seconds: Optional[float] = None,
    ) -> str:
        with self._lock:
            self._purge_expired_locked()
            max_tokens = int(getattr(settings, "IVR_MAX_ACTIVE_AUDIO_TOKENS", 2000))
            if len(self._entries) >= max_tokens:
                raise OSError("ivr_audio_token_capacity")
        token = secrets.token_urlsafe(32)
        # IVR_PUBLIC_AUDIO_TOKEN_TTL is the documented spec name; it takes
        # precedence over the legacy IVR_AUDIO_TOKEN_TTL_SECONDS when set.
        alias_ttl = float(getattr(settings, "IVR_PUBLIC_AUDIO_TOKEN_TTL", 0.0) or 0.0)
        default_ttl = alias_ttl if alias_ttl > 0 else float(settings.IVR_AUDIO_TOKEN_TTL_SECONDS)
        ttl = float(ttl_seconds or default_ttl)
        fd, path = tempfile.mkstemp(prefix="gramsakhi_ivr_audio_", suffix=".mp3")
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
        except Exception:
            try:
                os.close(fd)
            except OSError:
                pass
            _safe_unlink(path)
            raise
        entry = IvrAudioEntry(
            token=token,
            call_sid=call_sid.strip(),
            path=path,
            mime_type=mime_type,
            expires_at=time.time() + ttl,
        )
        with self._lock:
            self._entries[token] = entry
        return token

    def get(self, token: str) -> Optional[IvrAudioEntry]:
        if not token or not _TOKEN_PATTERN.match(token):
            return None
        with self._lock:
            self._purge_expired_locked()
            entry = self._entries.get(token)
            if not entry:
                return None
            if entry.consumed or time.time() > entry.expires_at:
                return None
            return entry

    def consume(self, token: str) -> Optional[IvrAudioEntry]:
        if not token or not _TOKEN_PATTERN.match(token):
            return None
        with self._lock:
            entry = self._entries.get(token)
            if not entry:
                return None
            if entry.consumed or time.time() > entry.expires_at:
                self._delete_locked(token, entry)
                return None
            entry.consumed = True
            return entry

    def delete(self, token: str) -> None:
        with self._lock:
            entry = self._entries.pop(token, None)
        if entry:
            _safe_unlink(entry.path)

    def revoke_for_call_sid(self, call_sid: str, *, except_token: Optional[str] = None) -> None:
        sid = (call_sid or "").strip()
        if not sid:
            return
        with self._lock:
            doomed = [
                token
                for token, entry in self._entries.items()
                if entry.call_sid == sid and token != except_token
            ]
            entries = [self._entries.pop(token) for token in doomed]
        for entry in entries:
            _safe_unlink(entry.path)

    def reset(self) -> None:
        with self._lock:
            entries = list(self._entries.values())
            self._entries.clear()
        for entry in entries:
            _safe_unlink(entry.path)

    def _purge_expired_locked(self) -> None:
        now = time.time()
        expired = [
            token
            for token, entry in self._entries.items()
            if entry.consumed or now > entry.expires_at
        ]
        for token in expired:
            entry = self._entries.pop(token, None)
            if entry:
                _safe_unlink(entry.path)

    def _delete_locked(self, token: str, entry: IvrAudioEntry) -> None:
        self._entries.pop(token, None)
        _safe_unlink(entry.path)


_store = IvrAudioTokenStore()


def get_audio_token_store() -> IvrAudioTokenStore:
    return _store


def reset_audio_token_store() -> None:
    _store.reset()


def validate_audio_token(token: str) -> bool:
    return bool(token and _TOKEN_PATTERN.match(token))


def _safe_unlink(path: Optional[str]) -> None:
    if not path:
        return
    try:
        os.unlink(path)
    except OSError:
        pass
