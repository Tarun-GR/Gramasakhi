"""Adaptive public government source acquisition (live fallback only).

Strategies escalate from cheap static HTTP → browser JS rendering.
Does not redesign RAG; callers still use ingest_raw_bytes.
"""

from app.services.acquisition.base import (
    AcquisitionResult,
    AccessBlockedError,
    SourceHealth,
)
from app.services.acquisition.orchestrator import SourceAcquisitionOrchestrator
from app.services.acquisition.reliability import FailureCode, acquire_stats_snapshot

__all__ = [
    "AcquisitionResult",
    "AccessBlockedError",
    "SourceHealth",
    "SourceAcquisitionOrchestrator",
    "FailureCode",
    "acquire_stats_snapshot",
]
