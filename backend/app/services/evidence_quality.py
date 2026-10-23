"""Rank retrieved chunks by policy substance vs portal/navigation noise (scheme-agnostic)."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Sequence

_NAV_PHRASES: tuple[str, ...] = (
    "find hospitals",
    "create ayushman",
    "create abha",
    "youtube channel",
    "our youtube",
    "click here",
    "sign in",
    "log in",
    "cookie policy",
    "issued in public interest",
    "fraudulent web portals",
    "only official website",
    "official website of",
    "network error",
    "loading",
    "skip to main",
    "follow us on",
    "download app",
    "am i eligible ?",
    "how to use ayushman app",
)

_POLICY_MARKERS: tuple[str, ...] = (
    "section:\neligibility",
    "section:\nbenefits",
    "section:\napplication",
    "section:\ndocuments",
    "eligibility",
    "eligible",
    "beneficiary",
    "benefit",
    "coverage",
    "installment",
    "guidelines",
    "operational",
    "criteria",
    "who can",
    "shall be",
    "must be",
    "applicant",
    "rupees",
    " crore",
    " lakh",
    " rs.",
    " rs ",
    "percent",
    "per annum",
    "per year",
)


def navigation_heaviness(text: str) -> float:
    """0..1 — higher means more portal chrome / menu noise."""
    body = (text or "").strip().lower()
    if len(body) < 40:
        return 0.0
    hits = sum(1 for p in _NAV_PHRASES if p in body)
    # Title-case menu fragments: "Find Hospitals ABHA Number"
    caps_fragments = len(re.findall(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,4}\b", text or ""))
    nav_signal = hits * 0.12 + min(caps_fragments, 12) * 0.04
    policy_hits = sum(1 for m in _POLICY_MARKERS if m in body)
    if policy_hits >= 3:
        nav_signal *= 0.45
    return min(1.0, nav_signal)


def policy_substance(text: str) -> float:
    """0..1 — higher means more policy/eligibility/benefit language."""
    body = (text or "").strip().lower()
    if len(body) < 40:
        return 0.0
    hits = sum(1 for m in _POLICY_MARKERS if m in body)
    # Reward complete sentences over menu lists
    sentences = len(re.findall(r"[.!?]\s+", body))
    score = min(1.0, hits * 0.08 + sentences * 0.03)
    if "section:" in body:
        score = min(1.0, score + 0.25)
    return score


def evidence_quality_score(doc: Dict[str, Any]) -> float:
    """Higher is better for grounding citizen answers."""
    content = str(doc.get("content") or doc.get("text") or "")
    nav = navigation_heaviness(content)
    pol = policy_substance(content)
    score = pol * 1.4 - nav * 0.9
    src = str(doc.get("source") or doc.get("url") or doc.get("document_url") or "").lower()
    if src.endswith(".pdf") or "/pdf" in src or ".pdf?" in src:
        score += 0.15
    if "myscheme.gov.in/schemes/" in src:
        score += 0.1
    if doc.get("source_aligned") or doc.get("eligibility_boost"):
        score += 0.08
    meta = doc.get("metadata") if isinstance(doc.get("metadata"), dict) else {}
    tags = meta.get("section_tags") or []
    if isinstance(tags, str):
        tags = [tags]
    if tags:
        score += 0.12
    return score


def _retrieval_score(doc: Dict[str, Any]) -> float:
    for key in ("similarity_score", "hybrid_score", "ce_score", "lex_score"):
        val = doc.get(key)
        if val is not None:
            try:
                return float(val)
            except (TypeError, ValueError):
                continue
    return 0.0


def rerank_docs_by_evidence_quality(
    query: str,
    docs: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Stable re-rank: retrieval strength + policy substance, demote navigation shells."""
    _ = query  # reserved for future intent-aware weighting
    items = [dict(d) for d in (docs or [])]
    if len(items) <= 1:
        return items

    def sort_key(d: Dict[str, Any]) -> float:
        q = evidence_quality_score(d)
        r = _retrieval_score(d)
        # Quality dominates tie-breaks; weak vector hits must not stay above policy-rich chunks.
        return q * 2.2 + r * 0.35

    items.sort(key=sort_key, reverse=True)
    return items
