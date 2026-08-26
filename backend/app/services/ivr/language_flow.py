"""IVR-A1 language menu flow — normalize Exotel digits and build Gather responses."""

from __future__ import annotations

import logging
import re
from typing import Optional

from app.schemas.ivr import GatherPromptText, IvrGatherResponse
from app.services.ivr.constants import (
    DIGIT_TO_LANGUAGE,
    GATHER_FINISH_ON_KEY,
    GATHER_INPUT_TIMEOUT_SECONDS,
    GATHER_MAX_INPUT_DIGITS,
    GATHER_REPEAT_MENU,
    GOODBYE_PROMPT,
    INVALID_PROMPT,
    LANGUAGE_CONFIRMATION,
    MAX_RETRY_ATTEMPTS,
    MENU_PROMPT,
)
from app.services.ivr.call_sid_validation import mask_call_sid
from app.services.ivr.language_session import get_session_store
from app.services.ivr.call_state import IvrCallState, get_state, set_state

_logger = logging.getLogger("gramsakhi.ivr")

# Language may only be (re)selected before the caller is inside an active turn.
_LANGUAGE_SELECTABLE_STATES = frozenset(
    {IvrCallState.LANGUAGE_SELECTION, IvrCallState.READY_FOR_INPUT}
)


def mask_caller_phone(phone: Optional[str]) -> str:
    """Mask caller identity for logs — never emit the full number."""
    raw = (phone or "").strip()
    if not raw:
        return "unknown"
    digits = re.sub(r"\D", "", raw)
    if len(digits) <= 3:
        return "***"
    if len(digits) >= 10:
        return f"+{digits[:2]}{'*' * (len(digits) - 5)}{digits[-3:]}"
    return f"{'*' * (len(digits) - 3)}{digits[-3:]}"


def normalize_digits(raw: Optional[str]) -> Optional[str]:
    """Strip Exotel quoting/whitespace from the digits query parameter."""
    if raw is None:
        return None
    cleaned = raw.strip().strip('"').strip("'").strip()
    return cleaned if cleaned else None


def _menu_gather(*, repeat_text: Optional[str] = None) -> IvrGatherResponse:
    repeat_prompt = GatherPromptText(text=repeat_text or MENU_PROMPT)
    return IvrGatherResponse(
        gather_prompt=GatherPromptText(text=MENU_PROMPT),
        max_input_digits=GATHER_MAX_INPUT_DIGITS,
        finish_on_key=GATHER_FINISH_ON_KEY,
        input_timeout=GATHER_INPUT_TIMEOUT_SECONDS,
        repeat_menu=GATHER_REPEAT_MENU,
        repeat_gather_prompt=repeat_prompt,
    )


def _retry_gather(prompt_text: str) -> IvrGatherResponse:
    return IvrGatherResponse(
        gather_prompt=GatherPromptText(text=prompt_text),
        max_input_digits=GATHER_MAX_INPUT_DIGITS,
        finish_on_key=GATHER_FINISH_ON_KEY,
        input_timeout=GATHER_INPUT_TIMEOUT_SECONDS,
        repeat_menu=GATHER_REPEAT_MENU,
        repeat_gather_prompt=GatherPromptText(text=prompt_text),
    )


def _terminal_gather(prompt_text: str) -> IvrGatherResponse:
    """Play a final prompt; Exotel Flow should transition to Hangup afterward."""
    return IvrGatherResponse(gather_prompt=GatherPromptText(text=prompt_text))


def build_language_gather_response(
    *,
    call_sid: str,
    digits: Optional[str],
    caller_phone: Optional[str] = None,
) -> IvrGatherResponse:
    store = get_session_store()
    session = store.get_session(call_sid)

    _logger.info(
        "ivr_language call_sid=%s caller=%s has_digits=%s",
        mask_call_sid(call_sid),
        mask_caller_phone(caller_phone),
        digits is not None and normalize_digits(digits) is not None,
    )

    current_state = get_state(call_sid)
    if session.language and current_state not in _LANGUAGE_SELECTABLE_STATES:
        # A caller (or provider retry) cannot reset the language mid-turn; the
        # A5 state machine owns the call after language selection.
        _logger.warning(
            "ivr_language_reentry_blocked call_sid=%s state=%s",
            mask_call_sid(call_sid),
            current_state.value,
        )
        return _terminal_gather(LANGUAGE_CONFIRMATION[session.language])

    normalized = normalize_digits(digits)

    if normalized is None:
        if not session.menu_shown:
            session.menu_shown = True
            return _menu_gather()
        session.no_input_attempts += 1
        if session.no_input_attempts > MAX_RETRY_ATTEMPTS:
            return _terminal_gather(GOODBYE_PROMPT)
        return _retry_gather(MENU_PROMPT)

    language = DIGIT_TO_LANGUAGE.get(normalized)
    if language is None:
        session.invalid_attempts += 1
        if session.invalid_attempts > MAX_RETRY_ATTEMPTS:
            return _terminal_gather(GOODBYE_PROMPT)
        return _retry_gather(INVALID_PROMPT)

    store.set_language(call_sid, language)
    set_state(call_sid, IvrCallState.READY_FOR_INPUT)
    return _terminal_gather(LANGUAGE_CONFIRMATION[language])
