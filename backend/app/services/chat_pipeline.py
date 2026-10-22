"""Chat request budgets, stage timing, and cloud-safe retrieval guards."""

from __future__ import annotations

import contextvars
import logging
import time
import uuid
from typing import Any, Dict, Optional

from app.core.config import settings

logger = logging.getLogger("gramsakhi.chat.pipeline")

_pipeline_deadline: contextvars.ContextVar[Optional[float]] = contextvars.ContextVar(
    "chat_pipeline_deadline", default=None
)
_request_id: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "chat_request_id", default=None
)

# Render web proxy commonly closes idle/slow responses near ~100s on Free tier.
_CLOUD_DEFAULT_BUDGET_S = 88.0
_LOCAL_DEFAULT_BUDGET_S = 270.0


class ChatPipelineTimeout(Exception):
    """Raised when a chat turn exceeds its wall-clock budget."""


def new_chat_request_id() -> str:
    return uuid.uuid4().hex[:12]


def set_chat_request_context(*, request_id: str, deadline_mono: float) -> None:
    _request_id.set(request_id)
    _pipeline_deadline.set(deadline_mono)


def clear_chat_request_context() -> None:
    _request_id.set(None)
    _pipeline_deadline.set(None)


def current_chat_request_id() -> Optional[str]:
    return _request_id.get()


def chat_pipeline_budget_seconds() -> float:
    explicit = float(getattr(settings, "CHAT_PIPELINE_BUDGET_SECONDS", 0) or 0)
    if explicit > 0:
        return explicit
    from app.services.runtime_profile import is_cloud_runtime

    return _CLOUD_DEFAULT_BUDGET_S if is_cloud_runtime() else _LOCAL_DEFAULT_BUDGET_S


def remaining_budget_seconds() -> Optional[float]:
    deadline = _pipeline_deadline.get()
    if deadline is None:
        return None
    return max(0.0, deadline - time.monotonic())


def ensure_budget(min_seconds: float = 1.0) -> None:
    remaining = remaining_budget_seconds()
    if remaining is not None and remaining < min_seconds:
        raise ChatPipelineTimeout("chat_pipeline_budget_exceeded")


def live_gov_effective_overall_seconds() -> float:
    base = float(settings.LIVE_GOV_OVERALL_TIMEOUT_SECONDS)
    from app.services.runtime_profile import is_cloud_runtime

    if is_cloud_runtime():
        cap = float(getattr(settings, "CLOUD_LIVE_GOV_OVERALL_CAP_SECONDS", 45.0) or 45.0)
        base = min(base, cap)
    remaining = remaining_budget_seconds()
    if remaining is not None:
        # Leave headroom for validation + LLM after live ingest attempt.
        base = min(base, max(8.0, remaining - 12.0))
    return max(5.0, base)


class ChatStageTimer:
    """Structured sanitized timing for one chat HTTP request."""

    def __init__(self, request_id: str) -> None:
        self.request_id = request_id
        self._started = time.perf_counter()
        self._last = self._started
        self.stages: Dict[str, int] = {}

    def mark(self, stage: str, **extra: Any) -> None:
        now = time.perf_counter()
        delta_ms = int((now - self._last) * 1000)
        total_ms = int((now - self._started) * 1000)
        self._last = now
        self.stages[stage] = delta_ms
        safe_extra = " ".join(f"{k}={v}" for k, v in extra.items() if v is not None)
        logger.info(
            "chat_stage rid=%s stage=%s delta_ms=%s total_ms=%s %s",
            self.request_id,
            stage,
            delta_ms,
            total_ms,
            safe_extra.strip(),
        )

    def finish(self, *, status: str, http_status: int) -> None:
        total_ms = int((time.perf_counter() - self._started) * 1000)
        logger.info(
            "chat_complete rid=%s status=%s http=%s total_ms=%s stages=%s",
            self.request_id,
            status,
            http_status,
            total_ms,
            self.stages,
        )
