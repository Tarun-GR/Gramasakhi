"""Query rewriting for conversational follow-ups (Phase 6).

Turns contextual questions into standalone retrieval queries.
Does NOT answer the question. Does NOT replace the Evidence Validator.
"""

from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.core.config import settings

logger = logging.getLogger("gramsakhi.query_rewriter")

# Known scheme aliases (longest match first). Expand as catalog grows.
_SCHEME_ALIASES: Tuple[Tuple[str, str], ...] = (
    ("pmay-g", "PMAY-G"),
    ("pmay g", "PMAY-G"),
    ("pradhan mantri awaas yojana gramin", "PMAY-G"),
    ("pradhan mantri awas yojana gramin", "PMAY-G"),
    ("pmay urban", "PMAY-U"),
    ("pmay-u", "PMAY-U"),
    ("pm-kisan", "PM-KISAN"),
    ("pm kisan", "PM-KISAN"),
    ("pmkisan", "PM-KISAN"),
    ("kisan samman nidhi", "PM-KISAN"),
    ("ayushman bharat", "Ayushman Bharat PM-JAY"),
    ("pm-jay", "Ayushman Bharat PM-JAY"),
    ("pmjay", "Ayushman Bharat PM-JAY"),
    ("mgnrega", "MGNREGA"),
    ("nrega", "MGNREGA"),
)

_FOLLOWUP_HINTS = re.compile(
    r"\b("
    r"who|what|when|where|how|which|"
    r"eligible|eligibility|benefit|benefits|document|documents|"
    r"apply|application|required|requirement|penalty|penalties|"
    r"amount|installment|criteria|procedure|process|"
    r"this|that|it|these|those|the scheme|this scheme|that scheme"
    r")\b",
    re.IGNORECASE,
)

_PRONOUN_SCHEME = re.compile(
    r"\b(this scheme|that scheme|the scheme|this program|that program)\b",
    re.IGNORECASE,
)


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def extract_scheme_mentions(text: str) -> List[str]:
    """Return canonical scheme names mentioned in text (order preserved)."""
    lowered = (text or "").lower()
    found: List[str] = []
    for alias, canonical in _SCHEME_ALIASES:
        if alias in lowered and canonical not in found:
            found.append(canonical)
    return found


def history_active_scheme(history: Sequence[Dict[str, Any]]) -> Optional[str]:
    """Most recent scheme mentioned in conversation history (user turns preferred)."""
    for turn in reversed(list(history or [])):
        role = (turn.get("role") or "").lower()
        content = turn.get("content") or ""
        mentions = extract_scheme_mentions(content)
        if mentions:
            # Prefer user-stated schemes
            if role == "user":
                return mentions[0]
            return mentions[0]
    return None


def is_standalone_query(query: str) -> bool:
    """True when the query already names a clear scheme/entity."""
    return bool(extract_scheme_mentions(query))


def _looks_like_followup(query: str) -> bool:
    q = _normalize(query)
    if not q:
        return False
    if is_standalone_query(q):
        return False
    if _FOLLOWUP_HINTS.search(q):
        return True
    # Short questions without a scheme are usually follow-ups in context
    return len(q.split()) <= 8


def _heuristic_rewrite(
    current_query: str,
    conversation_history: Sequence[Dict[str, Any]],
) -> str:
    original = _normalize(current_query)
    if not original:
        return original

    if is_standalone_query(original):
        return original

    scheme = history_active_scheme(conversation_history)
    if not scheme:
        return original

    if not _looks_like_followup(original):
        return original

    # Replace vague scheme references
    if _PRONOUN_SCHEME.search(original):
        return _PRONOUN_SCHEME.sub(scheme, original)

    # Avoid double-appending
    if scheme.lower() in original.lower():
        return original

    # Natural phrasing for common intents
    lower = original.lower().rstrip("?")
    if re.search(r"\bwho is eligible\b", lower):
        return f"Who is eligible for {scheme}?"
    if re.search(r"\beligibility\b", lower) and "for " not in lower:
        return f"What is the eligibility for {scheme}?"
    if re.search(r"\b(what are the )?benefits\b", lower):
        return f"What are the benefits of {scheme}?"
    if re.search(r"\b(what )?documents?\b", lower) or re.search(
        r"\bdocuments? (are )?(needed|required)\b", lower
    ):
        return f"What documents are needed for {scheme}?"
    if re.search(r"\bhow (do i|to) apply\b", lower):
        return f"How do I apply for {scheme}?"

    # Generic: append scheme context
    if original.endswith("?"):
        return f"{original[:-1].rstrip()} for {scheme}?"
    return f"{original} for {scheme}"


def _ollama_rewrite(
    current_query: str,
    conversation_history: Sequence[Dict[str, Any]],
    language: Optional[str],
) -> Optional[str]:
    """Optional Ollama rewrite. Returns None on any failure."""
    if not settings.QUERY_REWRITE_USE_OLLAMA:
        return None

    from app.services.llm_service import get_llm_model, get_ollama_base_url

    hist_lines = []
    for turn in list(conversation_history or [])[- settings.CONVERSATION_HISTORY_LIMIT :]:
        role = turn.get("role") or "user"
        content = (turn.get("content") or "").strip()
        if content:
            hist_lines.append(f"{role}: {content}")
    history_block = "\n".join(hist_lines) if hist_lines else "(none)"

    prompt = (
        "Rewrite the citizen's CURRENT question into a standalone government-scheme "
        "search query using conversation history only to resolve references.\n"
        "Rules:\n"
        "- Output ONLY the rewritten query text.\n"
        "- Do not answer the question.\n"
        "- Do not invent schemes or facts.\n"
        "- If the current question already names a scheme, keep it (do not replace with a previous scheme).\n"
        "- If no rewrite is needed, output the current question unchanged.\n"
        f"Language hint: {language or 'auto'}\n\n"
        f"HISTORY:\n{history_block}\n\n"
        f"CURRENT:\n{current_query}\n\n"
        "REWRITTEN QUERY:"
    )

    url = f"{get_ollama_base_url()}/api/generate"
    payload = json.dumps(
        {
            "model": get_llm_model(),
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.0, "num_predict": 64},
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        url, data=payload, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(
            req, timeout=float(settings.QUERY_REWRITE_TIMEOUT_SECONDS)
        ) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        text = (data.get("response") or "").strip()
        # Strip wrappers
        for prefix in ("Rewritten query:", "REWRITTEN QUERY:", "Query:"):
            if text.lower().startswith(prefix.lower()):
                text = text[len(prefix) :].strip()
        text = text.strip().strip('"').strip("'")
        if not text or "\n" in text:
            # Multi-line / empty → reject
            first = text.splitlines()[0].strip() if text else ""
            return first or None
        return text
    except Exception as e:  # noqa: BLE001
        logger.warning("Query rewrite Ollama failed: %s", type(e).__name__)
        return None


def rewrite_query(
    current_query: str,
    conversation_history: Optional[Sequence[Dict[str, Any]]] = None,
    language: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Rewrite a contextual question into a standalone retrieval query.

    Returns:
        {
          "original_query": str,
          "rewritten_query": str,
          "was_rewritten": bool,
          "method": "heuristic" | "ollama" | "passthrough" | "fallback",
          "active_scheme": optional str,
        }

    On rewriter failure: rewritten_query == original_query.
    """
    original = _normalize(current_query)
    history = list(conversation_history or [])
    scheme = history_active_scheme(history)

    if not original:
        return {
            "original_query": original,
            "rewritten_query": original,
            "was_rewritten": False,
            "method": "passthrough",
            "active_scheme": scheme,
        }

    # Explicit new scheme in the current turn wins — never force previous scheme
    if is_standalone_query(original):
        mentions = extract_scheme_mentions(original)
        return {
            "original_query": original,
            "rewritten_query": original,
            "was_rewritten": False,
            "method": "passthrough",
            "active_scheme": mentions[0] if mentions else scheme,
        }

    try:
        ollama_out = _ollama_rewrite(original, history, language)
        if ollama_out:
            # Guard: do not let Ollama swap in an unrelated prior scheme when
            # current already had none but result invents something odd — prefer heuristic check
            heuristic = _heuristic_rewrite(original, history)
            # If Ollama dropped the resolved scheme that heuristic found, prefer heuristic
            if scheme and scheme.lower() not in ollama_out.lower() and scheme.lower() in heuristic.lower():
                rewritten = heuristic
                method = "heuristic"
            else:
                rewritten = _normalize(ollama_out)
                method = "ollama"
        else:
            rewritten = _heuristic_rewrite(original, history)
            method = "heuristic" if rewritten != original else "passthrough"
    except Exception as e:  # noqa: BLE001
        logger.warning("Query rewriter failed safely: %s", type(e).__name__)
        return {
            "original_query": original,
            "rewritten_query": original,
            "was_rewritten": False,
            "method": "fallback",
            "active_scheme": scheme,
        }

    if not rewritten:
        rewritten = original
        method = "fallback"

    return {
        "original_query": original,
        "rewritten_query": rewritten,
        "was_rewritten": rewritten != original,
        "method": method,
        "active_scheme": extract_scheme_mentions(rewritten)[0]
        if extract_scheme_mentions(rewritten)
        else scheme,
    }
