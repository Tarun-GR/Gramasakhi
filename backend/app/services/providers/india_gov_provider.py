"""Thin India.gov.in provider — dynamic discovery via trusted registry + portal search.

Delegates acquisition, PDF handling, ingestion, identity, and sufficiency probing
to existing live_gov_retrieval_service mechanisms. No scheme-specific hard-coding.
"""

from __future__ import annotations

import re
import time
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus, urlparse

from app.core.config import settings
from app.services.providers.base import (
    ExtractedEvidence,
    GovernmentInformationProvider,
    IdentityCheckResult,
    ProviderContext,
    ProviderPhaseStatus,
    ProviderRunResult,
    SchemeCandidate,
    extracted_evidence_is_usable,
    log_provider_event,
    merge_provider_ingested,
)
from app.services.providers.myscheme_provider import (
    _candidate_to_dict,
    _dict_to_candidate,
    _map_outcome,
)


def is_india_gov_url(url: str) -> bool:
    host = (urlparse(url or "").hostname or "").lower()
    return host == "india.gov.in" or host.endswith(".india.gov.in")


def _normalize_search_terms(query: str) -> str:
    from app.services.live_gov_retrieval_service import expand_search_query

    q = (expand_search_query(query) or query or "").strip()
    q = re.sub(
        r"^(what is|tell me about|details about|information about|can i get details about)\s+",
        "",
        q,
        flags=re.I,
    ).strip()
    return q[:120]


def build_india_gov_seeds_for_query(
    query: str,
    *,
    verify_fn,
    already: Optional[List[str]] = None,
    limit: int = 4,
) -> List[Dict[str, Any]]:
    """Dynamic India.gov seeds: registry base, catalog spotlight pages, portal search."""
    from app.services.gov_source_registry import load_registry
    from app.services.live_gov_retrieval_service import match_catalog_schemes

    seen = set(already or [])
    seeds: List[Dict[str, Any]] = []
    search_q = _normalize_search_terms(query)

    def _add(seed: Dict[str, Any]) -> bool:
        url = seed.get("url") or ""
        if not url or url in seen or not verify_fn(url) or not is_india_gov_url(url):
            return False
        seen.add(url)
        seeds.append(seed)
        return True

    registry = load_registry()
    for src in registry.get("sources") or []:
        if (src.get("domain") or "").lower() != "india.gov.in":
            continue
        if not src.get("enabled", True):
            continue
        for url in src.get("base_urls") or []:
            if _add(
                {
                    "url": url,
                    "scheme_name": src.get("name") or "India.gov.in",
                    "link_text": src.get("name") or "India.gov.in",
                    "stage": "india_gov_registry",
                    "source": "india_gov",
                    "source_id": src.get("id"),
                }
            ) and len(seeds) >= limit:
                return seeds[:limit]

    for scheme in match_catalog_schemes(query):
        for url in scheme.get("urls") or []:
            if not is_india_gov_url(url):
                continue
            if _add(
                {
                    "url": url,
                    "scheme_name": scheme.get("name"),
                    "ministry": scheme.get("ministry"),
                    "state": scheme.get("state"),
                    "scope": scheme.get("scope"),
                    "link_text": scheme.get("name") or "",
                    "stage": "india_gov_catalog",
                    "source": "india_gov",
                }
            ) and len(seeds) >= limit:
                return seeds[:limit]

    if search_q and len(seeds) < limit:
        search_url = f"https://www.india.gov.in/search/node?keys={quote_plus(search_q)}"
        _add(
            {
                "url": search_url,
                "scheme_name": "India.gov.in search",
                "link_text": search_q,
                "kind": "search",
                "stage": "india_gov_search",
                "source": "india_gov",
            }
        )

    return seeds[:limit]


def _looks_like_search_shell(url: str, content: Optional[bytes]) -> bool:
    """Search/redirect shells without extractable scheme content are not evidence."""
    if not content:
        return False
    text = content.decode("utf-8", errors="ignore") if isinstance(content, bytes) else str(content)
    blob = text.strip()
    if len(blob) < 80:
        return True
    lower = blob.lower()
    url_l = (url or "").lower()
    if blob.startswith("http") and len(blob.split()) <= 3:
        return True
    if "/search/" in url_l or "/search?" in url_l:
        markers = (
            "search results",
            'name="keys"',
            "no results found",
            "enter search terms",
            "refine your search",
        )
        if any(m in lower for m in markers) and len(blob) < 2500:
            # Allow if substantial scheme-like sections exist
            section_markers = ("eligibility", "benefits", "how to apply", "documents required")
            if not any(m in lower for m in section_markers):
                return True
    return False


def _filter_usable_candidates(candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for cand in candidates or []:
        url = cand.get("url") or ""
        if not is_india_gov_url(url):
            continue
        content = cand.get("content")
        if content is not None and _looks_like_search_shell(url, content):
            continue
        out.append(cand)
    return out


class IndiaGovProvider(GovernmentInformationProvider):
    """Adapter for India.gov.in National Portal scheme information."""

    name = "india_gov"
    priority = 150

    def supports(self, query: str, *, context: ProviderContext) -> bool:
        from app.services.live_gov_retrieval_service import looks_like_gov_scheme_query

        if not getattr(settings, "INDIAGOV_PROVIDER_ENABLED", True):
            return False
        q = (context.search_query or query or "").strip()
        return looks_like_gov_scheme_query(q)

    def resolve_identity(
        self,
        candidate: SchemeCandidate,
        query: str,
        *,
        context: ProviderContext,
        service: Any = None,
    ) -> IdentityCheckResult:
        from app.services.myscheme_service import request_accepts_candidate

        row = _candidate_to_dict(candidate)
        accepted = request_accepts_candidate(query, row)
        event = "INDIAGOV_IDENTITY_PASS" if accepted else "INDIAGOV_IDENTITY_FAIL"
        log_provider_event(
            self.name,
            event,
            live_request_id=context.live_request_id,
            url=(candidate.url or "")[:160],
        )
        if not accepted:
            log_provider_event(
                self.name,
                "INDIAGOV_CANDIDATE_REJECTED",
                live_request_id=context.live_request_id,
                reason="SCHEME_IDENTITY_MISMATCH",
            )
        return IdentityCheckResult(
            accepted=accepted,
            reason=None if accepted else "SCHEME_IDENTITY_MISMATCH",
            requested_scheme=(context.search_query or query or "")[:120],
            candidate_scheme=candidate.scheme_name or candidate.scheme_id,
        )

    def discover(
        self,
        query: str,
        *,
        context: ProviderContext,
        service: Any = None,
    ) -> List[SchemeCandidate]:
        from app.services.live_gov_retrieval_service import (
            expand_search_query,
            select_best_candidates,
            verify_source,
        )

        search_q = (context.search_query or expand_search_query(query)).strip()
        log_provider_event(
            self.name,
            "INDIAGOV_SEARCH",
            live_request_id=context.live_request_id,
            query=search_q[:160],
        )
        seeds = build_india_gov_seeds_for_query(
            search_q,
            verify_fn=verify_source,
            already=context.tried_urls,
            limit=int(settings.LIVE_GOV_MAX_SOURCES),
        )
        if not service or not seeds:
            return [_dict_to_candidate(s) for s in seeds]

        service._live_request_id = context.live_request_id  # noqa: SLF001
        service._live_query = search_q  # noqa: SLF001
        raw = service.discover_candidate_pages(
            search_q,
            overall_deadline=context.overall_deadline,
            seeds=seeds,
            max_pages=min(4, int(getattr(settings, "LIVE_GOV_MAX_PAGES", 6))),
        )
        india_only = _filter_usable_candidates(
            [c for c in raw if is_india_gov_url(c.get("url") or "")]
        )
        ranked = select_best_candidates(
            india_only,
            search_q,
            limit=int(settings.LIVE_GOV_MAX_CANDIDATES),
        )
        for row in ranked:
            log_provider_event(
                self.name,
                "INDIAGOV_CANDIDATE_FOUND",
                live_request_id=context.live_request_id,
                url=(row.get("url") or "")[:160],
            )
        return [_dict_to_candidate(c) for c in ranked]

    def extract(
        self,
        candidate: SchemeCandidate,
        *,
        query: str,
        context: ProviderContext,
        service: Any = None,
    ) -> ExtractedEvidence:
        row = _candidate_to_dict(candidate)
        content = row.get("content")
        text = ""
        if isinstance(content, bytes):
            text = content.decode("utf-8", errors="ignore")
        elif isinstance(content, str):
            text = content
        evidence = ExtractedEvidence(
            ok=bool(text.strip()) and not _looks_like_search_shell(row.get("url") or "", content),
            content=text,
            source_url=row.get("url") or "",
            scheme_name=row.get("scheme_name"),
            text_chars=len(text.strip()),
        )
        if not extracted_evidence_is_usable(evidence):
            evidence.ok = False
            evidence.reason = "search_shell_or_empty"
        elif evidence.ok:
            log_provider_event(
                self.name,
                "INDIAGOV_CONTENT_EXTRACTED",
                live_request_id=context.live_request_id,
                url=(evidence.source_url or "")[:160],
                chars=evidence.text_chars,
            )
        return evidence

    def discover_documents(
        self,
        candidate: SchemeCandidate,
        *,
        context: ProviderContext,
        service: Any = None,
    ) -> List[str]:
        if not service or not candidate.url:
            return []
        html = ""
        if isinstance(candidate.content, bytes):
            html = candidate.content.decode("utf-8", errors="ignore")
        if not html:
            return []
        links: List[str] = []
        for item in service.discover_pdf_links(candidate.url, html):
            url = str(item.get("url") or "")
            if not url:
                continue
            links.append(url)
            log_provider_event(
                self.name,
                "INDIAGOV_DOCUMENT_FOUND",
                live_request_id=context.live_request_id,
                url=url[:200],
            )
        return links

    def run(self, context: ProviderContext, *, service: Any = None) -> ProviderRunResult:
        from app.services.live_gov_retrieval_service import (
            expand_search_query,
            select_best_candidates,
            verify_source,
        )

        log_provider_event(
            self.name,
            "INDIAGOV_PROVIDER_START",
            live_request_id=context.live_request_id,
        )
        context.extra["india_gov_attempted"] = True

        if service is None:
            return ProviderRunResult(
                provider=self.name,
                status=ProviderPhaseStatus.ERROR,
                failure_codes=["no_service"],
                meta={"outcome": "failed", "reason": "no_service"},
            )

        if time.time() >= context.overall_deadline:
            return ProviderRunResult(
                provider=self.name,
                status=ProviderPhaseStatus.INSUFFICIENT,
                failure_codes=["timeout"],
                meta={"outcome": "failed", "reason": "deadline_before_start"},
            )

        search_q = (context.search_query or expand_search_query(context.query)).strip()
        log_provider_event(
            self.name,
            "INDIAGOV_SEARCH",
            live_request_id=context.live_request_id,
            query=search_q[:160],
        )

        service._live_request_id = context.live_request_id  # noqa: SLF001
        service._live_query = search_q  # noqa: SLF001

        ingested: List[Dict[str, Any]] = list(context.ingested or [])
        rejected_urls: List[str] = []
        failure_codes: List[str] = list(context.failure_codes or [])
        pdfs_used = int(context.extra.get("pdfs_used") or 0)
        max_pdfs = int(settings.LIVE_GOV_MAX_PDFS)
        per_source = float(context.per_source_timeout or settings.LIVE_GOV_TIMEOUT_SECONDS)

        seeds = build_india_gov_seeds_for_query(
            search_q,
            verify_fn=verify_source,
            already=context.tried_urls,
            limit=int(settings.LIVE_GOV_MAX_SOURCES),
        )
        if not seeds:
            log_provider_event(
                self.name,
                "INDIAGOV_FAILED",
                live_request_id=context.live_request_id,
                reason="no_seeds",
            )
            status, meta = _map_outcome(
                evidence_ready=False,
                ingested=ingested,
                ranked_count=0,
                accepted_count=0,
            )
            return ProviderRunResult(
                provider=self.name,
                status=status,
                failure_codes=failure_codes,
                meta=meta,
            )

        try:
            raw = service.discover_candidate_pages(
                search_q,
                overall_deadline=context.overall_deadline,
                seeds=seeds,
                max_pages=min(4, int(getattr(settings, "LIVE_GOV_MAX_PAGES", 6))),
            )
        except Exception as exc:  # noqa: BLE001
            log_provider_event(
                self.name,
                "INDIAGOV_FAILED",
                live_request_id=context.live_request_id,
                reason=type(exc).__name__,
            )
            return ProviderRunResult(
                provider=self.name,
                status=ProviderPhaseStatus.ERROR,
                failure_codes=[type(exc).__name__],
                meta={"outcome": "failed", "reason": type(exc).__name__},
            )

        india_only = _filter_usable_candidates(
            [c for c in raw if is_india_gov_url(c.get("url") or "")]
        )
        ranked = select_best_candidates(
            india_only,
            search_q,
            limit=int(settings.LIVE_GOV_MAX_CANDIDATES),
        )

        all_ranked: List[Dict[str, Any]] = list(context.extra.get("all_ranked") or [])
        all_ranked.extend(ranked)
        context.extra["all_ranked"] = all_ranked

        if not ranked:
            log_provider_event(
                self.name,
                "INDIAGOV_FAILED",
                live_request_id=context.live_request_id,
                reason="no_candidates",
            )
            status, meta = _map_outcome(
                evidence_ready=False,
                ingested=ingested,
                ranked_count=0,
                accepted_count=0,
            )
            return ProviderRunResult(
                provider=self.name,
                status=status,
                failure_codes=failure_codes,
                meta=meta,
            )

        for row in ranked:
            log_provider_event(
                self.name,
                "INDIAGOV_CANDIDATE_FOUND",
                live_request_id=context.live_request_id,
                url=(row.get("url") or "")[:160],
            )
            if (row.get("kind") or "").startswith("pdf") or str(row.get("url") or "").lower().endswith(".pdf"):
                log_provider_event(
                    self.name,
                    "INDIAGOV_PDF_INGESTED",
                    live_request_id=context.live_request_id,
                    url=(row.get("url") or "")[:200],
                )

        phase_out = service._ingest_ranked_until_sufficient(  # noqa: SLF001
            ranked,
            search_q=search_q,
            rid=context.live_request_id,
            overall_deadline=context.overall_deadline,
            per_source=per_source,
            phase="india_gov",
            ingested=ingested,
            rejected_urls=rejected_urls,
            failure_codes=failure_codes,
            pdfs_used=pdfs_used,
            max_pdfs=max_pdfs,
        )

        merge_provider_ingested(context, ingested)
        context.failure_codes = failure_codes
        context.extra["pdfs_used"] = int(phase_out.get("pdfs_used") or pdfs_used)
        for url in (c.get("url") for c in ranked if c.get("url")):
            if url not in context.tried_urls:
                context.tried_urls.append(url)

        evidence_ready = bool(phase_out.get("evidence_ready"))
        accepted_url = phase_out.get("accepted_url")

        status, meta = _map_outcome(
            evidence_ready=evidence_ready,
            ingested=context.ingested,
            ranked_count=len(ranked),
            accepted_count=len(ranked),
        )
        meta.update(
            {
                "index_stats": phase_out.get("index_stats") or {},
                "candidates_tried": int(phase_out.get("candidates_tried") or 0),
            }
        )

        if evidence_ready:
            log_provider_event(
                self.name,
                "INDIAGOV_SUFFICIENT",
                live_request_id=context.live_request_id,
                url=(accepted_url or "")[:160],
            )
        elif context.ingested:
            log_provider_event(
                self.name,
                "INDIAGOV_PARTIAL",
                live_request_id=context.live_request_id,
                kept=len(context.ingested),
            )
        else:
            log_provider_event(
                self.name,
                "INDIAGOV_FAILED",
                live_request_id=context.live_request_id,
                reason=meta.get("reason") or "no_usable",
            )

        return ProviderRunResult(
            provider=self.name,
            status=status,
            candidates_found=len(ranked),
            candidates_accepted=len(ranked),
            ingested_count=len(context.ingested),
            evidence_ready=evidence_ready,
            accepted_url=accepted_url,
            failure_codes=failure_codes,
            meta=meta,
        )
