"""Bridge ProviderRegistry chain to LiveGovRetrievalService response shape."""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from app.core.config import settings
from app.services.live_gov_retrieval_service import (
    LIVE_CANDIDATE_FOUND,
    LIVE_DOCUMENT_INGESTED,
    LIVE_SEARCH_STARTED,
    LIVE_UNAVAILABLE,
    NO_TRUSTED_INFORMATION_FOUND,
    expand_search_query,
)
from app.services.providers.base import ChainRunResult, ProviderContext, log_provider_event
from app.services.providers.data_gov_provider import DataGovProvider
from app.services.providers.india_gov_provider import IndiaGovProvider
from app.services.providers.myscheme_provider import MySchemeProvider
from app.services.providers.registry import ProviderRegistry
from app.services.providers.registry_government_provider import RegistryGovernmentProvider


def build_default_registry() -> ProviderRegistry:
    return ProviderRegistry(
        [
            MySchemeProvider(),
            IndiaGovProvider(),
            DataGovProvider(),
            RegistryGovernmentProvider(),
        ]
    )


def search_via_provider_registry(
    service: Any,
    *,
    query: str,
    search_q: str,
    rid: str,
    wall_start: float,
    overall_deadline: float,
    per_source: float,
    started: float,
) -> Dict[str, Any]:
    """Run provider chain and map to legacy search_government_sources response."""
    context = ProviderContext(
        query=query,
        search_query=search_q or expand_search_query(query),
        live_request_id=rid,
        overall_deadline=overall_deadline,
        per_source_timeout=per_source,
        extra={"wall_start": wall_start, "all_ranked": [], "pdfs_used": 0},
    )
    log_provider_event(
        "registry",
        "PROVIDER_REGISTRY_START",
        live_request_id=rid,
        query=(search_q or query or "")[:160],
    )
    registry = build_default_registry()
    chain = registry.run_chain(context, service=service)
    log_provider_event(
        "registry",
        "PROVIDER_CHAIN_COMPLETE",
        live_request_id=rid,
        evidence_ready=chain.evidence_ready,
        final_provider=chain.final_provider,
    )
    return finalize_chain_to_live_response(
        service,
        chain=chain,
        context=context,
        rid=rid,
        search_q=search_q,
        started=started,
    )


def finalize_chain_to_live_response(
    service: Any,
    *,
    chain: ChainRunResult,
    context: ProviderContext,
    rid: str,
    search_q: str,
    started: float,
) -> Dict[str, Any]:
    """Convert chain output into the dict expected by try_live_gov_fallback / RAG."""
    from app.services.live_gov_retrieval_service import _live_log

    ingested = list(chain.ingested or context.ingested or [])
    all_ranked: List[Dict[str, Any]] = list(context.extra.get("all_ranked") or [])
    failure_codes = list(chain.failure_codes or [])
    rejected_urls: List[str] = []
    evidence_ready = bool(chain.evidence_ready)
    accepted_url = chain.accepted_url
    myscheme_phase_used = bool(context.extra.get("myscheme_phase_used"))
    myscheme_page_found_no_content = bool(context.extra.get("myscheme_page_found_no_content"))

    status = LIVE_DOCUMENT_INGESTED if ingested else LIVE_SEARCH_STARTED
    if evidence_ready and not ingested:
        status = LIVE_CANDIDATE_FOUND
    index_stats: Dict[str, Any] = {}
    candidates_tried = 0
    for pr in chain.provider_results or []:
        candidates_tried += int((pr.meta or {}).get("candidates_tried") or pr.candidates_found or 0)
        if (pr.meta or {}).get("index_stats"):
            index_stats = pr.meta["index_stats"]

    latency_ms = int((time.perf_counter() - started) * 1000)
    _live_log(
        rid,
        "LIVE_FALLBACK_SUMMARY",
        accepted_url=accepted_url,
        rejected=len(rejected_urls),
        evidence_ready=evidence_ready,
        latency_ms=latency_ms,
        myscheme_phase=myscheme_phase_used,
        provider_registry=True,
        final_provider=chain.final_provider,
    )

    guidance_urls = [
        {
            "url": c.get("url"),
            "name": c.get("scheme_name") or c.get("link_text") or "",
            "scheme_name": c.get("scheme_name") or c.get("link_text") or "",
            "link_text": c.get("link_text") or "",
            "stage": "candidate",
            "reason": "Candidate official page found while checking government sources.",
        }
        for c in all_ranked[:6]
        if c.get("url")
    ]

    preferred_status = _derive_preferred_status(
        evidence_ready=evidence_ready,
        ingested=ingested,
        failure_codes=failure_codes,
        guidance_urls=guidance_urls,
        myscheme_page_found_no_content=myscheme_page_found_no_content,
    )

    if not ingested:
        detail = None
        if any(
            c in failure_codes
            for c in ("NETWORK_ERROR", "TimeoutError", "ConnectionError")
        ):
            detail = LIVE_UNAVAILABLE
        return {
            "status": NO_TRUSTED_INFORMATION_FOUND,
            "ingested": [],
            "candidates_tried": candidates_tried or len(all_ranked),
            "rejected_urls": rejected_urls,
            "failure_codes": failure_codes,
            "guidance_urls": guidance_urls,
            "preferred_status": preferred_status,
            "live_request_id": rid,
            "latency_ms": latency_ms,
            "myscheme_priority": myscheme_phase_used,
            "evidence_ready": evidence_ready,
            "provider_registry": True,
            "final_provider": chain.final_provider,
            "detail": detail,
        }

    if not index_stats:
        try:
            index_stats = service.refresh_indexes(live_request_id=rid)
        except Exception as exc:  # noqa: BLE001
            index_stats = {"error": str(exc)}

    return {
        "status": status if evidence_ready or ingested else NO_TRUSTED_INFORMATION_FOUND,
        "ingested": ingested,
        "candidates_tried": candidates_tried or len(all_ranked),
        "accepted_url": accepted_url,
        "rejected_urls": rejected_urls,
        "failure_codes": failure_codes,
        "guidance_urls": guidance_urls,
        "preferred_status": preferred_status,
        "index_stats": index_stats,
        "evidence_ready": evidence_ready,
        "live_request_id": rid,
        "latency_ms": latency_ms,
        "myscheme_priority": myscheme_phase_used,
        "provider_registry": True,
        "final_provider": chain.final_provider,
    }


def _derive_preferred_status(
    *,
    evidence_ready: bool,
    ingested: List[Any],
    failure_codes: List[str],
    guidance_urls: List[Dict[str, Any]],
    myscheme_page_found_no_content: bool,
) -> Optional[str]:
    has_scheme_url = any(
        "myscheme.gov.in/schemes/" in ((g.get("url") or "").lower()) for g in guidance_urls
    )
    if not evidence_ready and myscheme_page_found_no_content and has_scheme_url:
        return "scheme_content_unavailable"
    if not evidence_ready and ingested and has_scheme_url:
        return "scheme_question_insufficient"
    if (
        not evidence_ready
        and not ingested
        and has_scheme_url
        and any(c == "scheme_not_resolved" for c in failure_codes)
    ):
        return "scheme_content_unavailable"
    if (
        not evidence_ready
        and not ingested
        and not has_scheme_url
        and any(c == "scheme_not_resolved" for c in failure_codes)
    ):
        return "scheme_not_identified"
    return None
