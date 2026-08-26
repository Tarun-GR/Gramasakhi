"""IVR telephony adapter — thin layer over Exotel Gather (A1: language selection)."""

from app.services.ivr.language_session import (
    clear_session,
    get_language,
    get_session_store,
    reset_session_store,
    set_language,
)

__all__ = [
    "clear_session",
    "get_language",
    "get_session_store",
    "reset_session_store",
    "set_language",
]
