"""IVR-A5 continue/end DTMF flow after response playback."""

from __future__ import annotations

import logging
from typing import Optional

from app.schemas.ivr import GatherPromptText, IvrContinueResponse
from app.services.ivr.call_state import (
    IvrCallState,
    get_state,
    set_state,
    transition,
)
from app.services.ivr.constants import (
    CONTINUE_GOODBYE_PROMPT,
    CONTINUE_INVALID_PROMPT,
    CONTINUE_MENU_PROMPT,
    DIGIT_CONTINUE,
    DIGIT_END,
    MAX_CONTINUE_RETRY_ATTEMPTS,
    MAX_RETRY_ATTEMPTS,
    TURN_LIMIT_PROMPT,
)
from app.services.ivr.language_flow import normalize_digits
from app.services.ivr.language_session import get_session_store
from app.services.ivr.session_cleanup import terminate_ivr_session

logger = logging.getLogger("gramsakhi.ivr.continue")


def _menu_response(*, end_call: bool = False, continue_loop: bool = False) -> IvrContinueResponse:
    return IvrContinueResponse(
        gather_prompt=GatherPromptText(text=CONTINUE_MENU_PROMPT),
        end_call=end_call,
        continue_loop=continue_loop,
        success=True,
    )


def _terminal_response(text: str, *, end_call: bool = True) -> IvrContinueResponse:
    return IvrContinueResponse(
        gather_prompt=GatherPromptText(text=text),
        end_call=end_call,
        continue_loop=False,
        success=not end_call,
    )


def build_continue_response(
    *,
    call_sid: str,
    digits: Optional[str] = None,
) -> IvrContinueResponse:
    store = get_session_store()
    session = store.get_session(call_sid)
    current = get_state(call_sid)

    if current == IvrCallState.PLAYING_RESPONSE:
        transition(call_sid, IvrCallState.ASK_CONTINUE, from_allowed={IvrCallState.PLAYING_RESPONSE})
        current = IvrCallState.ASK_CONTINUE

    if current == IvrCallState.ENDING:
        return _terminal_response(CONTINUE_GOODBYE_PROMPT, end_call=True)

    if current not in {IvrCallState.ASK_CONTINUE, IvrCallState.READY_FOR_INPUT}:
        logger.warning(
            "ivr_continue_invalid_state call_sid=%s state=%s",
            call_sid[:4] + "…" if len(call_sid) > 8 else "***",
            current.value,
        )
        return IvrContinueResponse(
            gather_prompt=GatherPromptText(text=CONTINUE_INVALID_PROMPT),
            end_call=False,
            continue_loop=False,
            success=False,
        )

    normalized = normalize_digits(digits)
    if normalized is None:
        session.continue_no_input_attempts += 1
        if session.continue_no_input_attempts > MAX_RETRY_ATTEMPTS:
            set_state(call_sid, IvrCallState.ENDING)
            terminate_ivr_session(call_sid)
            return _terminal_response(CONTINUE_GOODBYE_PROMPT, end_call=True)
        set_state(call_sid, IvrCallState.ASK_CONTINUE)
        return _menu_response()

    if normalized == DIGIT_CONTINUE:
        from app.services.ivr.call_state import can_accept_question

        ok, reason = can_accept_question(call_sid)
        if not ok and reason == "turn_limit":
            set_state(call_sid, IvrCallState.ENDING)
            terminate_ivr_session(call_sid)
            return _terminal_response(TURN_LIMIT_PROMPT, end_call=True)

        session.continue_invalid_attempts = 0
        session.continue_no_input_attempts = 0
        session.silence_attempts = 0
        session.stt_attempts = 0
        session.chat_failure_attempts = 0
        session.tts_failure_attempts = 0
        session.turn_in_progress = False
        set_state(call_sid, IvrCallState.READY_FOR_INPUT)
        return IvrContinueResponse(
            gather_prompt=GatherPromptText(text="Please ask your question after the tone."),
            end_call=False,
            continue_loop=True,
            success=True,
        )

    if normalized == DIGIT_END:
        set_state(call_sid, IvrCallState.ENDING)
        terminate_ivr_session(call_sid)
        return _terminal_response(CONTINUE_GOODBYE_PROMPT, end_call=True)

    session.continue_invalid_attempts += 1
    if session.continue_invalid_attempts > MAX_CONTINUE_RETRY_ATTEMPTS:
        set_state(call_sid, IvrCallState.ENDING)
        terminate_ivr_session(call_sid)
        return _terminal_response(CONTINUE_GOODBYE_PROMPT, end_call=True)

    set_state(call_sid, IvrCallState.ASK_CONTINUE)
    return IvrContinueResponse(
        gather_prompt=GatherPromptText(text=CONTINUE_INVALID_PROMPT),
        end_call=False,
        continue_loop=False,
        success=False,
    )
