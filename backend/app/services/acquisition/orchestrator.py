"""Source acquisition orchestrator — escalate static → browser → network docs."""

from __future__ import annotations

import logging
import time
from typing import Any, Callable, Optional
from urllib.parse import urlparse

from app.core.config import settings
from app.services.acquisition.base import (
    AcquisitionMethod,
    AcquisitionResult,
    SourceHealth,
)
from app.services.acquisition.browser_playwright import BrowserAcquisition, playwright_available
from app.services.acquisition.reliability import (
    FailureCode,
    get_capability,
    get_health,
    rate_limit_release,
    rate_limit_wait,
    record_acquire,
    set_health,
)
from app.services.acquisition.static_http import StaticHttpAcquisition

logger = logging.getLogger("gramsakhi.acquisition")

# Back-compat aliases for admin/tests that imported these names
_SOURCE_HEALTH = None  # populated lazily via reliability snapshot


def get_source_health(url: str) -> Optional[SourceHealth]:
    return get_health(url)


def set_source_health(url: str, health: SourceHealth) -> None:
    set_health(url, health)


class SourceAcquisitionOrchestrator:
    """
    Adaptive public acquisition:

      LEVEL 1 static HTTP
      LEVEL 2 document/API link discovery from HTML
      LEVEL 3 browser JS rendering (if static insufficient)
      LEVEL 4 dynamic download / network PDF detection
    """

    def __init__(self, web_service: Any):
        self.static = StaticHttpAcquisition(web_service)
        self.browser = BrowserAcquisition(
            timeout_seconds=float(
                getattr(settings, "LIVE_GOV_BROWSER_TIMEOUT_SECONDS", 45.0)
            ),
            max_actions=int(getattr(settings, "LIVE_GOV_MAX_BROWSER_ACTIONS", 8)),
        )
        self.min_html_chars = 200

    def acquire(
        self,
        url: str,
        *,
        verify_fn: Callable[[str], bool],
        live_request_id: str = "-",
        query: str = "",
        force_browser: bool = False,
        deadline_ts: Optional[float] = None,
    ) -> AcquisitionResult:
        started = time.perf_counter()
        key = (url or "").split("?")[0]
        host = (urlparse(url).hostname or "").lower()

        prior = get_health(key)
        if prior in (
            SourceHealth.CAPTCHA_BLOCKED,
            SourceHealth.LOGIN_REQUIRED,
            SourceHealth.PUBLIC_ACCESS_BLOCKED,
            SourceHealth.SSRF_BLOCKED,
        ):
            res = AcquisitionResult(
                url=url,
                error=prior.value,
                health=prior,
                method=AcquisitionMethod.STATIC_HTTP,
                meta={"failure_code": FailureCode.COOLDOWN_ACTIVE.value},
            )
            logger.info(
                "live_request_id=%s SOURCE_COOLDOWN url=%s health=%s",
                live_request_id,
                url,
                prior.value,
            )
            return res

        if deadline_ts is not None and time.time() >= deadline_ts:
            return AcquisitionResult(
                url=url,
                error="source_timeout",
                health=SourceHealth.TEMPORARILY_UNAVAILABLE,
                method=AcquisitionMethod.STATIC_HTTP,
                meta={"failure_code": FailureCode.TIMEOUT.value},
            )

        cap = get_capability(url)
        # Seeded/learned browser preference: still try static first unless forced
        prefer_browser = cap.preferred_strategy == "browser_js"
        skip_static = bool(force_browser)

        waited = rate_limit_wait(url)
        try:
            # LEVEL 1–2 static
            if not skip_static:
                logger.info(
                    "live_request_id=%s STATIC_ATTEMPT url=%s host=%s preferred=%s",
                    live_request_id,
                    url,
                    host,
                    cap.preferred_strategy,
                )
                static_res = self.static.fetch(
                    url, verify_fn=verify_fn, live_request_id=live_request_id
                )
                if static_res.health in (
                    SourceHealth.CAPTCHA_BLOCKED,
                    SourceHealth.LOGIN_REQUIRED,
                    SourceHealth.UNTRUSTED,
                ):
                    fc = (
                        FailureCode.CAPTCHA_BLOCKED
                        if static_res.health == SourceHealth.CAPTCHA_BLOCKED
                        else (
                            FailureCode.LOGIN_REQUIRED
                            if static_res.health == SourceHealth.LOGIN_REQUIRED
                            else FailureCode.UNTRUSTED_REDIRECT
                        )
                    )
                    set_health(key, static_res.health, failure_code=fc, error=static_res.error)
                    static_res.meta["failure_code"] = fc.value
                    self._finish(url, static_res, started, ok=False, failure_code=fc)
                    return static_res

                if static_res.ok:
                    ctype = (static_res.content_type or "").lower()
                    is_doc = (
                        "pdf" in ctype
                        or (static_res.content or b"")[:4] == b"%PDF"
                        or url.lower().endswith(
                            (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".csv", ".txt")
                        )
                    )
                    # HTML shell advertised as PDF
                    if url.lower().endswith(".pdf") and (static_res.content or b"")[:4] != b"%PDF":
                        if "html" in ctype or (static_res.content or b"")[:1] == b"<":
                            set_health(key, SourceHealth.JS_REQUIRED, failure_code=FailureCode.HTML_SHELL)
                            logger.info(
                                "live_request_id=%s HTML_SHELL url=%s",
                                live_request_id,
                                url,
                            )
                            # Escalate to browser instead of returning shell
                        else:
                            pass
                    else:
                        text_len = len((static_res.rendered_text or "").strip())
                        if is_doc and static_res.content:
                            set_health(key, SourceHealth.HEALTHY)
                            self._finish(url, static_res, started, ok=True)
                            return static_res

                        # myScheme: HTTP 200 + large SPA/Network Error shell ≠ success
                        myscheme_shell = False
                        shell_reason = ""
                        try:
                            host = (urlparse(url).hostname or "").lower()
                            if "myscheme.gov.in" in host:
                                from app.services.myscheme_service import (
                                    is_myscheme_shell_html,
                                    log_myscheme,
                                )

                                html_s = (static_res.content or b"").decode(
                                    "utf-8", errors="ignore"
                                )
                                myscheme_shell, shell_reason = is_myscheme_shell_html(
                                    html_s,
                                    rendered_text=static_res.rendered_text or "",
                                )
                                if myscheme_shell:
                                    log_myscheme(
                                        "MYSCHEME_SHELL",
                                        url=url,
                                        reason=shell_reason,
                                        method="static_http",
                                    )
                        except Exception:
                            myscheme_shell = False

                        if myscheme_shell:
                            set_health(
                                key,
                                SourceHealth.JS_REQUIRED,
                                failure_code=FailureCode.HTML_SHELL,
                            )
                            logger.info(
                                "live_request_id=%s MYSCHEME_SHELL_ESCALATE url=%s reason=%s",
                                live_request_id,
                                url,
                                shell_reason,
                            )
                        elif text_len >= self.min_html_chars or static_res.discovered_links:
                            # If domain prefers browser and static has thin content, escalate
                            if (
                                prefer_browser
                                and text_len < self.min_html_chars
                                and not static_res.discovered_links
                            ):
                                set_health(
                                    key,
                                    SourceHealth.JS_REQUIRED,
                                    failure_code=FailureCode.EMPTY_CONTENT,
                                )
                            else:
                                set_health(key, SourceHealth.HEALTHY)
                                self._finish(url, static_res, started, ok=True)
                                return static_res
                        else:
                            set_health(
                                key,
                                SourceHealth.JS_REQUIRED,
                                failure_code=FailureCode.EMPTY_CONTENT,
                            )
                            logger.info(
                                "live_request_id=%s STATIC_INSUFFICIENT url=%s text_len=%s links=%s",
                                live_request_id,
                                url,
                                text_len,
                                len(static_res.discovered_links),
                            )
                else:
                    logger.info(
                        "live_request_id=%s STATIC_FAIL_TRY_BROWSER url=%s err=%s",
                        live_request_id,
                        url,
                        static_res.error,
                    )

            if deadline_ts is not None and time.time() >= deadline_ts:
                return AcquisitionResult(
                    url=url,
                    error="source_timeout",
                    health=SourceHealth.TEMPORARILY_UNAVAILABLE,
                    method=AcquisitionMethod.STATIC_HTTP,
                    meta={"failure_code": FailureCode.TIMEOUT.value},
                )

            # LEVEL 3–4 browser
            if not getattr(settings, "LIVE_GOV_BROWSER_ENABLED", True):
                res = AcquisitionResult(
                    url=url,
                    error="browser_disabled",
                    health=SourceHealth.JS_REQUIRED,
                    method=AcquisitionMethod.BROWSER_JS,
                    meta={"failure_code": FailureCode.BROWSER_UNAVAILABLE.value},
                )
                self._finish(
                    url, res, started, ok=False, failure_code=FailureCode.BROWSER_UNAVAILABLE
                )
                return res
            if not playwright_available():
                res = AcquisitionResult(
                    url=url,
                    error="playwright_unavailable",
                    health=SourceHealth.JS_REQUIRED,
                    method=AcquisitionMethod.BROWSER_JS,
                    meta={
                        "hint": "pip install playwright && playwright install chromium",
                        "failure_code": FailureCode.BROWSER_UNAVAILABLE.value,
                    },
                )
                self._finish(
                    url, res, started, ok=False, failure_code=FailureCode.BROWSER_UNAVAILABLE
                )
                return res

            logger.info(
                "live_request_id=%s BROWSER_ATTEMPT url=%s waited_ms=%s",
                live_request_id,
                url,
                int(waited * 1000),
            )
            browser_res = self.browser.fetch(
                url,
                verify_fn=verify_fn,
                live_request_id=live_request_id,
                query=query,
                deadline_ts=deadline_ts,
            )
            if browser_res.health in (
                SourceHealth.CAPTCHA_BLOCKED,
                SourceHealth.LOGIN_REQUIRED,
                SourceHealth.UNTRUSTED,
            ):
                fc = (
                    FailureCode.CAPTCHA_BLOCKED
                    if browser_res.health == SourceHealth.CAPTCHA_BLOCKED
                    else (
                        FailureCode.LOGIN_REQUIRED
                        if browser_res.health == SourceHealth.LOGIN_REQUIRED
                        else FailureCode.UNTRUSTED_REDIRECT
                    )
                )
                set_health(key, browser_res.health, failure_code=fc, error=browser_res.error)
                browser_res.meta["failure_code"] = fc.value
                self._finish(url, browser_res, started, ok=False, failure_code=fc)
                return browser_res
            if browser_res.ok:
                set_health(key, SourceHealth.HEALTHY)
                self._finish(url, browser_res, started, ok=True)
            else:
                fc = FailureCode.JS_RENDER_FAILED
                browser_res.meta["failure_code"] = fc.value
                set_health(
                    key,
                    SourceHealth.TEMPORARILY_UNAVAILABLE,
                    failure_code=fc,
                    error=browser_res.error,
                )
                self._finish(url, browser_res, started, ok=False, failure_code=fc)
            return browser_res
        finally:
            rate_limit_release(url)

    def _finish(
        self,
        url: str,
        result: AcquisitionResult,
        started: float,
        *,
        ok: bool,
        failure_code: Optional[FailureCode] = None,
    ) -> None:
        latency_ms = (time.perf_counter() - started) * 1000.0
        result.meta["latency_ms"] = round(latency_ms, 1)
        if failure_code and "failure_code" not in result.meta:
            result.meta["failure_code"] = failure_code.value
        record_acquire(
            url,
            method=result.method,
            ok=ok,
            latency_ms=latency_ms,
            health=result.health,
            failure_code=failure_code,
        )
        logger.info(
            "LIVE_ACQUIRE_DONE url=%s method=%s ok=%s health=%s failure_code=%s latency_ms=%.0f",
            url,
            getattr(result.method, "value", result.method),
            ok,
            result.health.value,
            result.meta.get("failure_code"),
            latency_ms,
        )
