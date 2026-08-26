"""IVR-A5 authoritative CallSid state machine and turn concurrency guards."""

from __future__ import annotations

import logging
from enum import Enum
from typing import Optional

from app.core.config import settings
from app.services.ivr.language_session import IvrCallSession, get_session_store

logger = logging.getLogger("gramsakhi.ivr.state")


class IvrCallState(str, Enum):
    LANGUAGE_SELECTION = "language_selection"
    READY_FOR_INPUT = "ready_for_input"
    TRANSCRIBING = "transcribing"
    PROCESSING_CHAT = "processing_chat"
    SYNTHESIZING = "synthesizing"
    PLAYING_RESPONSE = "playing_response"
    ASK_CONTINUE = "ask_continue"
    ENDING = "ending"
    ERROR = "error"


class StateTransitionError(Exception):
    def __init__(self, code: str, message: str = "Invalid IVR state transition.") -> None:
        super().__init__(message)
        self.code = code


def _mask_call_sid(call_sid: str) -> str:
    sid = (call_sid or "").strip()
    if len(sid) <= 8:
        return "***"
    return f"{sid[:4]}…{sid[-4:]}"


def get_state(call_sid: str) -> IvrCallState:
    session = get_session_store().get_session(call_sid)
    raw = getattr(session, "state", IvrCallState.LANGUAGE_SELECTION.value)
    try:
        return IvrCallState(raw)
    except ValueError:
        return IvrCallState.LANGUAGE_SELECTION


def set_state(call_sid: str, state: IvrCallState) -> None:
    session = get_session_store().get_session(call_sid)
    previous = get_state(call_sid)
    session.state = state.value
    logger.info(
        "ivr_state call_sid=%s from=%s to=%s turn=%s",
        _mask_call_sid(call_sid),
        previous.value,
        state.value,
        getattr(session, "turn_count", 0),
    )


def require_states(call_sid: str, allowed: set[IvrCallState]) -> IvrCallSession:
    current = get_state(call_sid)
    if current not in allowed:
        raise StateTransitionError(
            "invalid_transition",
            f"CallSid state {current.value} not in {[s.value for s in allowed]}.",
        )
    return get_session_store().get_session(call_sid)


def transition(call_sid: str, to: IvrCallState, *, from_allowed: set[IvrCallState]) -> IvrCallSession:
    require_states(call_sid, from_allowed)
    set_state(call_sid, to)
    return get_session_store().get_session(call_sid)


def assert_turn_available(call_sid: str) -> None:
    session = get_session_store().get_session(call_sid)
    if getattr(session, "turn_in_progress", False):
        raise StateTransitionError("turn_busy", "An IVR turn is already in progress for this CallSid.")


def begin_turn(call_sid: str) -> None:
    assert_turn_available(call_sid)
    session = get_session_store().get_session(call_sid)
    session.turn_in_progress = True


def end_turn(call_sid: str) -> None:
    session = get_session_store().get_session(call_sid)
    session.turn_in_progress = False


def can_accept_question(call_sid: str) -> tuple[bool, Optional[str]]:
    session = get_session_store().get_session(call_sid)
    max_turns = int(getattr(settings, "IVR_MAX_TURNS", 10))
    if int(getattr(session, "turn_count", 0)) >= max_turns:
        return False, "turn_limit"
    return True, None


def increment_turn(call_sid: str) -> int:
    session = get_session_store().get_session(call_sid)
    session.turn_count = int(getattr(session, "turn_count", 0)) + 1
    return session.turn_count


def reset_turn_counters(call_sid: str) -> None:
    session = get_session_store().get_session(call_sid)
    session.turn_count = 0
    session.turn_in_progress = False
    session.silence_attempts = 0
    session.continue_invalid_attempts = 0
    session.continue_no_input_attempts = 0
    session.chat_failure_attempts = 0
    session.tts_failure_attempts = 0
    session.stt_attempts = 0
