"""In-memory IVR call session store keyed by Exotel CallSid (A1–A5; A6 TTL + bounds).

Limitations:
- Process restart clears all active IVR session state.
- Multiple backend instances require shared storage (e.g. Redis) for production IVR.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Optional

from app.core.config import settings
from app.services.ivr.constants import SUPPORTED_LANGUAGES


class SessionExpiredError(Exception):
    pass


class SessionNotFoundError(Exception):
    pass


class SessionCapacityError(Exception):
    pass


@dataclass
class IvrCallSession:
    call_sid: str
    language: Optional[str] = None
    state: str = "language_selection"
    turn_count: int = 0
    turn_in_progress: bool = False
    menu_shown: bool = False
    invalid_attempts: int = 0
    no_input_attempts: int = 0
    silence_attempts: int = 0
    continue_invalid_attempts: int = 0
    continue_no_input_attempts: int = 0
    chat_failure_attempts: int = 0
    tts_failure_attempts: int = 0
    transcription: Optional[str] = None
    stt_attempts: int = 0
    last_stt_low_confidence: bool = False
    last_stt_request_id: Optional[str] = None
    conversation_id: Optional[str] = None
    last_response_language: Optional[str] = None
    last_response_text: Optional[str] = None
    active_audio_token: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    last_activity_at: float = field(default_factory=time.time)
    expires_at: float = 0.0


class IvrLanguageSessionStore:
    """One CallSid maps to one isolated session; sessions never overwrite each other."""

    def __init__(self) -> None:
        self._sessions: dict[str, IvrCallSession] = {}
        self._lock = threading.Lock()

    def _session_ttl(self) -> float:
        return float(getattr(settings, "IVR_SESSION_TTL_SECONDS", 1800.0))

    def _max_sessions(self) -> int:
        return int(getattr(settings, "IVR_MAX_ACTIVE_SESSIONS", 1000))

    def _refresh_expiry(self, session: IvrCallSession) -> None:
        now = time.time()
        session.last_activity_at = now
        session.expires_at = now + self._session_ttl()

    def _is_expired(self, session: IvrCallSession) -> bool:
        return time.time() > float(session.expires_at or 0)

    def _purge_expired_locked(self) -> None:
        expired = [sid for sid, s in self._sessions.items() if self._is_expired(s)]
        for sid in expired:
            self._sessions.pop(sid, None)

    def _touch_or_create_unlocked(self, call_sid: str) -> IvrCallSession:
        sid = call_sid.strip()
        self._purge_expired_locked()
        session = self._sessions.get(sid)
        if session is not None:
            if self._is_expired(session):
                self._sessions.pop(sid, None)
            else:
                self._refresh_expiry(session)
                return session
        if len(self._sessions) >= self._max_sessions():
            raise SessionCapacityError("ivr_session_capacity")
        session = IvrCallSession(call_sid=sid)
        self._refresh_expiry(session)
        self._sessions[sid] = session
        return session

    def touch_or_create(self, call_sid: str) -> IvrCallSession:
        with self._lock:
            return self._touch_or_create_unlocked(call_sid)

    def require_active_session(self, call_sid: str) -> IvrCallSession:
        sid = call_sid.strip()
        with self._lock:
            self._purge_expired_locked()
            session = self._sessions.get(sid)
            if session is None:
                raise SessionNotFoundError("ivr_session_not_found")
            if self._is_expired(session):
                self._sessions.pop(sid, None)
                raise SessionExpiredError("ivr_session_expired")
            self._refresh_expiry(session)
            return session

    def _get_or_create(self, call_sid: str) -> IvrCallSession:
        return self._touch_or_create_unlocked(call_sid)

    def set_language(self, call_sid: str, language: str) -> None:
        lang = (language or "").strip().lower()
        if lang not in SUPPORTED_LANGUAGES:
            raise ValueError(f"Unsupported IVR language: {language!r}")
        with self._lock:
            session = self._get_or_create(call_sid)
            session.language = lang

    def get_language(self, call_sid: str) -> Optional[str]:
        with self._lock:
            session = self._sessions.get(call_sid.strip())
            return session.language if session else None

    def has_language(self, call_sid: str) -> bool:
        with self._lock:
            session = self._sessions.get(call_sid.strip())
            return bool(session and session.language)

    def session_exists(self, call_sid: str) -> bool:
        with self._lock:
            return call_sid.strip() in self._sessions

    def set_transcription(
        self,
        call_sid: str,
        *,
        transcription: Optional[str],
        low_confidence: bool = False,
        request_id: Optional[str] = None,
    ) -> None:
        with self._lock:
            session = self._get_or_create(call_sid)
            session.transcription = transcription
            session.last_stt_low_confidence = low_confidence
            session.last_stt_request_id = request_id

    def increment_stt_attempts(self, call_sid: str) -> int:
        with self._lock:
            session = self._get_or_create(call_sid)
            session.stt_attempts += 1
            return session.stt_attempts

    def get_transcription(self, call_sid: str) -> Optional[str]:
        with self._lock:
            session = self._sessions.get(call_sid.strip())
            return session.transcription if session else None

    def get_conversation_id(self, call_sid: str) -> Optional[str]:
        with self._lock:
            session = self._sessions.get(call_sid.strip())
            return session.conversation_id if session else None

    def set_conversation_id(self, call_sid: str, conversation_id: str) -> None:
        with self._lock:
            session = self._get_or_create(call_sid)
            session.conversation_id = conversation_id.strip()

    def set_last_response_language(self, call_sid: str, language: Optional[str]) -> None:
        with self._lock:
            session = self._get_or_create(call_sid)
            session.last_response_language = language

    def get_last_response_language(self, call_sid: str) -> Optional[str]:
        with self._lock:
            session = self._sessions.get(call_sid.strip())
            return session.last_response_language if session else None

    def set_last_response_text(self, call_sid: str, text: Optional[str]) -> None:
        with self._lock:
            session = self._get_or_create(call_sid)
            session.last_response_text = text

    def get_last_response_text(self, call_sid: str) -> Optional[str]:
        with self._lock:
            session = self._sessions.get(call_sid.strip())
            return session.last_response_text if session else None

    def get_session(self, call_sid: str) -> IvrCallSession:
        with self._lock:
            return self._get_or_create(call_sid)

    def peek_session(self, call_sid: str) -> Optional[IvrCallSession]:
        """Read a session without creating one (cleanup/inspection paths)."""
        with self._lock:
            return self._sessions.get(call_sid.strip())

    def clear_session(self, call_sid: str) -> None:
        with self._lock:
            self._sessions.pop(call_sid.strip(), None)

    def reset(self) -> None:
        with self._lock:
            self._sessions.clear()


_store = IvrLanguageSessionStore()


def get_session_store() -> IvrLanguageSessionStore:
    return _store


def reset_session_store() -> None:
    _store.reset()


def set_language(call_sid: str, language: str) -> None:
    get_session_store().set_language(call_sid, language)


def get_language(call_sid: str) -> Optional[str]:
    return get_session_store().get_language(call_sid)


def has_language(call_sid: str) -> bool:
    return get_session_store().has_language(call_sid)


def get_transcription(call_sid: str) -> Optional[str]:
    return get_session_store().get_transcription(call_sid)


def get_conversation_id(call_sid: str) -> Optional[str]:
    return get_session_store().get_conversation_id(call_sid)


def clear_session(call_sid: str) -> None:
    get_session_store().clear_session(call_sid)
