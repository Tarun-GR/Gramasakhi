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
    ('pmay-g', 'PMAY-G'),
    ('pmay g', 'PMAY-G'),
    ('pradhan mantri awaas yojana gramin', 'PMAY-G'),
    ('pradhan mantri awas yojana gramin', 'PMAY-G'),
    ('pmay urban', 'PMAY-U'),
    ('pmay-u', 'PMAY-U'),
    ('pm-kisan', 'PM-KISAN'),
    ('pm kisan', 'PM-KISAN'),
    ('pmkisan', 'PM-KISAN'),
    ('kisan samman nidhi', 'PM-KISAN'),
    ('pradhan mantri kisan samman nidhi', 'PM-KISAN'),
    ('pm-sby', 'PM-SBY'),
    ('pm sby', 'PM-SBY'),
    ('pmsby', 'PM-SBY'),
    ('pradhan mantri suraksha bima', 'PM-SBY'),
    ('suraksha bima yojana', 'PM-SBY'),
    ('ಪಿಎಂ-ಕಿಸಾನ್', 'PM-KISAN'),
    ('ಪಿಎಂ ಕಿಸಾನ್', 'PM-KISAN'),
    ('ಪಿಎಂಕಿಸಾನ್', 'PM-KISAN'),
    ('पीएम-किसान', 'PM-KISAN'),
    ('पीएम किसान', 'PM-KISAN'),
    ('udyogini scheme', 'Udyogini'),
    ('udyogini yojana', 'Udyogini'),
    ('udyogini yojane', 'Udyogini'),
    ('udyogini', 'Udyogini'),
    ('ಉದ್ಯೋಗಿನಿ ಯೋಜನೆ', 'Udyogini'),
    ('ಉದ್ಯೋಗಿನಿ', 'Udyogini'),
    ('उद्योगिनी योजना', 'Udyogini'),
    ('उद्योगिनी', 'Udyogini'),
    ('pmfby', 'PMFBY'),
    ('pradhan mantri fasal bima', 'PMFBY'),
    ('fasal bima', 'PMFBY'),
    ('gruha lakshmi', 'Gruha Lakshmi'),
    ('guruha lakshmi', 'Gruha Lakshmi'),
    ('ಗೃಹ ಲಕ್ಷ್ಮೀ', 'Gruha Lakshmi'),
    ('ಗೃಹ ಲಕ್ಷ್ಮಿ', 'Gruha Lakshmi'),
    ('गृह लक्ष्मी', 'Gruha Lakshmi'),
    ('gruha jyoti', 'Gruha Jyoti'),
    ('gruha jyothi', 'Gruha Jyoti'),
    ('guruha jyoti', 'Gruha Jyoti'),
    ('guruha jyothi', 'Gruha Jyoti'),
    ('ಗೃಹ ಜ್ಯೋತಿ', 'Gruha Jyoti'),
    ('ayushman bharat', 'Ayushman Bharat PM-JAY'),
    ('pm-jay', 'Ayushman Bharat PM-JAY'),
    ('pmjay', 'Ayushman Bharat PM-JAY'),
    ('ಆಯುಷ್ಮಾನ್', 'Ayushman Bharat PM-JAY'),
    ('आयुष्मान', 'Ayushman Bharat PM-JAY'),
    ('mgnrega', 'MGNREGA'),
    ('nrega', 'MGNREGA'),
    ('shakti scheme', 'Shakti'),
    ('shakti yojana', 'Shakti'),
    ('shakti', 'Shakti'),
    ('ಶಕ್ತಿ ಯೋಜನೆ', 'Shakti'),
    ('ಶಕ್ತಿ', 'Shakti'),
    ('शक्ति योजना', 'Shakti'),
    ('शक्ति', 'Shakti'),
)

_FOLLOWUP_HINTS = re.compile(
    r"("
    r"\b("
    r"who|what|when|where|how|which|"
    r"eligible|eligibility|benefit|benefits|document|documents|"
    r"apply|application|required|requirement|penalty|penalties|"
    r"amount|installment|criteria|procedure|process|"
    r"this|that|it|these|those|the scheme|this scheme|that scheme|"
    r"more|details|elaborate"
    r")\b|"
    r"ಅರ್ಹ|ಪ್ರಯೋಜನ|ಅರ್ಜಿ|ದಾಖಲೆ|ಅದಕ್ಕೆ|ಅದರ|ಯಾರು|ಏನು|"
    r"ಇನ್ನಷ್ಟು|ಹೇಳಿ|ಹೆಚ್ಚು|ಬಗ್ಗೆ|"
    r"पात्र|लाभ|आवेदन|दस्तावेज|उसके|इसके|कौन|क्या|और बता"
    r")",
    re.IGNORECASE,
)

# New-topic phrasing without a scheme name must NOT inherit prior scheme.
_NEW_TOPIC_OPENER = re.compile(
    r"^\s*("
    r"tell me about|tell me|explain|describe|information (on|about)|"
    r"what (is|are)|who (is|are)|"
    r".{0,40}\b(bagge heli|bagge helu|ke bare mein|के बारे में)"
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
    raw = text or ""
    lowered = raw.lower()
    # Apply light STT spelling fixes so "Guruha Jyoti" counts as a scheme.
    try:
        from app.services.multilingual_retrieval_service import normalize_stt_artifacts

        lowered = normalize_stt_artifacts(raw).lower()
    except Exception:
        pass
    found: List[str] = []
    for alias, canonical in sorted(_SCHEME_ALIASES, key=lambda x: -len(x[0])):
        if (alias in lowered or alias in raw) and canonical not in found:
            found.append(canonical)
    return found


def history_active_scheme(history: Sequence[Dict[str, Any]]) -> Optional[str]:
    """Most recent scheme mentioned in conversation history (user turns preferred)."""
    for turn in reversed(list(history or [])):
        role = (turn.get("role") or "").lower()
        content = turn.get("content") or ""
        mentions = extract_scheme_mentions(content)
        if mentions:
            return mentions[0]
        if role == "user" and not mentions:
            if is_standalone_query(content):
                try:
                    from app.services.myscheme_service import requested_scheme_identity

                    ident = requested_scheme_identity(content)
                    name = (ident or {}).get("scheme_name") or ""
                    if name:
                        return name
                except Exception:
                    pass
                return None
            if not _looks_like_followup(content):
                return None
    return None


_SCHEME_WORD = re.compile(
    r"(?:\b(?:scheme|yojana|yojane|yojna)\b|ಯೋಜನೆ|योजना)",
    re.IGNORECASE,
)
_STANDALONE_STRIP = re.compile(
    r"\b("
    r"scheme|yojana|yojane|yojna|details|about|tell me|information|info|"
    r"the|a|an|of|for|to|please|can i get|complete|full|more"
    r")\b",
    re.IGNORECASE,
)


def is_standalone_query(query: str) -> bool:
    """True when the query already names a clear scheme/entity.

    Known catalog aliases AND explicit named schemes (e.g. KSCSTE Emeritus
    Scientist Scheme) must override previous conversation scheme context.
    Pronoun follow-ups ('this scheme') still inherit.
    """
    if extract_scheme_mentions(query):
        return True
    q = _normalize(query)
    if not q:
        return False
    if _PRONOUN_SCHEME.search(q):
        return False
    if _SCHEME_WORD.search(q):
        rest = _STANDALONE_STRIP.sub(" ", q)
        rest = re.sub(r"\s+", " ", rest).strip(" ?!.,;:")
        if len(rest) >= 4:
            return True
    return False


def _looks_like_followup(query: str) -> bool:
    q = _normalize(query)
    if not q:
        return False
    if is_standalone_query(q):
        return False
    # "Tell me about farming…" is a new topic, not a PM-KISAN follow-up.
    if _NEW_TOPIC_OPENER.search(q) and not _PRONOUN_SCHEME.search(q):
        # Still allow classic short follow-ups: "What are the benefits?"
        lower = q.lower()
        if re.search(
            r"\b(benefit|benefits|eligible|eligibility|document|documents|"
            r"apply|application|amount|installment|criteria|more|details|"
            r"this scheme|that scheme|the scheme)\b",
            lower,
        ) or re.search(r"ಅರ್ಹ|ಪ್ರಯೋಜನ|ದಾಖಲೆ|ಅದಕ್ಕೆ|ಇನ್ನಷ್ಟು|पात्र|लाभ|उसके|इसके", q):
            return True
        return False
    if _FOLLOWUP_HINTS.search(q):
        return True
    # Do NOT treat every short utterance as a follow-up (topic-shift bug).
    return False


def _heuristic_rewrite(
    current_query: str,
    conversation_history: Sequence[Dict[str, Any]],
) -> str:
    original = _normalize(current_query)
    if not original:
        return original

    if is_standalone_query(original):
        return original

    # New scheme / topic named (incl. STT Latin forms) — never force prior scheme.
    current_schemes = extract_scheme_mentions(original)
    scheme = history_active_scheme(conversation_history)
    if current_schemes and scheme and current_schemes[0] != scheme:
        return original
    if current_schemes:
        return original

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

    # Natural phrasing for common intents (EN + KN/HI → English retrieval form)
    lower = original.lower().rstrip("?")
    if (
        re.search(r"\bwho is eligible\b", lower)
        or "ಅರ್ಹ" in original
        or "पात्र" in original
        or "ಯಾರು ಅರ್ಹ" in original
    ):
        return f"Who is eligible for {scheme}?"
    if (re.search(r"\beligibility\b", lower) and "for " not in lower) or "ಅರ್ಹತೆ" in original:
        return f"What is the eligibility for {scheme}?"
    if (
        re.search(r"\b(what are the )?benefits\b", lower)
        or "ಪ್ರಯೋಜನ" in original
        or "लाभ" in original
    ):
        return f"What are the benefits of {scheme}?"
    if (
        re.search(r"\b(what )?documents?\b", lower)
        or re.search(r"\bdocuments? (are )?(needed|required)\b", lower)
        or "ದಾಖಲೆ" in original
        or "दस्तावेज" in original
        or "दस्तावेज़" in original
    ):
        return f"What documents are needed for {scheme}?"
    if (
        re.search(r"\bhow (do i|to) apply\b", lower)
        or "ಅರ್ಜಿ" in original
        or "आवेदन" in original
    ):
        return f"How do I apply for {scheme}?"

    # Generic: append scheme context (English retrieval-friendly for hybrid index)
    if any(ord(c) > 127 for c in original):
        return f"{scheme} {original}"
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
            "active_scheme": mentions[0] if mentions else None,
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
