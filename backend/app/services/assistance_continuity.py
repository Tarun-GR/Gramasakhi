"""Stage 6C-3 — citizen assistance continuity and resume.

Persists structured assistance metadata inside assistant message sources_json
(internal markers). Restores metadata on conversation reload without RAG/LLM.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Sequence

from app.services.eligibility_questioning import (
    SESSION_MARKER,
    EligibilitySession,
    load_session_from_messages,
    session_outcome_from,
)

ASSISTANCE_META_MARKER = "_gramsakhi_assistance_meta"

_INTERNAL_MARKERS = frozenset({SESSION_MARKER, ASSISTANCE_META_MARKER})


def _sources_from_message(msg: Any) -> List[Any]:
    raw_json = getattr(msg, "sources_json", None)
    if raw_json is None and isinstance(msg, dict):
        sources = msg.get("sources") or []
    else:
        try:
            sources = json.loads(raw_json) if raw_json else []
        except Exception:
            sources = []
    return sources if isinstance(sources, list) else []


def strip_internal_sources_for_api(sources: Optional[List[Any]]) -> List[Any]:
    """Remove internal continuity markers before exposing sources to clients."""
    return [
        s
        for s in (sources or [])
        if not (isinstance(s, dict) and s.get("_internal") in _INTERNAL_MARKERS)
    ]


def build_message_assistance_meta(
    *,
    citizen_intent: Optional[str] = None,
    assistance_mode: Optional[str] = None,
    detected_scheme: Optional[str] = None,
    comparison_schemes: Optional[List[str]] = None,
    eligibility_criteria: Optional[Dict[str, Any]] = None,
    required_information: Optional[List[str]] = None,
    missing_information: Optional[List[str]] = None,
    eligibility_status: Optional[str] = None,
    eligibility_evaluation: Optional[Dict[str, Any]] = None,
    eligibility_explanation: Optional[Dict[str, Any]] = None,
    scheme_guidance: Optional[Dict[str, Any]] = None,
    action_plan: Optional[Dict[str, Any]] = None,
    eligibility_session_active: Optional[bool] = None,
    eligibility_question: Optional[str] = None,
    eligibility_completed: Optional[bool] = None,
    known_information: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Build a serializable metadata blob for one assistant turn."""
    meta: Dict[str, Any] = {}
    if citizen_intent:
        meta["citizen_intent"] = citizen_intent
    if assistance_mode:
        meta["assistance_mode"] = assistance_mode
    if detected_scheme:
        meta["detected_scheme"] = detected_scheme
    if comparison_schemes:
        meta["comparison_schemes"] = list(comparison_schemes)
    if eligibility_criteria:
        meta["eligibility_criteria"] = eligibility_criteria
    if required_information:
        meta["required_information"] = list(required_information)
    if missing_information:
        meta["missing_information"] = list(missing_information)
    if eligibility_status:
        meta["eligibility_status"] = eligibility_status
    if eligibility_evaluation:
        meta["eligibility_evaluation"] = eligibility_evaluation
    if eligibility_explanation:
        meta["eligibility_explanation"] = eligibility_explanation
    if scheme_guidance:
        meta["scheme_guidance"] = scheme_guidance
    if action_plan:
        meta["action_plan"] = action_plan
    if eligibility_session_active is not None:
        meta["eligibility_session_active"] = bool(eligibility_session_active)
    if eligibility_question:
        meta["eligibility_question"] = eligibility_question
    if eligibility_completed is not None:
        meta["eligibility_completed"] = bool(eligibility_completed)
    if known_information:
        meta["known_information"] = dict(known_information)
    return meta or None


def embed_assistance_meta_in_sources(
    sources: Optional[List[Any]],
    meta: Optional[Dict[str, Any]],
) -> List[Any]:
    """Attach assistance metadata marker to sources list (stored in DB)."""
    out = [
        s
        for s in (sources or [])
        if not (isinstance(s, dict) and s.get("_internal") == ASSISTANCE_META_MARKER)
    ]
    if meta:
        out.append({"_internal": ASSISTANCE_META_MARKER, "meta": meta})
    return out


def extract_assistance_meta_from_sources(sources: Optional[List[Any]]) -> Optional[Dict[str, Any]]:
    if not isinstance(sources, list):
        return None
    for item in sources:
        if isinstance(item, dict) and item.get("_internal") == ASSISTANCE_META_MARKER:
            payload = item.get("meta")
            if isinstance(payload, dict):
                return dict(payload)
    return None


def extract_assistance_meta_from_message(msg: Any) -> Optional[Dict[str, Any]]:
    role = getattr(msg, "role", None) or (msg.get("role") if isinstance(msg, dict) else None)
    if role != "assistant":
        return None
    return extract_assistance_meta_from_sources(_sources_from_message(msg))


def extract_latest_assistance_meta(messages: Sequence[Any]) -> Optional[Dict[str, Any]]:
    for msg in reversed(list(messages or [])):
        meta = extract_assistance_meta_from_message(msg)
        if meta:
            return meta
    return None


def _safe_session_for_conversation(
    messages: Sequence[Any],
    conversation_id: str,
) -> Optional[EligibilitySession]:
    session = load_session_from_messages(messages)
    if session is None:
        return None
    if str(session.conversation_id) != str(conversation_id):
        return None
    return session


def build_conversation_assistance_state(
    *,
    conversation_id: str,
    active_scheme_context: Optional[str],
    messages: Sequence[Any],
) -> Optional[Dict[str, Any]]:
    """Derive conversation-scoped assistance state for history reload (read-only)."""
    session = _safe_session_for_conversation(messages, conversation_id)
    latest_meta = extract_latest_assistance_meta(messages) or {}

    state: Dict[str, Any] = {}

    scheme = active_scheme_context or (session.active_scheme if session else None) or latest_meta.get(
        "detected_scheme"
    )
    if scheme:
        state["active_scheme_context"] = scheme
        state["detected_scheme"] = scheme

    if session:
        state.update(session_outcome_from(session))
        if session.evaluation_result:
            state["eligibility_status"] = session.evaluation_result.get("status")
            state["eligibility_evaluation"] = session.evaluation_result
    else:
        for key in (
            "eligibility_session_active",
            "eligibility_question",
            "eligibility_completed",
            "known_information",
            "missing_information",
            "eligibility_status",
            "eligibility_evaluation",
        ):
            if latest_meta.get(key) is not None:
                state[key] = latest_meta[key]

    for key in (
        "citizen_intent",
        "assistance_mode",
        "scheme_guidance",
        "action_plan",
        "eligibility_explanation",
        "required_information",
        "eligibility_criteria",
    ):
        if latest_meta.get(key) is not None:
            state[key] = latest_meta[key]

    return state or None


def sanitize_assistance_state_for_api(
    state: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Coerce stored assistance state into schema-safe shapes for history responses."""
    if not state or not isinstance(state, dict):
        return None
    out: Dict[str, Any] = {}
    for key in (
        "active_scheme_context",
        "detected_scheme",
        "citizen_intent",
        "assistance_mode",
        "eligibility_question",
        "eligibility_status",
    ):
        val = state.get(key)
        if isinstance(val, str) and val.strip():
            out[key] = val.strip()
    for key in ("eligibility_session_active", "eligibility_completed"):
        if state.get(key) is not None:
            out[key] = bool(state[key])
    for key in ("missing_information", "required_information"):
        val = state.get(key)
        if isinstance(val, list):
            out[key] = [str(x) for x in val if x is not None]
        elif isinstance(val, str) and val.strip():
            out[key] = [val.strip()]
    for key in (
        "known_information",
        "eligibility_evaluation",
        "eligibility_explanation",
        "scheme_guidance",
        "action_plan",
        "eligibility_criteria",
    ):
        val = state.get(key)
        if isinstance(val, dict):
            out[key] = val
    return out or None
