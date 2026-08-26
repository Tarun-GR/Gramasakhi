"""IVR-A5 session termination — clear volatile CallSid state, preserve conversation in DB."""

from __future__ import annotations

from app.services.ivr.audio_token_store import get_audio_token_store
from app.services.ivr.language_session import get_session_store


def terminate_ivr_session(call_sid: str) -> None:
    """Remove in-memory IVR session and revoke temporary audio; DB conversation remains."""
    sid = (call_sid or "").strip()
    if not sid:
        return
    store = get_session_store()
    session = store.peek_session(sid)
    token = getattr(session, "active_audio_token", None) if session else None
    if token:
        get_audio_token_store().delete(token)
    get_audio_token_store().revoke_for_call_sid(sid)
    store.clear_session(sid)
