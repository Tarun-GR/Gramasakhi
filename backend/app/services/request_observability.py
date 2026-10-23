"""HTTP request IDs and sanitized access logging."""

from __future__ import annotations

import logging
import time
import uuid
from typing import Optional

from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger("gramsakhi.api")

REQUEST_ID_HEADER = "X-GramSakhi-Request-Id"


def new_request_id() -> str:
    return uuid.uuid4().hex[:16]


def normalize_path(path: str) -> str:
    p = (path or "").strip()
    if len(p) > 120:
        return p[:117] + "..."
    return p


async def observability_middleware(request: Request, call_next) -> Response:
    """Log every request; never log auth headers or bodies."""
    rid = new_request_id()
    request.state.request_id = rid
    method = (request.method or "GET").upper()
    path = normalize_path(request.url.path or "")
    started = time.perf_counter()
    status = 500
    err_type: Optional[str] = None
    try:
        response = await call_next(request)
        status = response.status_code
        response.headers.setdefault(REQUEST_ID_HEADER, rid)
        return response
    except Exception as exc:
        err_type = type(exc).__name__
        logger.exception(
            "http_request_error rid=%s method=%s path=%s err=%s",
            rid,
            method,
            path,
            err_type,
        )
        raise
    finally:
        ms = int((time.perf_counter() - started) * 1000)
        logger.info(
            "http_request rid=%s method=%s path=%s status=%s duration_ms=%s err=%s",
            rid,
            method,
            path,
            status,
            ms,
            err_type or "-",
        )
