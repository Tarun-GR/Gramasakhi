"""Government information provider abstraction (additive layer).

Thin wrappers delegate to existing live_gov_retrieval_service and
myscheme_service implementations. This module defines contracts only.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence

logger = logging.getLogger("gramsakhi.gov_providers")


class ProviderPhaseStatus(str, Enum):
    SKIPPED = "skipped"
    INSUFFICIENT = "insufficient"
    SUFFICIENT = "sufficient"
    ERROR = "error"


@dataclass
class ProviderContext:
    """Shared context for a live acquisition chain run."""

    query: str
    search_query: str
    live_request_id: str
    overall_deadline: float
    per_source_timeout: float
    language: Optional[str] = None
    conversation_context: Any = None
    tried_urls: List[str] = field(default_factory=list)
    ingested: List[Dict[str, Any]] = field(default_factory=list)
    failure_codes: List[str] = field(default_factory=list)
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SchemeCandidate:
    url: str
    scheme_name: Optional[str] = None
    scheme_id: Optional[str] = None
    kind: str = ""
    content: Optional[bytes] = None
    link_text: Optional[str] = None
    meta: Dict[str, Any] = field(default_factory=dict)


@dataclass
class IdentityCheckResult:
    accepted: bool
    reason: Optional[str] = None
    requested_scheme: Optional[str] = None
    candidate_scheme: Optional[str] = None


@dataclass
class ExtractedEvidence:
    """Packaged evidence from a provider. URL discovery alone is not success."""

    ok: bool
    content: str = ""
    sections: Dict[str, str] = field(default_factory=dict)
    source_url: str = ""
    scheme_id: Optional[str] = None
    scheme_name: Optional[str] = None
    document_urls: List[str] = field(default_factory=list)
    reason: Optional[str] = None
    text_chars: int = 0


@dataclass
class ProbeResult:
    evidence_ready: bool = False
    accepted_url: Optional[str] = None
    ingested: List[Dict[str, Any]] = field(default_factory=list)
    index_stats: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ProviderRunResult:
    provider: str
    status: ProviderPhaseStatus
    candidates_found: int = 0
    candidates_accepted: int = 0
    ingested_count: int = 0
    evidence_ready: bool = False
    accepted_url: Optional[str] = None
    failure_codes: List[str] = field(default_factory=list)
    meta: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ChainRunResult:
    evidence_ready: bool
    final_provider: Optional[str]
    provider_results: List[ProviderRunResult] = field(default_factory=list)
    ingested: List[Dict[str, Any]] = field(default_factory=list)
    accepted_url: Optional[str] = None
    failure_codes: List[str] = field(default_factory=list)


def log_provider_event(provider: str, event: str, *, live_request_id: str = "-", **fields: Any) -> None:
    """Structured provider observability — never log secrets."""
    safe = {k: v for k, v in fields.items() if v is not None}
    blocked = {"api_key", "client_secret", "password", "token", "authorization"}
    for key in list(safe.keys()):
        if any(b in key.lower() for b in blocked):
            safe[key] = "[REDACTED]"
    parts = " ".join(f"{k}={v!r}" for k, v in safe.items())
    line = f"{event} provider={provider!r} live_request_id={live_request_id!r} {parts}".strip()
    try:
        print(line, flush=True)
    except UnicodeEncodeError:
        print(line.encode("ascii", "backslashreplace").decode("ascii"), flush=True)
    logger.info("%s provider=%s %s", event, provider, parts)


def extracted_evidence_is_usable(
    evidence: ExtractedEvidence,
    *,
    min_chars: int = 40,
) -> bool:
    """URL-only or empty packaging is never sufficient evidence."""
    if not evidence or not evidence.ok:
        return False
    section_text = " ".join(
        (v or "").strip() for v in (evidence.sections or {}).values() if (v or "").strip()
    )
    blob = (evidence.content or "").strip() or section_text.strip()
    if len(blob) < min_chars:
        return False
    lower = blob.lower()
    # Bare URL with no factual body
    if lower.startswith("http") and len(blob.split()) <= 3 and not section_text:
        return False
    if lower in ("open official website", "visit the official website"):
        return False
    return True


class GovernmentInformationProvider(ABC):
    """Provider contract for staged government information acquisition."""

    name: str
    priority: int = 100

    def supports(self, query: str, *, context: ProviderContext) -> bool:
        return True

    @abstractmethod
    def run(self, context: ProviderContext, *, service: Any = None) -> ProviderRunResult:
        """Execute one provider phase (discover → acquire → ingest delegate)."""

    def discover(self, query: str, *, context: ProviderContext, service: Any = None) -> List[SchemeCandidate]:
        return []

    def resolve_identity(
        self,
        candidate: SchemeCandidate,
        query: str,
        *,
        context: ProviderContext,
        service: Any = None,
    ) -> IdentityCheckResult:
        return IdentityCheckResult(accepted=True)

    def acquire(
        self,
        candidate: SchemeCandidate,
        *,
        context: ProviderContext,
        service: Any = None,
    ) -> Optional[SchemeCandidate]:
        return candidate

    def extract(
        self,
        candidate: SchemeCandidate,
        *,
        query: str,
        context: ProviderContext,
        service: Any = None,
    ) -> ExtractedEvidence:
        return ExtractedEvidence(ok=False, reason="not_implemented")

    def discover_documents(
        self,
        candidate: SchemeCandidate,
        *,
        context: ProviderContext,
        service: Any = None,
    ) -> List[str]:
        return []

    def is_sufficient(
        self,
        query: str,
        *,
        context: ProviderContext,
        probe: ProbeResult,
        service: Any = None,
    ) -> bool:
        return bool(probe and probe.evidence_ready)


def merge_provider_ingested(context: ProviderContext, new_items: Sequence[Dict[str, Any]]) -> None:
    seen = {item.get("source_url") or item.get("url") for item in context.ingested}
    for item in new_items or []:
        key = item.get("source_url") or item.get("url")
        if key and key in seen:
            continue
        context.ingested.append(dict(item))
        if key:
            seen.add(key)
