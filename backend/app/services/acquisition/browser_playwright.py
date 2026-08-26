"""Level 3–5: Playwright JS rendering for public government pages only."""

from __future__ import annotations

import logging
import re
import time
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from app.services.acquisition.base import (
    AcquisitionMethod,
    AcquisitionResult,
    SourceHealth,
    detect_access_block,
)
from app.services.acquisition.static_http import discover_document_links

logger = logging.getLogger("gramsakhi.acquisition.browser")

_PRIVATE_HOST_MARKERS = (
    "localhost",
    "127.0.0.1",
    "0.0.0.0",
    "::1",
    "169.254.169.254",
    "metadata.google",
)

_PRIVATE_IP_PREFIXES = (
    "10.",
    "192.168.",
    "172.16.",
    "172.17.",
    "172.18.",
    "172.19.",
    "172.20.",
    "172.21.",
    "172.22.",
    "172.23.",
    "172.24.",
    "172.25.",
    "172.26.",
    "172.27.",
    "172.28.",
    "172.29.",
    "172.30.",
    "172.31.",
)


def playwright_available() -> bool:
    try:
        import playwright  # noqa: F401

        return True
    except Exception:
        return False


def _host_is_private(hostname: str) -> bool:
    h = (hostname or "").lower().strip(".")
    if not h:
        return True
    if h in _PRIVATE_HOST_MARKERS or any(h.endswith(m) for m in _PRIVATE_HOST_MARKERS):
        return True
    if any(h.startswith(p) for p in _PRIVATE_IP_PREFIXES):
        return True
    return False


class BrowserAcquisition:
    """Headless Chromium acquisition with allowlist + SSRF guards."""

    def __init__(
        self,
        *,
        timeout_seconds: float = 45.0,
        max_actions: int = 8,
    ):
        self.timeout_seconds = float(timeout_seconds)
        self.max_actions = int(max_actions)

    def fetch(
        self,
        url: str,
        *,
        verify_fn: Callable[[str], bool],
        live_request_id: str = "-",
        query: str = "",
        deadline_ts: Optional[float] = None,
    ) -> AcquisitionResult:
        if not verify_fn(url):
            return AcquisitionResult(
                url=url,
                error="untrusted",
                health=SourceHealth.UNTRUSTED,
                method=AcquisitionMethod.BROWSER_JS,
            )
        if not playwright_available():
            return AcquisitionResult(
                url=url,
                error="playwright_unavailable",
                health=SourceHealth.TEMPORARILY_UNAVAILABLE,
                method=AcquisitionMethod.BROWSER_JS,
                meta={"browser_available": False},
            )

        try:
            from playwright.sync_api import TimeoutError as PwTimeout
            from playwright.sync_api import sync_playwright
        except Exception as e:  # noqa: BLE001
            return AcquisitionResult(
                url=url,
                error=f"playwright_import:{type(e).__name__}",
                health=SourceHealth.TEMPORARILY_UNAVAILABLE,
                method=AcquisitionMethod.BROWSER_JS,
            )

        timeout_ms = int(max(5.0, self.timeout_seconds) * 1000)
        if deadline_ts is not None:
            remaining_ms = int(max(1000, (deadline_ts - time.time()) * 1000))
            timeout_ms = min(timeout_ms, remaining_ms)
        discovered: List[Dict[str, Any]] = []
        downloaded: List[Tuple[str, bytes, str]] = []
        network_docs: List[Dict[str, Any]] = []
        network_json_bodies: List[Tuple[str, str]] = []
        rendered_html = ""
        final_url = url
        actions = 0

        logger.info(
            "live_request_id=%s BROWSER_FALLBACK url=%s", live_request_id, url
        )

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context(accept_downloads=True)

                def _route_handler(route, request):  # noqa: ANN001
                    req_url = request.url
                    host = urlparse(req_url).hostname or ""
                    if _host_is_private(host):
                        logger.warning(
                            "live_request_id=%s BROWSER_SSRF_BLOCKED url=%s",
                            live_request_id,
                            req_url,
                        )
                        return route.abort()
                    # Only allow trusted navigations / document fetches
                    if request.resource_type in ("document", "xhr", "fetch", "other"):
                        if not verify_fn(req_url) and not req_url.startswith("blob:"):
                            # Allow same-page assets loosely; block cross-nav to untrusted
                            if request.is_navigation_request():
                                return route.abort()
                    return route.continue_()

                context.route("**/*", _route_handler)

                def _on_response(response):  # noqa: ANN001
                    try:
                        rurl = response.url
                        ctype = (response.headers.get("content-type") or "").lower()
                        if not verify_fn(rurl):
                            return
                        if "pdf" in ctype or rurl.lower().endswith(".pdf"):
                            network_docs.append(
                                {
                                    "url": rurl,
                                    "link_text": "network pdf",
                                    "kind": "dynamic_download",
                                    "content_type": ctype,
                                }
                            )
                        elif "json" in ctype:
                            network_docs.append(
                                {
                                    "url": rurl,
                                    "link_text": "network api",
                                    "kind": "public_api",
                                    "content_type": ctype,
                                }
                            )
                            # Capture public JSON bodies for scheme-id discovery
                            try:
                                if response.ok and len(network_json_bodies) < 12:
                                    body = response.body()
                                    if body and len(body) < 2_000_000:
                                        network_json_bodies.append(
                                            (
                                                rurl,
                                                body.decode("utf-8", errors="ignore"),
                                            )
                                        )
                            except Exception:  # noqa: BLE001
                                pass
                    except Exception:  # noqa: BLE001
                        return

                context.on("response", _on_response)
                page = context.new_page()
                page.set_default_timeout(timeout_ms)

                page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                try:
                    page.wait_for_load_state("networkidle", timeout=min(timeout_ms, 15000))
                except PwTimeout:
                    pass
                # SPA shells often need extra settle time after networkidle
                try:
                    page.wait_for_timeout(min(5000, max(1000, timeout_ms // 6)))
                    page.evaluate("window.scrollTo(0, Math.min(1200, document.body.scrollHeight))")
                    page.wait_for_timeout(800)
                except Exception:  # noqa: BLE001
                    pass

                final_url = page.url
                if not verify_fn(final_url):
                    browser.close()
                    return AcquisitionResult(
                        url=url,
                        final_url=final_url,
                        error="untrusted_redirect",
                        health=SourceHealth.UNTRUSTED,
                        method=AcquisitionMethod.BROWSER_JS,
                    )

                rendered_html = page.content() or ""
                blocked = detect_access_block(rendered_html)
                if blocked in (SourceHealth.CAPTCHA_BLOCKED, SourceHealth.LOGIN_REQUIRED):
                    browser.close()
                    logger.info(
                        "live_request_id=%s BROWSER_ACCESS_BLOCKED health=%s",
                        live_request_id,
                        blocked.value,
                    )
                    return AcquisitionResult(
                        url=url,
                        final_url=final_url,
                        error=blocked.value,
                        health=blocked,
                        method=AcquisitionMethod.BROWSER_JS,
                    )

                # Public interactions: Documents / Download / myScheme tabs (bounded, read-only)
                host = (urlparse(final_url or url).hostname or "").lower()
                myscheme = "myscheme.gov.in" in host
                path_l = (urlparse(final_url or url).path or "").lower()
                is_myscheme_search = myscheme and (
                    "/search" in path_l or "/external/search" in path_l
                )

                # myScheme search: fill normalized scheme name + submit (public only)
                if is_myscheme_search and query and actions < self.max_actions:
                    try:
                        from app.services.myscheme_service import (
                            log_myscheme,
                            normalize_myscheme_search_query,
                        )

                        term = normalize_myscheme_search_query(query)
                        log_myscheme(
                            "MYSCHEME_DISCOVERY_BROWSER",
                            action="search_attempt",
                            term=(term or "")[:100],
                            url=(final_url or url)[:160],
                        )
                        if term:
                            filled = False
                            selectors = (
                                'input[type="search"]',
                                'input[name="q"]',
                                'input[placeholder*="Search" i]',
                                'input[placeholder*="scheme" i]',
                                'input[aria-label*="Search" i]',
                                'input[type="text"]',
                            )
                            for sel in selectors:
                                try:
                                    loc = page.locator(sel).first
                                    if loc.count() == 0:
                                        continue
                                    loc.click(timeout=1500)
                                    loc.fill(term, timeout=2000)
                                    filled = True
                                    actions += 1
                                    break
                                except Exception:  # noqa: BLE001
                                    continue
                            if filled:
                                try:
                                    page.keyboard.press("Enter")
                                    actions += 1
                                except Exception:  # noqa: BLE001
                                    try:
                                        page.locator(
                                            'button[type="submit"], button:has-text("Search")'
                                        ).first.click(timeout=2000)
                                        actions += 1
                                    except Exception:  # noqa: BLE001
                                        pass
                                try:
                                    page.wait_for_load_state(
                                        "networkidle",
                                        timeout=min(timeout_ms, 12000),
                                    )
                                except PwTimeout:
                                    pass
                                try:
                                    page.wait_for_timeout(1500)
                                except Exception:  # noqa: BLE001
                                    pass
                                final_url = page.url
                                rendered_html = page.content() or ""
                                log_myscheme(
                                    "MYSCHEME_DISCOVERY_BROWSER",
                                    action="search_submitted",
                                    term=term[:100],
                                )
                    except Exception:  # noqa: BLE001
                        pass

                click_labels = (
                    "document",
                    "documents",
                    "documents required",
                    "download",
                    "pdf",
                    "guideline",
                    "guidelines",
                    "scheme",
                    "view",
                    "load more",
                    "next",
                    "resources",
                    "eligibility",
                    "benefits",
                    "details",
                    "faq",
                    "faqs",
                    "frequently asked questions",
                    "application",
                    "application process",
                    "how to apply",
                    "sources and references",
                )
                if myscheme:
                    try:
                        from app.services.myscheme_service import log_myscheme

                        log_myscheme("MYSCHEME_BROWSER", url=final_url or url)
                    except Exception:
                        pass
                q_tokens = set(re.findall(r"[a-zA-Z]{4,}", (query or "").lower()))
                # On myScheme, always allow public scheme-section tabs (lazy content).
                myscheme_always = {
                    "document",
                    "documents",
                    "documents required",
                    "download",
                    "pdf",
                    "guideline",
                    "guidelines",
                    "load more",
                    "next",
                    "resources",
                    "view",
                    "eligibility",
                    "benefits",
                    "details",
                    "faq",
                    "faqs",
                    "frequently asked questions",
                    "application",
                    "application process",
                    "how to apply",
                    "sources and references",
                }
                is_scheme_detail = myscheme and "/schemes/" in path_l
                scheme_stay_url = final_url if is_scheme_detail else ""
                if is_scheme_detail:
                    try:
                        from app.services.myscheme_service import log_myscheme

                        log_myscheme("MYSCHEME_BROWSER_START", url=final_url or url)
                        # Progressive scroll to trigger lazy panels
                        for y in (400, 900, 1400):
                            page.evaluate(f"window.scrollTo(0, {y})")
                            page.wait_for_timeout(400)
                    except Exception:  # noqa: BLE001
                        pass

                # On scheme detail pages, only click in-page section tabs (not sitewide FAQ links)
                scheme_tab_labels = (
                    "details",
                    "benefits",
                    "eligibility",
                    "application process",
                    "documents required",
                    "documents",
                    "faqs",
                    "frequently asked questions",
                    "sources and references",
                )
                active_labels = scheme_tab_labels if is_scheme_detail else click_labels

                for label in active_labels:
                    if actions >= self.max_actions:
                        break
                    if (
                        not myscheme
                        and q_tokens
                        and label not in q_tokens
                        and label not in myscheme_always
                    ):
                        continue
                    if (
                        myscheme
                        and not is_scheme_detail
                        and label not in myscheme_always
                        and q_tokens
                        and label not in q_tokens
                    ):
                        continue
                    try:
                        loc = None
                        if is_scheme_detail:
                            # Prefer tabs/buttons so we do not navigate to /faqs site pages
                            for role in ("tab", "button"):
                                cand = page.get_by_role(
                                    role, name=re.compile(label, re.I)
                                ).first
                                if cand.count() > 0:
                                    loc = cand
                                    break
                            if loc is None:
                                cand = page.get_by_text(
                                    re.compile(rf"^{re.escape(label)}$", re.I)
                                ).first
                                if cand.count() > 0:
                                    loc = cand
                        else:
                            loc = page.get_by_role(
                                "link", name=re.compile(label, re.I)
                            ).first
                            if loc.count() == 0:
                                loc = page.get_by_role(
                                    "button", name=re.compile(label, re.I)
                                ).first
                            if loc.count() == 0:
                                loc = None
                        if loc is None:
                            continue
                        # myScheme section tabs rarely trigger downloads — click directly
                        if myscheme and (is_scheme_detail or label in myscheme_always):
                            loc.click(timeout=2500)
                            actions += 1
                            try:
                                page.wait_for_timeout(700)
                            except Exception:  # noqa: BLE001
                                pass
                            # Stay on canonical scheme page
                            if scheme_stay_url and "/schemes/" not in (
                                page.url or ""
                            ).lower():
                                try:
                                    page.goto(
                                        scheme_stay_url,
                                        wait_until="domcontentloaded",
                                        timeout=min(timeout_ms, 15000),
                                    )
                                    page.wait_for_timeout(800)
                                except Exception:  # noqa: BLE001
                                    pass
                            continue
                        with page.expect_download(timeout=2500) as dl_info:
                            loc.click(timeout=2500)
                            actions += 1
                        try:
                            download = dl_info.value
                            path = download.path()
                            if path:
                                data = open(path, "rb").read()
                                if data:
                                    downloaded.append(
                                        (download.url or final_url, data, "application/octet-stream")
                                    )
                        except Exception:  # noqa: BLE001
                            pass
                    except Exception:  # noqa: BLE001
                        # Click without download is fine — may reveal links
                        try:
                            if is_scheme_detail:
                                continue
                            page.get_by_text(re.compile(label, re.I)).first.click(
                                timeout=1500
                            )
                            actions += 1
                            if myscheme:
                                try:
                                    page.wait_for_timeout(500)
                                except Exception:  # noqa: BLE001
                                    pass
                        except Exception:  # noqa: BLE001
                            continue

                try:
                    page.wait_for_timeout(800)
                except Exception:  # noqa: BLE001
                    pass

                # Ensure we finish on the scheme page when that was the target
                if scheme_stay_url and "/schemes/" not in (page.url or "").lower():
                    try:
                        page.goto(
                            scheme_stay_url,
                            wait_until="domcontentloaded",
                            timeout=min(timeout_ms, 20000),
                        )
                        page.wait_for_load_state(
                            "networkidle", timeout=min(timeout_ms, 12000)
                        )
                        page.wait_for_timeout(1500)
                    except Exception:  # noqa: BLE001
                        pass

                rendered_html = page.content() or ""
                final_url = page.url
                text = ""
                try:
                    text = page.inner_text("body") or ""
                except Exception:  # noqa: BLE001
                    text = ""
                if is_scheme_detail:
                    try:
                        from app.services.myscheme_service import log_myscheme

                        log_myscheme(
                            "MYSCHEME_BROWSER_RENDERED",
                            url=final_url or url,
                            text_len=len(text or ""),
                            actions=actions,
                        )
                        log_myscheme(
                            "MYSCHEME_RENDERED",
                            url=final_url or url,
                            text_len=len(text or ""),
                        )
                    except Exception:  # noqa: BLE001
                        pass

                discovered = discover_document_links(
                    final_url, rendered_html, verify_fn=verify_fn
                )
                # Merge network-discovered docs
                seen = {d["url"] for d in discovered}
                for n in network_docs:
                    if n["url"] not in seen and verify_fn(n["url"]):
                        discovered.append(n)
                        seen.add(n["url"])

                # myScheme: promote scheme links + public JSON search hits
                if myscheme:
                    try:
                        from app.services.myscheme_service import (
                            discover_myscheme_scheme_links,
                            extract_candidates_from_json_text,
                            log_myscheme,
                        )

                        for link in discover_myscheme_scheme_links(
                            final_url,
                            rendered_html,
                            verify_fn=verify_fn,
                            query=query,
                            limit=12,
                        ):
                            u = link.get("url") or ""
                            if u and u not in seen and verify_fn(u):
                                discovered.append(
                                    {
                                        "url": u,
                                        "link_text": link.get("scheme_name")
                                        or link.get("link_text")
                                        or "",
                                        "kind": "scheme_page",
                                        "scheme_id": link.get("scheme_id"),
                                    }
                                )
                                seen.add(u)
                        json_hits = 0
                        for _jurl, jbody in network_json_bodies:
                            for cand in extract_candidates_from_json_text(
                                jbody, query=query, verify_fn=verify_fn
                            ):
                                u = cand.get("url") or cand.get("canonical_url") or ""
                                if not u or u in seen or not verify_fn(u):
                                    continue
                                discovered.append(
                                    {
                                        "url": u,
                                        "link_text": cand.get("scheme_name") or "",
                                        "kind": "scheme_page",
                                        "scheme_id": cand.get("scheme_id"),
                                    }
                                )
                                seen.add(u)
                                json_hits += 1
                        log_myscheme(
                            "MYSCHEME_DISCOVERY_BROWSER",
                            action="extract",
                            links=len(discovered),
                            json_bodies=len(network_json_bodies),
                            json_hits=json_hits,
                        )
                    except Exception:  # noqa: BLE001
                        pass

                content = rendered_html.encode("utf-8", errors="ignore")
                # Prefer first downloaded PDF bytes if any
                for durl, data, dct in downloaded:
                    if data[:4] == b"%PDF" or (durl or "").lower().endswith(".pdf"):
                        browser.close()
                        logger.info(
                            "live_request_id=%s BROWSER_DYNAMIC_DOWNLOAD url=%s bytes=%s",
                            live_request_id,
                            durl,
                            len(data),
                        )
                        return AcquisitionResult(
                            url=url,
                            content=data,
                            content_type="application/pdf",
                            final_url=durl or final_url,
                            method=AcquisitionMethod.DYNAMIC_DOWNLOAD,
                            health=SourceHealth.HEALTHY,
                            discovered_links=discovered,
                            rendered_text=text,
                            meta={"browser_actions": actions},
                        )

                browser.close()
                logger.info(
                    "live_request_id=%s BROWSER_RENDERED url=%s text_len=%s links=%s actions=%s",
                    live_request_id,
                    final_url,
                    len(text),
                    len(discovered),
                    actions,
                )
                return AcquisitionResult(
                    url=url,
                    content=content,
                    content_type="text/html",
                    final_url=final_url,
                    method=AcquisitionMethod.BROWSER_JS,
                    health=SourceHealth.HEALTHY,
                    discovered_links=discovered,
                    rendered_text=text,
                    meta={"browser_actions": actions},
                )
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "live_request_id=%s BROWSER_FAIL url=%s err=%s",
                live_request_id,
                url,
                type(e).__name__,
            )
            return AcquisitionResult(
                url=url,
                error=str(e)[:300],
                health=SourceHealth.TEMPORARILY_UNAVAILABLE,
                method=AcquisitionMethod.BROWSER_JS,
            )

