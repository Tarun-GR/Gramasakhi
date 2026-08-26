"""
Government website ingestion — data-source layer only (hardened).

Fetches allowlisted central/state pages and PDFs, then hands content to the
existing RAG ingest entry point (chunk → embed → index). Does not implement
retrieval, embeddings, FAISS, BM25, CrossEncoder, or LLM logic.
"""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.config.gov_sources import (
    GOV_SOURCES,
    is_allowed_url,
    list_catalog_schemes,
    load_catalog,
    schemes_for_source,
)
from app.models.rag import RagDocument, DocumentChunk
from app.services import rag as rag_service

logger = logging.getLogger("gramsakhi.web_ingestion")

USER_AGENT = (
    "GramSakhiBot/1.0 (+local research; respectful crawler; contact=local)"
)
MAX_BYTES = 15 * 1024 * 1024
FETCH_TIMEOUT = 30.0
# Reject weak / JS-shell HTML pages from entering the RAG corpus
MIN_HTML_CHARS = 500

CATEGORY_KEYWORDS = {
    "ELIGIBILITY": ("eligible", "eligibility", "who can apply", "criteria"),
    "APPLICATION": ("how to apply", "application", "apply online", "registration"),
    "BENEFITS": ("benefit", "benefits", "entitlement", "amount", "assistance"),
}


def compute_hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _normalize_text(text: str) -> str:
    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _host(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


def extract_scheme_name(raw: Dict[str, Any]) -> str:
    if raw.get("scheme_name"):
        return str(raw["scheme_name"]).strip()
    title = (raw.get("title") or "").strip()
    if title:
        return title
    url = raw.get("url") or ""
    stub = (urlparse(url).path or "scheme").strip("/").replace("/", " ")
    return stub[:120] or "Unknown Scheme"


def extract_state(raw: Dict[str, Any]) -> str:
    if raw.get("state"):
        return str(raw["state"]).strip()
    url = (raw.get("url") or "").lower()
    if "karnataka" in url:
        return "Karnataka"
    return "India"


def classify_scheme(raw: Dict[str, Any]) -> str:
    if raw.get("category"):
        return str(raw["category"]).strip()
    blob = " ".join(
        [
            str(raw.get("scheme_name") or ""),
            str(raw.get("title") or ""),
            str(raw.get("text_preview") or ""),
            str(raw.get("url") or ""),
        ]
    ).lower()
    for category, keys in CATEGORY_KEYWORDS.items():
        if any(k in blob for k in keys):
            return category
    return "GOVERNMENT_SCHEMES"


def normalize_metadata(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize web-ingest metadata for documents and chunks."""
    url = raw.get("url") or raw.get("source") or ""
    scheme_name = extract_scheme_name(raw)
    state = extract_state(raw)
    category = classify_scheme(raw)
    document_hash = raw.get("document_hash") or raw.get("version_hash")
    meta = {
        "scheme_name": scheme_name,
        "state": state,
        "category": category,
        "source": url,
        "ingestion_type": raw.get("ingestion_type") or "web",
        "ministry": raw.get("ministry"),
        "document_hash": document_hash,
        "version_hash": document_hash,
        "last_ingested_at": raw.get("last_ingested_at")
        or datetime.now(timezone.utc).isoformat(),
    }
    if raw.get("page") is not None:
        meta["page"] = raw["page"]
    return {k: v for k, v in meta.items() if v is not None}


class WebIngestionService:
    """Pluggable web → existing RAG ingest adapter (hardened)."""

    def __init__(self, db: Session, uploaded_by: Optional[str] = None):
        self.db = db
        self.uploaded_by = uploaded_by

    # ------------------------------------------------------------------ fetch
    def fetch_url(self, url: str) -> Tuple[bytes, str]:
        if not is_allowed_url(url):
            raise HTTPException(
                status_code=400,
                detail=(
                    "URL not allowed. Only Karnataka (.karnataka.gov.in) "
                    f"and curated central gov hosts: {url}"
                ),
            )

        try:
            import httpx
        except ImportError as e:
            raise HTTPException(
                status_code=500,
                detail="httpx is required for web ingestion. pip install httpx",
            ) from e

        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/pdf,*/*;q=0.8",
            "Accept-Language": "en-IN,en;q=0.9,kn;q=0.8,hi;q=0.7",
        }

        # Prefer configured per-source timeout when available
        try:
            from app.core.config import settings as _settings

            timeout = float(getattr(_settings, "LIVE_GOV_TIMEOUT_SECONDS", FETCH_TIMEOUT))
        except Exception:  # noqa: BLE001
            timeout = FETCH_TIMEOUT

        def _get(verify: bool) -> Tuple[bytes, str]:
            import time as _time

            last_exc: Optional[Exception] = None
            for attempt in range(3):
                try:
                    with httpx.Client(
                        follow_redirects=True, timeout=timeout, verify=verify
                    ) as client:
                        resp = client.get(url, headers=headers)
                        # Bounded retry only for transient upstream failures
                        if resp.status_code in (429, 502, 503, 504):
                            if attempt < 2:
                                _time.sleep(0.4 * (2**attempt))
                                continue
                            resp.raise_for_status()
                        resp.raise_for_status()
                        final_url = str(resp.url)
                        if not is_allowed_url(final_url):
                            raise HTTPException(
                                status_code=400,
                                detail=(
                                    "Redirect target is not a trusted government source: "
                                    f"{final_url}"
                                ),
                            )
                        content = resp.content
                        if len(content) > MAX_BYTES:
                            raise HTTPException(
                                status_code=413, detail=f"Remote file too large: {url}"
                            )
                        ctype = (
                            (resp.headers.get("content-type") or "")
                            .split(";")[0]
                            .strip()
                            .lower()
                        )
                        if not ctype and url.lower().endswith(".pdf"):
                            ctype = "application/pdf"
                        return content, ctype or "application/octet-stream"
                except HTTPException:
                    raise
                except Exception as e:  # noqa: BLE001
                    last_exc = e
                    msg = str(e).lower()
                    transient = any(
                        tok in msg for tok in ("429", "502", "503", "504", "timeout", "timed out")
                    )
                    if transient and attempt < 2:
                        _time.sleep(0.4 * (2**attempt))
                        continue
                    raise
            raise HTTPException(
                status_code=502, detail=f"Could not fetch {url}: {last_exc}"
            )

        try:
            content, ctype = _get(verify=True)
            logger.info("Fetched URL %s (%s, %s bytes)", url, ctype, len(content))
            return content, ctype
        except HTTPException:
            raise
        except Exception as e:
            err_s = str(e).lower()
            if "certificate" in err_s or "ssl" in err_s:
                try:
                    logger.warning("Retrying fetch with SSL verify disabled: %s", url)
                    content, ctype = _get(verify=False)
                    logger.info("Fetched URL %s (ssl-relaxed, %s bytes)", url, len(content))
                    return content, ctype
                except HTTPException:
                    raise
                except Exception as e2:
                    raise HTTPException(
                        status_code=502, detail=f"Could not fetch {url}: {e2}"
                    ) from e2
            raise HTTPException(status_code=502, detail=f"Could not fetch {url}: {e}") from e

    # --------------------------------------------------------------- extract
    def extract_links(self, base_url: str, html: str) -> List[str]:
        try:
            from bs4 import BeautifulSoup
        except ImportError as e:
            raise HTTPException(
                status_code=500,
                detail="beautifulsoup4 is required for web ingestion. pip install beautifulsoup4",
            ) from e

        soup = BeautifulSoup(html, "html.parser")
        links: List[str] = []
        for a in soup.find_all("a", href=True):
            href = (a.get("href") or "").strip()
            if not href or href.startswith("#") or href.startswith("mailto:"):
                continue
            absolute = urljoin(base_url, href)
            if is_allowed_url(absolute):
                links.append(absolute.split("#")[0])
        seen = set()
        out = []
        for u in links:
            if u not in seen:
                seen.add(u)
                out.append(u)
        return out

    def extract_pdf_links(self, base_url: str, html: str) -> List[str]:
        links = self.extract_links(base_url, html)
        return [
            u
            for u in links
            if u.lower().endswith(".pdf") or "/pdf" in u.lower()
        ]

    def filter_relevant_documents(self, links: List[str], *, limit: int = 10) -> List[str]:
        """Prefer PDFs first, then scheme-like HTML paths."""
        scored: List[Tuple[int, str]] = []
        for url in links:
            if not is_allowed_url(url):
                continue
            score = 0
            lower = url.lower()
            if lower.endswith(".pdf") or "/pdf" in lower:
                score += 10
            if any(k in lower for k in ("scheme", "yojana", "guideline", "circular", "policy")):
                score += 3
            if "myscheme.gov.in/schemes/" in lower:
                score += 4
            scored.append((score, url))
        scored.sort(key=lambda x: (-x[0], x[1]))
        return [u for _, u in scored[:limit]]

    def download_documents(self, links: List[str]) -> List[Dict[str, Any]]:
        results = []
        for url in links:
            try:
                content, ctype = self.fetch_url(url)
                results.append(
                    {"url": url, "content": content, "content_type": ctype, "status": "ok"}
                )
            except Exception as e:
                results.append({"url": url, "status": "error", "detail": str(e)})
        return results

    def extract_text_from_html(self, html: str, base_url: str = "") -> str:
        try:
            from bs4 import BeautifulSoup
        except ImportError as e:
            raise HTTPException(
                status_code=500,
                detail="beautifulsoup4 is required for web ingestion. pip install beautifulsoup4",
            ) from e

        soup = BeautifulSoup(html, "html.parser")

        # Preserve tables before stripping structure
        try:
            from app.services.myscheme_service import extract_tables_as_text

            table_text = extract_tables_as_text(html)
        except Exception:
            table_text = ""

        for tag in soup(["script", "style", "noscript", "svg", "iframe", "nav", "footer"]):
            tag.decompose()

        title = ""
        if soup.title and soup.title.string:
            title = _normalize_text(soup.title.string)

        blocks = []
        for root in (
            soup.find("main"),
            soup.find("article"),
            soup.find(id="content"),
            soup.find(id="main"),
            soup.find(class_="content"),
            soup.find(attrs={"role": "main"}),
            soup.body,
            soup,
        ):
            if root is None:
                continue
            blocks.append(_normalize_text(root.get_text("\n", strip=True)))

        joined = max(blocks, key=len) if blocks else ""
        if table_text:
            joined = f"{joined}\n\n{table_text}".strip() if joined else table_text
        if title and title not in joined:
            joined = f"{title}\n\n{joined}"
        if base_url:
            joined = f"Source URL: {base_url}\n\n{joined}"
        return _normalize_text(joined)

    def normalize_text(self, text: str) -> str:
        return _normalize_text(text)

    def extract_text(self, content: bytes, content_type: str, url: str) -> Tuple[str, str]:
        is_pdf = "pdf" in (content_type or "") or url.lower().endswith(".pdf")
        if is_pdf:
            return "", ".pdf"
        html = content.decode("utf-8", errors="ignore")
        return self.extract_text_from_html(html, base_url=url), ".txt"

    # ----------------------------------------------------- deduplication
    def hash_exists(self, document_hash: str) -> bool:
        if not document_hash:
            return False
        existing = (
            self.db.query(RagDocument)
            .filter(RagDocument.document_hash == document_hash)
            .first()
        )
        if existing:
            return True
        # Legacy rows: hash may only live in chunk metadata
        chunks = self.db.query(DocumentChunk).limit(5000).all()
        for chunk in chunks:
            meta = chunk.metadata_dict or {}
            if meta.get("document_hash") == document_hash or meta.get("content_hash") == document_hash:
                return True
        return False

    def _already_ingested(self, source_url: str, document_hash: str) -> bool:
        if self.hash_exists(document_hash):
            return True
        if not source_url:
            return False
        docs = (
            self.db.query(RagDocument)
            .filter(RagDocument.source == source_url, RagDocument.indexing_status == "INDEXED")
            .all()
        )
        for doc in docs:
            if doc.document_hash and doc.document_hash == document_hash:
                return True
            # Same source + same hash already seen
            for chunk in doc.chunks or []:
                meta = chunk.metadata_dict or {}
                if meta.get("document_hash") == document_hash or meta.get("content_hash") == document_hash:
                    return True
        return False

    def _push_to_pipeline(
        self,
        *,
        url: str,
        contents: bytes,
        ext: str,
        document_type: str,
        scheme_name: Optional[str],
        ministry: Optional[str],
        state: Optional[str],
        category: str,
        document_hash: str,
        page: Optional[int] = None,
        text_preview: str = "",
        ingestion_type: Optional[str] = None,
        extra_metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        now_iso = datetime.now(timezone.utc).isoformat()
        meta = normalize_metadata(
            {
                "url": url,
                "scheme_name": scheme_name,
                "ministry": ministry,
                "state": state,
                "category": category,
                "document_hash": document_hash,
                "last_ingested_at": now_iso,
                "text_preview": text_preview[:500],
                "page": page,
                "ingestion_type": ingestion_type or "web",
            }
        )
        if extra_metadata:
            meta.update({k: v for k, v in extra_metadata.items() if v is not None})
        try:
            doc = rag_service.ingest_raw_bytes(
                db=self.db,
                uploaded_by=self.uploaded_by,
                title=meta["scheme_name"],
                category=meta["category"],
                version="1.0",
                contents=contents,
                ext=ext,
                scheme_name=meta["scheme_name"],
                ministry=ministry,
                state=meta["state"],
                source=meta["source"],
                language=None,
                document_type=document_type,
                document_hash=document_hash,
                extra_metadata=meta,
            )
            chunk_count = (
                self.db.query(DocumentChunk)
                .filter(DocumentChunk.document_id == doc.id)
                .count()
            )
            logger.info(
                "Ingested successfully url=%s doc_id=%s chunks=%s hash=%s",
                url,
                doc.id,
                chunk_count,
                document_hash[:12],
            )
            return {
                "status": "ok",
                "document_id": doc.id,
                "source_url": url,
                "scheme_name": doc.scheme_name,
                "state": doc.state,
                "document_hash": document_hash,
                "chunk_count": chunk_count,
                "indexing_status": doc.indexing_status,
                "last_ingested_at": now_iso,
            }
        except HTTPException as e:
            logger.error("Ingest failed url=%s detail=%s", url, e.detail)
            return {"status": "error", "source_url": url, "detail": e.detail}
        except Exception as e:
            logger.exception("Ingest failed url=%s", url)
            return {"status": "error", "source_url": url, "detail": str(e)}

    # --------------------------------------------------------- single URL
    def ingest_single_url(
        self,
        url: str,
        *,
        scheme_name: Optional[str] = None,
        ministry: Optional[str] = None,
        state: Optional[str] = None,
        category: str = "GOVERNMENT_SCHEMES",
        crawl_links: bool = False,
        max_extra_links: int = 0,
    ) -> Dict[str, Any]:
        try:
            content, ctype = self.fetch_url(url)
        except HTTPException as e:
            return {"status": "error", "source_url": url, "detail": e.detail}

        is_pdf = "pdf" in (ctype or "") or url.lower().endswith(".pdf")

        if is_pdf:
            document_hash = compute_hash(content)
            if self._already_ingested(url, document_hash):
                logger.info("Skipped duplicate url=%s hash=%s", url, document_hash[:12])
                return {
                    "status": "skipped",
                    "reason": "duplicate",
                    "source_url": url,
                    "document_hash": document_hash,
                }
            preview_pages = rag_service.extract_text_from_bytes(content, ".pdf")
            joined = "\n".join(p.get("text", "") for p in preview_pages)
            if len(joined.strip()) < 50:
                logger.info("Skipped low content PDF url=%s", url)
                return {
                    "status": "skipped",
                    "reason": "low_content",
                    "source_url": url,
                    "detail": "PDF contained too little extractable text.",
                }
            return self._push_to_pipeline(
                url=url,
                contents=content,
                ext=".pdf",
                document_type="PDF",
                scheme_name=scheme_name,
                ministry=ministry,
                state=state,
                category=category,
                document_hash=document_hash,
                text_preview=joined,
            )

        # HTML path — PDF-first strategy
        html = content.decode("utf-8", errors="ignore")
        pdf_links = self.extract_pdf_links(url, html)
        linked_results: List[Dict[str, Any]] = []

        if pdf_links:
            prioritized = self.filter_relevant_documents(pdf_links, limit=max(1, max_extra_links or 3))
            logger.info("PDF-first: found %s PDF links on %s", len(prioritized), url)
            for pdf_url in prioritized:
                linked_results.append(
                    self.ingest_single_url(
                        pdf_url,
                        scheme_name=scheme_name,
                        ministry=ministry,
                        state=state,
                        category=category,
                        crawl_links=False,
                    )
                )
            pdf_ok = any(r.get("status") == "ok" for r in linked_results)
            if pdf_ok:
                # Prefer PDFs; do not also index weak HTML shells
                logger.info("PDF preferred over HTML for %s", url)
                return {
                    "status": "ok",
                    "source_url": url,
                    "strategy": "pdf_first",
                    "linked_documents": linked_results,
                    "html_ingested": False,
                }

        # Fallback: HTML text if quality is sufficient
        text = self.extract_text_from_html(html, base_url=url)
        if len(text.strip()) < MIN_HTML_CHARS:
            logger.info(
                "Skipped low content HTML url=%s chars=%s", url, len(text.strip())
            )
            result = {
                "status": "skipped",
                "reason": "low_content",
                "source_url": url,
                "detail": (
                    f"HTML text below quality threshold ({MIN_HTML_CHARS} chars). "
                    "Prefer a PDF or richer static page."
                ),
            }
            if linked_results:
                result["linked_documents"] = linked_results
            return result

        document_hash = compute_hash(text.encode("utf-8"))
        if self._already_ingested(url, document_hash):
            logger.info("Skipped duplicate url=%s hash=%s", url, document_hash[:12])
            return {
                "status": "skipped",
                "reason": "duplicate",
                "source_url": url,
                "document_hash": document_hash,
            }

        primary = self._push_to_pipeline(
            url=url,
            contents=text.encode("utf-8"),
            ext=".txt",
            document_type="HTML",
            scheme_name=scheme_name,
            ministry=ministry,
            state=state,
            category=category,
            document_hash=document_hash,
            page=1,
            text_preview=text,
        )

        # Optional: also crawl PDF links when explicitly requested and none succeeded yet
        if crawl_links and max_extra_links > 0 and not linked_results:
            for pdf_url in self.filter_relevant_documents(
                self.extract_pdf_links(url, html), limit=max_extra_links
            ):
                linked_results.append(
                    self.ingest_single_url(
                        pdf_url,
                        scheme_name=scheme_name,
                        ministry=ministry,
                        state=state,
                        category=category,
                        crawl_links=False,
                    )
                )
        if linked_results:
            primary["linked_documents"] = linked_results
        return primary

    # ----------------------------------------------------- source / catalog
    def ingest_source(
        self,
        source: str,
        *,
        max_docs: int = 5,
        query: Optional[str] = None,
        urls: Optional[List[str]] = None,
        crawl_links: bool = False,
    ) -> Dict[str, Any]:
        source_key = (source or "").strip().lower()
        work: List[Dict[str, Any]] = []
        seen = set()

        for url in urls or []:
            url = (url or "").strip()
            if not url or url in seen:
                continue
            if not is_allowed_url(url):
                continue
            seen.add(url)
            work.append(
                {
                    "url": url,
                    "scheme_name": None,
                    "ministry": None,
                    "state": "Karnataka" if "karnataka" in _host(url) else "India",
                }
            )

        schemes = schemes_for_source(source_key)
        if not schemes:
            for s in load_catalog().get("schemes", []):
                if (s.get("id") or "").lower() == source_key:
                    schemes = [s]
                    break

        if query:
            q = query.lower()
            filtered = []
            for s in schemes:
                blob = " ".join(
                    [
                        str(s.get("id") or ""),
                        str(s.get("name") or ""),
                        " ".join(s.get("keywords") or []),
                    ]
                ).lower()
                if q in blob or any(tok in blob for tok in re.findall(r"[a-z0-9-]{3,}", q)):
                    filtered.append(s)
            schemes = filtered or schemes

        for scheme in schemes:
            for url in scheme.get("urls") or []:
                if url in seen:
                    continue
                seen.add(url)
                work.append(
                    {
                        "url": url,
                        "scheme_name": scheme.get("name"),
                        "ministry": scheme.get("ministry"),
                        "state": scheme.get("state")
                        or ("Karnataka" if scheme.get("scope") == "karnataka" else "India"),
                    }
                )

        if not work:
            known = [s["id"] for s in GOV_SOURCES] + [
                s.get("id") for s in list_catalog_schemes()
            ]
            raise HTTPException(
                status_code=404,
                detail=(
                    f"No schemes/URLs matched source={source!r}. "
                    f"Try source=central|karnataka or a catalog id. Known: {known[:20]}..."
                ),
            )

        results = []
        for item in work[: max(1, max_docs)]:
            results.append(
                self.ingest_single_url(
                    item["url"],
                    scheme_name=item.get("scheme_name"),
                    ministry=item.get("ministry"),
                    state=item.get("state"),
                    crawl_links=crawl_links,
                    max_extra_links=3 if crawl_links else 0,
                )
            )

        ok = sum(1 for r in results if r.get("status") == "ok")
        skipped = sum(1 for r in results if r.get("status") == "skipped")
        errors = sum(1 for r in results if r.get("status") == "error")

        return {
            "source": source_key,
            "query": query,
            "summary": {
                "ok": ok,
                "skipped": skipped,
                "errors": errors,
                "attempted": len(results),
            },
            "results": results,
        }
