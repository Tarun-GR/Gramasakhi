"""Thin trusted registry / state / central government provider.

Delegates to existing Phase 2 live_gov retrieval (discover_seed_urls fallback,
discover_candidate_pages, select_best_candidates, _ingest_ranked_until_sufficient).
"""

from __future__ import annotations

import time
from typing import Any, Dict, List

from app.core.config import settings
from app.services.providers.base import (
    ExtractedEvidence,
    GovernmentInformationProvider,
    IdentityCheckResult,
    ProviderContext,
    ProviderPhaseStatus,
    ProviderRunResult,
    SchemeCandidate,
    log_provider_event,
    merge_provider_ingested,
)
from app.services.providers.myscheme_provider import (
    _candidate_to_dict,
    _dict_to_candidate,
    _map_outcome,
)


def _filter_fallback_seeds(seeds: List[Dict[str, Any]], context: ProviderContext) -> List[Dict[str, Any]]:
    from app.services.myscheme_service import is_myscheme_url
    from app.services.providers.data_gov_provider import is_data_gov_url
    from app.services.providers.india_gov_provider import is_india_gov_url

    return [
        s
        for s in seeds
        if (s.get("url") or "") not in context.tried_urls
        and not is_myscheme_url(s.get("url") or "")
        and not (
            context.extra.get("india_gov_attempted")
            and is_india_gov_url(s.get("url") or "")
        )
        and not (
            context.extra.get("data_gov_attempted")
            and is_data_gov_url(s.get("url") or "")
        )
    ]


class RegistryGovernmentProvider(GovernmentInformationProvider):
    """Adapter over existing trusted registry / catalog / portal fallback."""

    name = "registry_government"
    priority = 200

    def supports(self, query: str, *, context: ProviderContext) -> bool:
        # Chain entry is already gated for government/scheme queries at the live layer.
        return True

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
    ) -> List:
        from app.services.live_gov_retrieval_service import (
            discover_seed_urls,
            expand_search_query,
            select_best_candidates,
        )

        search_q = (context.search_query or expand_search_query(query)).strip()
        log_provider_event(
            self.name,
            "STATE_GOV_SEARCH_START",
            live_request_id=context.live_request_id,
            query=search_q[:160],
        )
        fallback_seeds = discover_seed_urls(
            search_q,
            phase="fallback",
            already=context.tried_urls,
        )
        fallback_seeds = _filter_fallback_seeds(fallback_seeds, context)
        if not service or not fallback_seeds:
            return [_dict_to_candidate(s) for s in fallback_seeds]

        service._live_request_id = context.live_request_id  # noqa: SLF001
        service._live_query = search_q  # noqa: SLF001
        raw = service.discover_candidate_pages(
            search_q,
            overall_deadline=context.overall_deadline,
            seeds=fallback_seeds,
        )
        ranked = select_best_candidates(
            raw,
            search_q,
            limit=int(settings.LIVE_GOV_MAX_CANDIDATES),
        )
        return [_dict_to_candidate(c) for c in ranked]

    def run(self, context: ProviderContext, *, service: Any = None) -> ProviderRunResult:
        from app.services.live_gov_retrieval_service import (
            discover_seed_urls,
            expand_search_query,
            select_best_candidates,
        )

        if service is None:
            return ProviderRunResult(
                provider=self.name,
                status=ProviderPhaseStatus.ERROR,
                failure_codes=["no_service"],
                meta={"reason": "LiveGovRetrievalService required"},
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
            "STATE_GOV_SEARCH_START",
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
        myscheme_phase_used = bool(context.extra.get("myscheme_phase_used"))

        all_ranked: List[Dict[str, Any]] = list(context.extra.get("all_ranked") or [])
        ranked_fb: List[Dict[str, Any]] = []
        phase_out: Dict[str, Any] = {}

        fallback_seeds = discover_seed_urls(
            search_q,
            phase="fallback",
            already=context.tried_urls,
        )
        fallback_seeds = _filter_fallback_seeds(fallback_seeds, context)

        if fallback_seeds:
            try:
                raw_fb = service.discover_candidate_pages(
                    search_q,
                    overall_deadline=context.overall_deadline,
                    seeds=fallback_seeds,
                )
            except Exception as exc:  # noqa: BLE001
                if not ingested:
                    return ProviderRunResult(
                        provider=self.name,
                        status=ProviderPhaseStatus.ERROR,
                        failure_codes=[type(exc).__name__, "NETWORK_ERROR"],
                        meta={"outcome": "failed", "reason": type(exc).__name__},
                    )
                raw_fb = []

            ranked_fb = select_best_candidates(
                raw_fb,
                search_q,
                limit=int(settings.LIVE_GOV_MAX_CANDIDATES),
            )
            all_ranked.extend(ranked_fb)

            if ranked_fb:
                phase_out = service._ingest_ranked_until_sufficient(  # noqa: SLF001
                    ranked_fb,
                    search_q=search_q,
                    rid=context.live_request_id,
                    overall_deadline=context.overall_deadline,
                    per_source=per_source,
                    phase="fallback",
                    ingested=ingested,
                    rejected_urls=rejected_urls,
                    failure_codes=failure_codes,
                    pdfs_used=pdfs_used,
                    max_pdfs=max_pdfs,
                )
        elif not myscheme_phase_used:
            try:
                raw_candidates = service.discover_candidate_pages(
                    search_q,
                    overall_deadline=context.overall_deadline,
                )
            except Exception as exc:  # noqa: BLE001
                return ProviderRunResult(
                    provider=self.name,
                    status=ProviderPhaseStatus.ERROR,
                    failure_codes=[type(exc).__name__],
                    meta={"outcome": "failed", "reason": type(exc).__name__},
                )
            ranked_fb = select_best_candidates(
                raw_candidates,
                search_q,
                limit=int(settings.LIVE_GOV_MAX_CANDIDATES),
            )
            all_ranked.extend(ranked_fb)
            if ranked_fb:
                phase_out = service._ingest_ranked_until_sufficient(  # noqa: SLF001
                    ranked_fb,
                    search_q=search_q,
                    rid=context.live_request_id,
                    overall_deadline=context.overall_deadline,
                    per_source=per_source,
                    phase="legacy",
                    ingested=ingested,
                    rejected_urls=rejected_urls,
                    failure_codes=failure_codes,
                    pdfs_used=pdfs_used,
                    max_pdfs=max_pdfs,
                )
        else:
            log_provider_event(
                self.name,
                "STATE_GOV_SEARCH_START",
                live_request_id=context.live_request_id,
                skipped=True,
                reason="no_fallback_seeds_after_myscheme",
            )

        merge_provider_ingested(context, ingested)
        context.failure_codes = failure_codes
        context.extra["all_ranked"] = all_ranked
        context.extra["pdfs_used"] = int(phase_out.get("pdfs_used") or pdfs_used)
        for url in (c.get("url") for c in ranked_fb if c.get("url")):
            if url not in context.tried_urls:
                context.tried_urls.append(url)

        evidence_ready = bool(phase_out.get("evidence_ready"))
        accepted_url = phase_out.get("accepted_url")

        if ranked_fb and evidence_ready:
            log_provider_event(
                self.name,
                "STATE_GOV_CONTENT_EXTRACTED",
                live_request_id=context.live_request_id,
                candidates=len(ranked_fb),
            )

        status, meta = _map_outcome(
            evidence_ready=evidence_ready,
            ingested=context.ingested,
            ranked_count=len(ranked_fb),
            accepted_count=len(ranked_fb),
        )
        meta.update(
            {
                "index_stats": phase_out.get("index_stats") or {},
                "candidates_tried": int(phase_out.get("candidates_tried") or 0),
                "phase": phase_out.get("phase") or ("fallback" if fallback_seeds else "legacy"),
            }
        )

        if evidence_ready:
            log_provider_event(
                self.name,
                "STATE_GOV_CONTENT_EXTRACTED",
                live_request_id=context.live_request_id,
                sufficient=True,
            )

        return ProviderRunResult(
            provider=self.name,
            status=status,
            candidates_found=len(ranked_fb),
            candidates_accepted=len(ranked_fb),
            ingested_count=len(context.ingested),
            evidence_ready=evidence_ready,
            accepted_url=accepted_url,
            failure_codes=failure_codes,
            meta=meta,
        )
