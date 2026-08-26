"""Level 1–2: static HTTP acquisition + document/API link discovery."""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

from app.services.acquisition.base import (
    AcquisitionMethod,
    AcquisitionResult,
    SourceHealth,
    detect_access_block,
)

logger = logging.getLogger("gramsakhi.acquisition.static")

_DOC_EXT = (
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".csv",
    ".txt",
)


def discover_document_links(base_url: str, html: str, *, verify_fn) -> List[Dict[str, Any]]:
    """Find PDF/DOC/XLS/etc links + common viewer/iframe sources in HTML."""
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []

    soup = BeautifulSoup(html or "", "html.parser")
    out: List[Dict[str, Any]] = []
    seen = set()

    def _add(absolute: str, link_text: str = "", kind: str = "document_link") -> None:
        absolute = (absolute or "").split("#")[0].strip()
        if not absolute or absolute in seen:
            return
        if not verify_fn(absolute):
            return
        seen.add(absolute)
        out.append(
            {
                "url": absolute,
                "link_text": (link_text or "")[:200],
                "kind": kind,
            }
        )

    for a in soup.find_all("a", href=True):
        href = (a.get("href") or "").strip()
        if not href:
            continue
        absolute = urljoin(base_url, href)
        lower = absolute.lower().split("?")[0]
        # Skip images/media even if path contains "pdf-files"
        if any(lower.endswith(ext) for ext in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".mp4")):
            continue
        # myScheme /schemes/ detail pages (HTML evidence, not only PDFs)
        if "/schemes/" in lower and "myscheme.gov.in" in lower:
            _add(absolute, a.get_text(" ", strip=True) or "", "scheme_page")
            continue
        if any(lower.endswith(ext) or f"{ext}?" in absolute.lower() for ext in _DOC_EXT):
            _add(absolute, a.get_text(" ", strip=True) or "", "document_link")
        elif lower.endswith("/download") or "download.php" in lower or "downloadfile" in lower:
            if any(
                tok in absolute.lower()
                for tok in ("pdf", "document", "guideline", "circular", "notification")
            ):
                _add(absolute, a.get_text(" ", strip=True) or "", "document_link")

    for tag in soup.find_all(["iframe", "embed", "object"]):
        src = tag.get("src") or tag.get("data") or ""
        if not src:
            continue
        absolute = urljoin(base_url, src)
        lower = absolute.lower()
        if ".pdf" in lower or "viewer" in lower or "document" in lower:
            _add(absolute, "embedded viewer", "embedded_viewer")

    # Bare PDF URLs in scripts / JSON (common SPA bootstrap)
    for match in re.findall(
        r"https?://[^\s\"'<>]+\.pdf(?:\?[^\s\"'<>]*)?",
        html or "",
        flags=re.I,
    ):
        _add(match, "embedded url", "document_link")

    # Bound discovery — relevance ranking happens later; avoid portal floods
    return out[:40]


def discover_public_api_hints(base_url: str, html: str, *, verify_fn) -> List[Dict[str, Any]]:
    """Heuristic discovery of publicly referenced JSON/API endpoints in page source."""
    hints: List[Dict[str, Any]] = []
    seen = set()
    patterns = (
        r"https?://[^\s\"'<>]+/api/[^\s\"'<>]+",
        r"https?://[^\s\"'<>]+\.json(?:\?[^\s\"'<>]*)?",
    )
    for pat in patterns:
        for match in re.findall(pat, html or "", flags=re.I):
            url = match.rstrip(".,);]")
            if url in seen or not verify_fn(url):
                continue
            # Skip auth-looking endpoints
            low = url.lower()
            if any(x in low for x in ("/auth", "/login", "/token", "/oauth", "apikey=")):
                continue
            seen.add(url)
            hints.append({"url": url, "link_text": "public api hint", "kind": "public_api"})
    return hints[:12]


def discover_pagination_links(base_url: str, html: str, *, verify_fn) -> List[str]:
    """Bounded discovery of public next/page=N links (no infinite crawl)."""
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []

    soup = BeautifulSoup(html or "", "html.parser")
    out: List[str] = []
    seen = {base_url.split("?")[0]}

    def _add(href: str) -> None:
        absolute = urljoin(base_url, href).split("#")[0]
        if not absolute or absolute in seen:
            return
        if not verify_fn(absolute):
            return
        seen.add(absolute)
        out.append(absolute)

    for a in soup.find_all("a", href=True):
        href = (a.get("href") or "").strip()
        text = (a.get_text(" ", strip=True) or "").lower()
        low = href.lower()
        if (
            "page=" in low
            or re.search(r"[?&]p=\d+", low)
            or text in ("next", "next »", "»", "load more", "more")
            or "page/" in low
        ):
            _add(href)

    return out[:8]


def public_api_bytes_to_text(content: bytes, content_type: str = "") -> str:
    """Convert public JSON/XML/CSV API payloads into readable text for ingestion."""
    ctype = (content_type or "").lower()
    raw = (content or b"").decode("utf-8", errors="ignore").strip()
    if not raw:
        return ""
    if "json" in ctype or raw[:1] in ("{", "["):
        try:
            import json

            data = json.loads(raw)

            def _walk(node: Any, parts: List[str], depth: int = 0) -> None:
                if depth > 6:
                    return
                if isinstance(node, dict):
                    for k, v in node.items():
                        if isinstance(v, (dict, list)):
                            parts.append(str(k))
                            _walk(v, parts, depth + 1)
                        else:
                            parts.append(f"{k}: {v}")
                elif isinstance(node, list):
                    for item in node[:80]:
                        _walk(item, parts, depth + 1)
                else:
                    parts.append(str(node))

            parts: List[str] = []
            _walk(data, parts)
            return "\n".join(parts)[:200_000]
        except Exception:  # noqa: BLE001
            return raw[:200_000]
    return raw[:200_000]


class StaticHttpAcquisition:
    """Wrap existing WebIngestionService.fetch_url with access detection."""

    def __init__(self, web_service: Any):
        self.web = web_service

    def fetch(
        self,
        url: str,
        *,
        verify_fn,
        live_request_id: str = "-",
    ) -> AcquisitionResult:
        if not verify_fn(url):
            return AcquisitionResult(
                url=url,
                error="untrusted",
                health=SourceHealth.UNTRUSTED,
                method=AcquisitionMethod.STATIC_HTTP,
            )
        try:
            content, ctype = self.web.fetch_url(url)
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "live_request_id=%s STATIC_FETCH_FAIL url=%s err=%s",
                live_request_id,
                url,
                type(e).__name__,
            )
            return AcquisitionResult(
                url=url,
                error=str(e)[:300],
                health=SourceHealth.TEMPORARILY_UNAVAILABLE,
                method=AcquisitionMethod.STATIC_HTTP,
            )

        final_url = url
        method = AcquisitionMethod.STATIC_HTTP
        lower_ct = (ctype or "").lower()
        if "pdf" in lower_ct or url.lower().endswith(".pdf"):
            method = AcquisitionMethod.DIRECT_DOCUMENT

        rendered_text = None
        discovered: List[Dict[str, Any]] = []
        if "html" in lower_ct or (content and content[:1] == b"<"):
            html = content.decode("utf-8", errors="ignore")
            blocked = detect_access_block(html)
            if blocked in (SourceHealth.CAPTCHA_BLOCKED, SourceHealth.LOGIN_REQUIRED):
                logger.info(
                    "live_request_id=%s STATIC_ACCESS_BLOCKED url=%s health=%s",
                    live_request_id,
                    url,
                    blocked.value,
                )
                return AcquisitionResult(
                    url=url,
                    content=None,
                    content_type=ctype,
                    final_url=final_url,
                    method=method,
                    health=blocked,
                    error=blocked.value,
                )
            try:
                rendered_text = self.web.extract_text_from_html(html, base_url=url)
            except Exception:  # noqa: BLE001
                rendered_text = ""
            discovered = discover_document_links(url, html, verify_fn=verify_fn)
            discovered.extend(discover_public_api_hints(url, html, verify_fn=verify_fn))

        return AcquisitionResult(
            url=url,
            content=content,
            content_type=ctype,
            final_url=final_url,
            method=method,
            health=SourceHealth.HEALTHY,
            discovered_links=discovered,
            rendered_text=rendered_text,
        )
