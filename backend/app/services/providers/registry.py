"""Ordered government information provider registry.

Stage 1: chain runner only. Wrappers wire into live_gov_retrieval_service
in later stages without moving substantial logic out of that module.
"""

from __future__ import annotations

import time
from typing import Any, List, Optional, Sequence

from app.services.providers.base import (
    ChainRunResult,
    GovernmentInformationProvider,
    ProviderContext,
    ProviderPhaseStatus,
    ProviderRunResult,
    log_provider_event,
)


class ProviderRegistry:
    """Run providers in priority order; stop when one reports sufficient evidence."""

    def __init__(self, providers: Sequence[GovernmentInformationProvider]):
        ordered = sorted(list(providers or []), key=lambda p: (p.priority, p.name))
        self.providers: List[GovernmentInformationProvider] = ordered

    @property
    def provider_names(self) -> List[str]:
        return [p.name for p in self.providers]

    def run_chain(
        self,
        context: ProviderContext,
        *,
        service: Any = None,
    ) -> ChainRunResult:
        results: List[ProviderRunResult] = []
        final_provider: Optional[str] = None
        evidence_ready = False
        accepted_url: Optional[str] = None
        failure_codes = list(context.failure_codes or [])

        log_provider_event(
            "chain",
            "PROVIDER_CHAIN_START",
            live_request_id=context.live_request_id,
            providers=self.provider_names,
            query=(context.query or "")[:160],
        )

        for provider in self.providers:
            if time.time() >= context.overall_deadline:
                log_provider_event(
                    provider.name,
                    "PROVIDER_CHAIN_TIMEOUT",
                    live_request_id=context.live_request_id,
                )
                results.append(
                    ProviderRunResult(
                        provider=provider.name,
                        status=ProviderPhaseStatus.SKIPPED,
                        meta={"reason": "overall_deadline_exceeded"},
                    )
                )
                break

            if not provider.supports(context.query, context=context):
                log_provider_event(
                    provider.name,
                    "PROVIDER_SKIPPED",
                    live_request_id=context.live_request_id,
                    reason="supports_false",
                )
                results.append(
                    ProviderRunResult(
                        provider=provider.name,
                        status=ProviderPhaseStatus.SKIPPED,
                        meta={"reason": "supports_false"},
                    )
                )
                continue

            log_provider_event(
                provider.name,
                "PROVIDER_SELECTED",
                live_request_id=context.live_request_id,
            )
            log_provider_event(
                provider.name,
                "PROVIDER_START",
                live_request_id=context.live_request_id,
            )

            try:
                phase = provider.run(context, service=service)
            except Exception as exc:  # noqa: BLE001
                log_provider_event(
                    provider.name,
                    "PROVIDER_ERROR",
                    live_request_id=context.live_request_id,
                    err=type(exc).__name__,
                )
                phase = ProviderRunResult(
                    provider=provider.name,
                    status=ProviderPhaseStatus.ERROR,
                    failure_codes=[type(exc).__name__],
                    meta={"error": type(exc).__name__},
                )

            results.append(phase)
            if phase.failure_codes:
                for code in phase.failure_codes:
                    if code not in failure_codes:
                        failure_codes.append(code)

            if phase.accepted_url and phase.evidence_ready:
                accepted_url = phase.accepted_url

            log_provider_event(
                provider.name,
                "PROVIDER_END",
                live_request_id=context.live_request_id,
                status=phase.status.value,
                evidence_ready=phase.evidence_ready,
                ingested=phase.ingested_count,
            )
            if phase.status == ProviderPhaseStatus.SUFFICIENT and phase.evidence_ready:
                log_provider_event(
                    provider.name,
                    "PROVIDER_SUFFICIENT",
                    live_request_id=context.live_request_id,
                )
            elif phase.status == ProviderPhaseStatus.SKIPPED:
                pass
            elif (phase.meta or {}).get("outcome") == "partial":
                log_provider_event(
                    provider.name,
                    "PROVIDER_INSUFFICIENT",
                    live_request_id=context.live_request_id,
                    outcome="partial",
                )
            elif phase.status == ProviderPhaseStatus.ERROR:
                log_provider_event(
                    provider.name,
                    "PROVIDER_FAILED",
                    live_request_id=context.live_request_id,
                    reason="error",
                )
            else:
                log_provider_event(
                    provider.name,
                    "PROVIDER_INSUFFICIENT",
                    live_request_id=context.live_request_id,
                    outcome=(phase.meta or {}).get("outcome") or "insufficient",
                )

            if phase.status == ProviderPhaseStatus.SUFFICIENT and phase.evidence_ready:
                evidence_ready = True
                final_provider = provider.name
                log_provider_event(
                    provider.name,
                    "PROVIDER_CHAIN_SUFFICIENT",
                    live_request_id=context.live_request_id,
                )
                break

        if not evidence_ready:
            log_provider_event(
                "chain",
                "PROVIDER_CHAIN_INSUFFICIENT",
                live_request_id=context.live_request_id,
                tried=len(results),
            )

        log_provider_event(
            "chain",
            "PROVIDER_CHAIN_COMPLETE",
            live_request_id=context.live_request_id,
            evidence_ready=evidence_ready,
            final_provider=final_provider,
        )

        return ChainRunResult(
            evidence_ready=evidence_ready,
            final_provider=final_provider,
            provider_results=results,
            ingested=list(context.ingested or []),
            accepted_url=accepted_url,
            failure_codes=failure_codes,
        )


def default_provider_registry(
    providers: Optional[Sequence[GovernmentInformationProvider]] = None,
) -> ProviderRegistry:
    """Factory for explicit provider lists (wrappers added in Stage 2+)."""
    return ProviderRegistry(providers or [])
