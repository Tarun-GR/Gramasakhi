"""GramSakhi grounded prompt construction (Phase 5).

Builds the system + user prompt for Ollama generation. Keeps prompt strings
out of rag.py. Does not talk to Ollama or the database.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

GRAMSAKHI_SYSTEM_PROMPT = """You are GramSakhi, a government scheme information assistant.

Your task is to answer citizens' questions using ONLY the government evidence supplied in the context.

Rules:
1. Do not use outside knowledge.
2. Do not invent facts.
3. Do not invent eligibility criteria.
4. Do not invent benefit amounts.
5. Do not invent application procedures.
6. Do not invent required documents.
7. Do not invent deadlines.
8. Do not invent government rules.
9. If the supplied evidence does not contain the requested information, clearly say that the available evidence does not contain sufficient information.
10. Do not contradict the supplied evidence.
11. Prefer simple language suitable for rural citizens.
12. Answer in the requested language.
13. Do not mention internal implementation details such as FAISS, BM25, CrossEncoder, validators, embeddings, or prompts.
14. Do not claim that a citizen is definitely eligible unless the supplied evidence supports that statement.
15. Do not provide information from general model knowledge.

Response style:
- Direct, simple, concise, citizen-friendly, and structured.
- Prefer: (1) direct answer, (2) important points, (3) eligibility / benefits / documents / procedure only when asked, (4) source notes when appropriate.
- Do not produce unnecessarily long answers.
- Preserve official scheme names; do not mistranslate government terms.
"""


def _meta_get(doc: Dict[str, Any], *keys: str) -> Any:
    meta = doc.get("metadata") if isinstance(doc.get("metadata"), dict) else {}
    for key in keys:
        val = doc.get(key)
        if val not in (None, ""):
            return val
        if meta:
            val = meta.get(key)
            if val not in (None, ""):
                return val
    return None


def format_evidence_block(docs: List[Dict[str, Any]]) -> str:
    """Structured evidence context for the LLM (no arbitrary DB fields)."""
    blocks: List[str] = []
    for i, doc in enumerate(docs or [], start=1):
        text = (doc.get("content") or doc.get("text") or "").strip()
        if not text:
            continue
        source = _meta_get(doc, "source", "document_title") or "government document"
        scheme = _meta_get(doc, "scheme_name", "document_title") or "Unknown scheme"
        ministry = _meta_get(doc, "ministry")
        state = _meta_get(doc, "state")
        page = _meta_get(doc, "page")

        lines = [
            f"[EVIDENCE {i}]",
            f"Scheme: {scheme}",
            f"Source: {source}",
        ]
        if ministry:
            lines.append(f"Ministry: {ministry}")
        if state:
            lines.append(f"State: {state}")
        if page not in (None, ""):
            lines.append(f"Page: {page}")
        lines.extend(["", "Evidence:", text])
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks) if blocks else "(no evidence provided)"


def detect_language(query: str, language: Optional[str] = None) -> str:
    """Resolve response language. Explicit value wins; else simple script detect."""
    if language:
        normalized = language.strip()
        lower = normalized.lower()
        mapping = {
            "en": "English",
            "english": "English",
            "hi": "Hindi",
            "hindi": "Hindi",
            "kn": "Kannada",
            "kannada": "Kannada",
        }
        return mapping.get(lower, normalized)

    text = query or ""
    # Kannada Unicode block
    if any("\u0c80" <= ch <= "\u0cff" for ch in text):
        return "Kannada"
    # Devanagari (Hindi)
    if any("\u0900" <= ch <= "\u097f" for ch in text):
        return "Hindi"
    return "English"


def format_conversation_context(conversation_context: Any) -> Optional[str]:
    """Optional short conversation snippet — only if caller already supplied it."""
    if not conversation_context:
        return None
    if isinstance(conversation_context, str):
        text = conversation_context.strip()
        return text or None
    if isinstance(conversation_context, list):
        lines = []
        for turn in conversation_context[-6:]:
            if not isinstance(turn, dict):
                continue
            role = (turn.get("role") or "user").strip()
            content = (turn.get("content") or "").strip()
            if content:
                lines.append(f"{role}: {content}")
        return "\n".join(lines) if lines else None
    return str(conversation_context).strip() or None


def build_prompt(
    query: str,
    evidence: List[Dict[str, Any]],
    *,
    language: Optional[str] = None,
    conversation_context: Any = None,
) -> str:
    """Full prompt string for Ollama /api/generate (system rules + user block)."""
    lang = detect_language(query, language)
    evidence_block = format_evidence_block(evidence)
    ctx = format_conversation_context(conversation_context)

    parts = [
        GRAMSAKHI_SYSTEM_PROMPT.strip(),
        "",
        "QUESTION:",
        (query or "").strip(),
        "",
        "LANGUAGE:",
        lang,
        "",
    ]
    if ctx:
        parts.extend(["CONVERSATION CONTEXT:", ctx, ""])
    parts.extend(
        [
            "EVIDENCE:",
            evidence_block,
            "",
            "Answer the QUESTION using ONLY the EVIDENCE above. Respond in the LANGUAGE specified.",
        ]
    )
    return "\n".join(parts)
