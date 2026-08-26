"""Thin myScheme provider — delegates to existing live/myScheme implementations.

Does not duplicate acquisition, ingestion, identity, or extraction logic.
Production orchestration remains in live_gov_retrieval_service until Stage 3.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

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


def _dict_to_candidate(row: Dict[str, Any]) -> SchemeCandidate:
    content = row.get("content")
    if content is not None and not isinstance(content, (bytes, str)):
        content = None
    return SchemeCandidate(
        url=str(row.get("url") or ""),
        scheme_name=row.get("scheme_name"),
        scheme_id=row.get("scheme_id"),
        kind=str(row.get("kind") or ""),
        content=content if isinstance(content, bytes) else None,
        link_text=row.get("link_text"),
        meta={
            k: v
            for k, v in row.items()
            if k
            not in {
                "url",
                "scheme_name",
                "scheme_id",
                "kind",
                "content",
                "link_text",
            }
        },
    )


def _candidate_to_dict(candidate: SchemeCandidate) -> Dict[str, Any]:
    row: Dict[str, Any] = {
        "url": candidate.url,
        "scheme_name": candidate.scheme_name,
        "scheme_id": candidate.scheme_id,
        "kind": candidate.kind,
        "link_text": candidate.link_text,
    }
    if candidate.content is not None:
        row["content"] = candidate.content
    row.update(candidate.meta or {})
    return row


def _compute_myscheme_deadline(context: ProviderContext) -> float:
    """Match live_gov Phase 1 myScheme budget without altering that module."""
    browser_budget = float(getattr(settings, "LIVE_GOV_BROWSER_TIMEOUT_SECONDS", 45.0))
    overall_budget = float(settings.LIVE_GOV_OVERALL_TIMEOUT_SECONDS)
    per_source = float(context.per_source_timeout or settings.LIVE_GOV_TIMEOUT_SECONDS)
    wall_start = float(context.extra.get("wall_start") or time.time())
    myscheme_budget = min(
        overall_budget * 0.65,
        max(per_source * 2.5, browser_budget + 35.0, 70.0),
    )
    return min(context.overall_deadline, wall_start + myscheme_budget)


def _map_outcome(
    *,
    evidence_ready: bool,
    ingested: List[Dict[str, Any]],
    ranked_count: int,
    accepted_count: int,
) -> tuple[ProviderPhaseStatus, Dict[str, Any]]:
    meta: Dict[str, Any] = {}
    if evidence_ready:
        meta["outcome"] = "sufficient"
        return ProviderPhaseStatus.SUFFICIENT, meta
    if ingested:
        meta["outcome"] = "partial"
        return ProviderPhaseStatus.INSUFFICIENT, meta
    if ranked_count == 0:
        meta["outcome"] = "failed"
        return ProviderPhaseStatus.INSUFFICIENT, meta
    if accepted_count == 0:
        meta["outcome"] = "failed"
        meta["reason"] = "identity_rejected_or_no_content"
        return ProviderPhaseStatus.INSUFFICIENT, meta
    meta["outcome"] = "failed"
    meta["reason"] = "no_usable"
    return ProviderPhaseStatus.INSUFFICIENT, meta


class MySchemeProvider(GovernmentInformationProvider):
    """Adapter over existing myScheme-first live retrieval phase."""

    name = "myscheme"
    priority = 100

    def supports(self, query: str, *, context: ProviderContext) -> bool:
        from app.services.live_gov_retrieval_service import looks_like_gov_scheme_query

        q = (context.search_query or query or "").strip()
        return looks_like_gov_scheme_query(q)

    def discover(
        self,
        query: str,
        *,
        context: ProviderContext,
        service: Any = None,
    ) -> List[SchemeCandidate]:
        from app.services.live_gov_retrieval_service import (
            discover_seed_urls,
            expand_search_query,
            select_best_candidates,
        )
        from app.services.myscheme_service import is_myscheme_url, normalize_myscheme_search_query

        normalize_myscheme_search_query(query)
        search_q = (context.search_query or expand_search_query(query)).strip()
        log_provider_event(
            self.name,
            "MYSCHEME_SEARCH_START",
            live_request_id=context.live_request_id,
            query=search_q[:160],
        )
        seeds = discover_seed_urls(search_q, phase="myscheme", already=context.tried_urls)
        if not service or not seeds:
            return [_dict_to_candidate(s) for s in seeds]

        service._live_request_id = context.live_request_id  # noqa: SLF001
        service._live_query = search_q  # noqa: SLF001
        deadline = _compute_myscheme_deadline(context)
        raw = service.discover_candidate_pages(
            search_q,
            overall_deadline=deadline,
            seeds=seeds,
            max_pages=min(4, int(getattr(settings, "LIVE_GOV_MAX_PAGES", 6))),
        )
        ms_only = [c for c in raw if is_myscheme_url(c.get("url") or "")]
        ranked = select_best_candidates(
            ms_only,
            search_q,
            limit=int(settings.LIVE_GOV_MAX_CANDIDATES),
        )
        for row in ranked:
            log_provider_event(
                self.name,
                "MYSCHEME_CANDIDATE_FOUND",
                live_request_id=context.live_request_id,
                url=(row.get("url") or "")[:160],
                scheme_id=row.get("scheme_id"),
            )
        return [_dict_to_candidate(c) for c in ranked]

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
        event = "MYSCHEME_IDENTITY_PASS" if accepted else "MYSCHEME_IDENTITY_FAIL"
        log_provider_event(
            self.name,
            event,
            live_request_id=context.live_request_id,
            url=(candidate.url or "")[:160],
            scheme_id=candidate.scheme_id,
        )
        return IdentityCheckResult(
            accepted=accepted,
            reason=None if accepted else "SCHEME_IDENTITY_MISMATCH",
            requested_scheme=(context.search_query or query or "")[:120],
            candidate_scheme=candidate.scheme_name or candidate.scheme_id,
        )

    def extract(
        self,
        candidate: SchemeCandidate,
        *,
        query: str,
        context: ProviderContext,
        service: Any = None,
    ) -> ExtractedEvidence:
        from app.services.myscheme_service import package_myscheme_evidence

        row = _candidate_to_dict(candidate)
        content = row.get("content")
        html = ""
        rendered = str(row.get("rendered_text") or "")
        json_blobs = None
        if isinstance(content, bytes):
            html = content.decode("utf-8", errors="ignore")
        elif isinstance(content, str):
            stripped = content.strip()
            if stripped.startswith("{") or stripped.startswith("["):
                json_blobs = [content]
            else:
                html = content

        packed = package_myscheme_evidence(
            html=html,
            rendered_text=rendered,
            scheme_name=row.get("scheme_name") or row.get("link_text") or "",
            source_url=row.get("url") or "",
            query=query,
            json_blobs=json_blobs,
        )

        evidence = ExtractedEvidence(
            ok=bool(packed.get("ok")),
            content=str(packed.get("content") or ""),
            sections=dict(packed.get("sections") or {}),
            source_url=row.get("url") or "",
            scheme_id=packed.get("scheme_id") or row.get("scheme_id"),
            scheme_name=packed.get("scheme_name") or row.get("scheme_name"),
            reason=packed.get("reason"),
            text_chars=int(packed.get("text_chars") or 0),
        )
        if not extracted_evidence_is_usable(evidence):
            evidence.ok = False
            evidence.reason = evidence.reason or "url_only_or_empty"
        elif evidence.ok:
            log_provider_event(
                self.name,
                "MYSCHEME_CONTENT_EXTRACTED",
                live_request_id=context.live_request_id,
                url=(evidence.source_url or "")[:160],
                chars=evidence.text_chars,
                sections=list(evidence.sections.keys())[:8],
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
        elif candidate.meta.get("html"):
            html = str(candidate.meta.get("html"))
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
                "MYSCHEME_DOCUMENT_FOUND",
                live_request_id=context.live_request_id,
                url=url[:200],
                scheme_id=candidate.scheme_id,
            )
        return links

    def run(self, context: ProviderContext, *, service: Any = None) -> ProviderRunResult:
        """Delegate to existing myScheme Phase 1 orchestration on LiveGovRetrievalService."""
        from app.services.live_gov_retrieval_service import (
            discover_seed_urls,
            expand_search_query,
            select_best_candidates,
        )
        from app.services.myscheme_service import (
            is_myscheme_url,
            log_myscheme,
            normalize_myscheme_search_query,
        )

        if service is None:
            return ProviderRunResult(
                provider=self.name,
                status=ProviderPhaseStatus.ERROR,
                failure_codes=["no_service"],
                meta={"reason": "LiveGovRetrievalService required"},
            )

        search_q = (context.search_query or expand_search_query(context.query)).strip()
        normalize_myscheme_search_query(context.query)
        log_provider_event(
            self.name,
            "MYSCHEME_SEARCH_START",
            live_request_id=context.live_request_id,
            query=search_q[:160],
        )

        if time.time() >= context.overall_deadline:
            return ProviderRunResult(
                provider=self.name,
                status=ProviderPhaseStatus.INSUFFICIENT,
                failure_codes=["timeout"],
                meta={"outcome": "failed", "reason": "deadline_before_start"},
            )

        service._live_request_id = context.live_request_id  # noqa: SLF001
        service._live_query = search_q  # noqa: SLF001
        myscheme_deadline = _compute_myscheme_deadline(context)
        per_source = float(context.per_source_timeout or settings.LIVE_GOV_TIMEOUT_SECONDS)
        ingested: List[Dict[str, Any]] = list(context.ingested or [])
        rejected_urls: List[str] = []
        failure_codes: List[str] = list(context.failure_codes or [])
        pdfs_used = int(context.extra.get("pdfs_used") or 0)
        max_pdfs = int(settings.LIVE_GOV_MAX_PDFS)

        myscheme_seeds = discover_seed_urls(
            search_q,
            phase="myscheme",
            already=context.tried_urls,
        )
        if myscheme_seeds:
            context.extra["myscheme_phase_used"] = True
        if not myscheme_seeds or time.time() >= myscheme_deadline:
            log_myscheme("MYSCHEME_FAILED", live_request_id=context.live_request_id, reason="no_seeds")
            status, meta = _map_outcome(
                evidence_ready=False,
                ingested=ingested,
                ranked_count=0,
                accepted_count=0,
            )
            meta["reason"] = meta.get("reason") or "no_seeds"
            failure_codes.append("scheme_not_resolved")
            return ProviderRunResult(
                provider=self.name,
                status=status,
                failure_codes=failure_codes,
                meta=meta,
            )

        log_myscheme(
            "MYSCHEME_PRIORITY_START",
            live_request_id=context.live_request_id,
            seeds=len(myscheme_seeds),
        )

        discovery_error = None
        try:
            raw_ms = service.discover_candidate_pages(
                search_q,
                overall_deadline=myscheme_deadline,
                seeds=myscheme_seeds,
                max_pages=min(4, int(getattr(settings, "LIVE_GOV_MAX_PAGES", 6))),
            )
        except Exception as exc:  # noqa: BLE001
            discovery_error = exc
            log_myscheme(
                "MYSCHEME_FAILED",
                live_request_id=context.live_request_id,
                reason=type(exc).__name__,
            )
            raw_ms = []

        ms_only = [c for c in raw_ms if is_myscheme_url(c.get("url") or "")]
        ranked_ms = select_best_candidates(
            ms_only,
            search_q,
            limit=int(settings.LIVE_GOV_MAX_CANDIDATES),
        )

        walked_canonical = any(
            (s.get("kind") == "scheme_page") or "/schemes/" in ((s.get("url") or "").lower())
            for s in myscheme_seeds
        )
        if (
            not ranked_ms
            and discovery_error is None
            and not raw_ms
            and not walked_canonical
        ):
            browser_ms = service._myscheme_browser_discover_candidates(  # noqa: SLF001
                search_q,
                overall_deadline=myscheme_deadline,
                already_urls=[s.get("url") for s in myscheme_seeds if s.get("url")],
            )
            if browser_ms:
                ranked_ms = select_best_candidates(
                    browser_ms,
                    search_q,
                    limit=int(settings.LIVE_GOV_MAX_CANDIDATES),
                )

        candidates_found = len(ranked_ms)
        accepted_count = len(ranked_ms)
        context.extra.setdefault("all_ranked", []).extend(ranked_ms)

        if not ranked_ms:
            failure_codes.append("scheme_not_resolved")
            log_myscheme(
                "MYSCHEME_FAILED",
                live_request_id=context.live_request_id,
                reason="scheme_not_resolved",
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
                candidates_found=0,
                candidates_accepted=0,
                failure_codes=failure_codes,
                meta=meta,
            )

        log_myscheme(
            "MYSCHEME_CANDIDATE_FOUND",
            live_request_id=context.live_request_id,
            count=candidates_found,
        )

        phase_out = service._ingest_ranked_until_sufficient(  # noqa: SLF001
            ranked_ms,
            search_q=search_q,
            rid=context.live_request_id,
            overall_deadline=myscheme_deadline,
            per_source=per_source,
            phase="myscheme",
            ingested=ingested,
            rejected_urls=rejected_urls,
            failure_codes=failure_codes,
            pdfs_used=pdfs_used,
            max_pdfs=max_pdfs,
        )

        merge_provider_ingested(context, ingested)
        context.failure_codes = failure_codes
        context.extra["pdfs_used"] = int(phase_out.get("pdfs_used") or pdfs_used)
        if phase_out.get("myscheme_page_found_no_content"):
            context.extra["myscheme_page_found_no_content"] = True
        for url in (c.get("url") for c in ranked_ms if c.get("url")):
            if url not in context.tried_urls:
                context.tried_urls.append(url)

        evidence_ready = bool(phase_out.get("evidence_ready"))
        accepted_url = phase_out.get("accepted_url")

        status, meta = _map_outcome(
            evidence_ready=evidence_ready,
            ingested=context.ingested,
            ranked_count=candidates_found,
            accepted_count=accepted_count,
        )
        meta.update(
            {
                "index_stats": phase_out.get("index_stats") or {},
                "myscheme_page_found_no_content": bool(
                    phase_out.get("myscheme_page_found_no_content")
                ),
                "candidates_tried": int(phase_out.get("candidates_tried") or 0),
            }
        )
        if evidence_ready:
            log_provider_event(
                self.name,
                "MYSCHEME_SUFFICIENT",
                live_request_id=context.live_request_id,
                url=(accepted_url or "")[:160],
            )
        elif context.ingested:
            log_provider_event(
                self.name,
                "MYSCHEME_INSUFFICIENT",
                live_request_id=context.live_request_id,
                outcome="partial",
                kept=len(context.ingested),
            )
        else:
            log_provider_event(
                self.name,
                "MYSCHEME_INSUFFICIENT",
                live_request_id=context.live_request_id,
                outcome="failed",
            )

        return ProviderRunResult(
            provider=self.name,
            status=status,
            candidates_found=candidates_found,
            candidates_accepted=accepted_count,
            ingested_count=len(context.ingested),
            evidence_ready=evidence_ready,
            accepted_url=accepted_url,
            failure_codes=failure_codes,
            meta=meta,
        )
