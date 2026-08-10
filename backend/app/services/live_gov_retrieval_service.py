"""Live government information retrieval — FALLBACK only (non-destructive).

Activated ONLY when indexed-KB evidence is insufficient.
Reuses: gov_sources allowlist, WebIngestionService, ingest_raw_bytes,
EvidenceValidator, FAISS/BM25 rebuild. Does not redesign RAG.
"""

from __future__ import annotations

import logging
import re
import time
import uuid
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from app.config.gov_sources import (
    GOV_SOURCES,
    is_allowed_url,
    load_catalog,
    source_category,
)
from app.core.config import settings
from app.models.rag import RagDocument
from app.services.gov_source_registry import (
    classify_query,
    ensure_curated_hosts_merged,
    prioritize_sources_for_query,
)
from app.services.web_ingestion_service import WebIngestionService, compute_hash

logger = logging.getLogger("gramsakhi.live_gov")


def _live_log(request_id: str, event: str, **fields: Any) -> None:
    extras = " ".join(f"{k}={v}" for k, v in fields.items() if v is not None)
    logger.info("live_request_id=%s %s %s", request_id, event, extras)

NO_VERIFIED_INFORMATION = (
    "No verified information was found in the available government sources."
)
LIVE_UNAVAILABLE = (
    "I could not find verified information in the available government sources."
)

# Internal status constants
EXISTING_EVIDENCE_FOUND = "EXISTING_EVIDENCE_FOUND"
LIVE_SEARCH_STARTED = "LIVE_SEARCH_STARTED"
LIVE_CANDIDATE_FOUND = "LIVE_CANDIDATE_FOUND"
LIVE_DOCUMENT_INGESTED = "LIVE_DOCUMENT_INGESTED"
LIVE_EVIDENCE_VALIDATED = "LIVE_EVIDENCE_VALIDATED"
LIVE_EVIDENCE_INSUFFICIENT = "LIVE_EVIDENCE_INSUFFICIENT"
NO_TRUSTED_INFORMATION_FOUND = "NO_TRUSTED_INFORMATION_FOUND"

_INTENT_TERMS = {
    "eligibility",
    "eligible",
    "benefit",
    "benefits",
    "document",
    "documents",
    "apply",
    "application",
    "guideline",
    "guidelines",
    "notification",
    "circular",
    "deadline",
    "criteria",
    "procedure",
    "penalty",
    "penalties",
    "scheme",
    "yojana",
}


def verify_source(url: str) -> bool:
    """Allowlist + SSRF checks before any download."""
    if not url or not isinstance(url, str):
        return False
    lower = url.strip().lower()
    if lower.startswith(("file:", "data:", "ftp:", "javascript:")):
        return False
    return is_allowed_url(url)


def _query_tokens(query: str) -> List[str]:
    return [t for t in re.findall(r"[a-zA-Z0-9\-]{3,}", (query or "").lower())]


def content_relevant_to_query(text: str, query: str) -> bool:
    """Lightweight pre-ingest gate: reject PDFs that share almost no query terms."""
    tokens = [t for t in _query_tokens(query) if len(t) >= 4]
    if not tokens:
        return True
    blob = (text or "").lower()
    if len(blob) < 80:
        return False
    hits = sum(1 for t in tokens if t in blob)
    # Need some real overlap; single generic token is not enough
    return hits >= min(2, max(1, len(tokens) // 3))


def looks_like_gov_scheme_query(query: str) -> bool:
    q = (query or "").lower()
    if any(t in q for t in _INTENT_TERMS):
        return True
    # Scheme aliases from catalog
    for scheme in load_catalog().get("schemes") or []:
        name = (scheme.get("name") or "").lower()
        if name and name in q:
            return True
        for kw in scheme.get("keywords") or []:
            if kw and str(kw).lower() in q:
                return True
    return False


def match_catalog_schemes(query: str) -> List[Dict[str, Any]]:
    """Rank catalog schemes by keyword/name overlap with the query.

    Requires a real name/keyword hit — do not boost every central scheme.
    When the query names a scheme strongly, keep only those matches.
    """
    q = (query or "").lower()
    tokens = set(_query_tokens(query))
    prefer_karnataka = "karnataka" in q or "sevasindhu" in q
    scored: List[Tuple[int, Dict[str, Any]]] = []
    for scheme in load_catalog().get("schemes") or []:
        score = 0
        name = (scheme.get("name") or "").lower()
        if name and name in q:
            score += 20
        # Short aliases / id tokens (e.g. mgnrega, pmfby)
        sid = (scheme.get("id") or "").lower()
        if sid and len(sid) >= 4 and sid in q:
            score += 18
        for kw in scheme.get("keywords") or []:
            k = str(kw).lower()
            if not k:
                continue
            if k in q:
                score += 8
            # Only count token equality for multi-char keywords (avoid noise)
            if " " not in k and len(k) >= 4 and k in tokens:
                score += 3
        scope = (scheme.get("scope") or "").lower()
        if score > 0 and prefer_karnataka and scope == "karnataka":
            score += 5
        if score > 0:
            scored.append((score, scheme))
    scored.sort(key=lambda x: -x[0])
    if not scored:
        return []
    # Strong name/id hit → do not dilute with weakly related schemes
    top = scored[0][0]
    if top >= 18:
        scored = [s for s in scored if s[0] >= 18]
    return [s for _, s in scored]


def score_candidate(url: str, query: str, *, link_text: str = "") -> float:
    """Higher = more relevant PDF/page for this query. Logo/branding docs penalized."""
    if not verify_source(url):
        return -1.0
    blob = f"{url} {link_text}".lower()
    q_tokens = _query_tokens(query)
    score = 0.0
    if blob.endswith(".pdf") or "/pdf" in blob:
        score += 10.0
    for t in q_tokens:
        if t in blob:
            score += 2.0
    for bonus in (
        "guideline",
        "guidelines",
        "eligibility",
        "notification",
        "circular",
        "application",
        "scheme",
        "yojana",
        "benefit",
    ):
        if bonus in blob:
            score += 1.5
    # Irrelevant official docs / HR noise / calendar clutter
    for pen in (
        "logo",
        "brand",
        "icon",
        "banner",
        "favicon",
        "stylesheet",
        "vacancy",
        "advertisement",
        "recruitment",
        "/order-notices/",
        "holiday",
        "holidays-list",
        "calendar",
        "tender",
        "rti-",
    ):
        if pen in blob:
            score -= 20.0
    cat = source_category(url)
    if "karnataka" in (query or "").lower() and cat == "karnataka":
        score += 3.0
    # Prefer URLs that mention schemes named in the query; penalize mismatches
    q_l = (query or "").lower()
    for marker, aliases in (
        ("mgnrega", ("mgnrega", "nrega", "rural.nic", "nrega.nic")),
        ("pmfby", ("pmfby", "fasal", "crop insurance")),
        ("pm-kisan", ("pmkisan", "pm-kisan", "kisan")),
        ("pmay", ("pmay", "awas", "housing")),
    ):
        if marker in q_l or any(a in q_l for a in aliases if len(a) > 4):
            if any(a in blob for a in aliases):
                score += 6.0
            elif marker in q_l and "pmkisan" in blob and marker != "pm-kisan":
                score -= 8.0
    return score


def select_best_candidates(
    candidates: Sequence[Dict[str, Any]],
    query: str,
    *,
    limit: int,
) -> List[Dict[str, Any]]:
    scored = []
    q_tokens = set(_query_tokens(query))
    for c in candidates:
        url = c.get("url") or ""
        s = score_candidate(url, query, link_text=c.get("link_text") or "")
        if s < 0:
            continue
        kind = (c.get("kind") or "").lower()
        blob = f"{url} {c.get('link_text') or ''}".lower()
        # Drop unrelated PDFs (e.g. holiday lists) that share almost no query tokens
        if kind.startswith("pdf"):
            overlap = sum(1 for t in q_tokens if t in blob)
            if overlap == 0 and s < 12:
                continue
        scored.append({**c, "relevance_score": s})
    scored.sort(key=lambda x: -float(x.get("relevance_score") or 0))
    return scored[: max(0, limit)]


def discover_seed_urls(query: str) -> List[Dict[str, Any]]:
    """Staged trusted seeds: catalog → matching registry depts → portal expand.

    Does not crawl every registry site. Expands only up to LIVE_GOV_MAX_SOURCES.
    """
    ensure_curated_hosts_merged()
    seeds: List[Dict[str, Any]] = []
    seen = set()
    schemes = match_catalog_schemes(query)
    max_sources = int(settings.LIVE_GOV_MAX_SOURCES)
    categories = classify_query(query)
    selected_departments: List[str] = []

    # Stage 1–2: scheme catalog URLs (highest precision)
    for scheme in schemes[:max_sources]:
        for url in scheme.get("urls") or []:
            if not verify_source(url) or url in seen:
                continue
            seen.add(url)
            seeds.append(
                {
                    "url": url,
                    "scheme_name": scheme.get("name"),
                    "ministry": scheme.get("ministry"),
                    "state": scheme.get("state"),
                    "scope": scheme.get("scope"),
                    "link_text": scheme.get("name") or "",
                    "stage": "catalog",
                }
            )
            if len(seeds) >= max_sources:
                break
        if len(seeds) >= max_sources:
            break

    # Stage 3: prioritize matching government departments from registry
    # Skip expansion when catalog already supplied a strong scheme match —
    # except Karnataka queries, which should still prefer state portals.
    prefer_karnataka = "karnataka" in (query or "").lower() or "sevasindhu" in (
        query or ""
    ).lower()
    strong_catalog_hit = any(s.get("stage") == "catalog" for s in seeds) and not prefer_karnataka
    if len(seeds) < max_sources and not strong_catalog_hit:
        for src in prioritize_sources_for_query(query, limit=max_sources * 2):
            if len(seeds) >= max_sources:
                break
            selected_departments.append(src.get("name") or src.get("domain") or "")
            for url in src.get("base_urls") or []:
                if not verify_source(url) or url in seen:
                    continue
                seen.add(url)
                seeds.append(
                    {
                        "url": url,
                        "scheme_name": src.get("name"),
                        "ministry": src.get("organization"),
                        "state": src.get("state"),
                        "scope": src.get("level"),
                        "link_text": src.get("name") or "",
                        "stage": "registry_department",
                        "source_id": src.get("id"),
                    }
                )
                break

    # Stage 4: expand via high-level portal sources if still thin
    if len(seeds) < max_sources and (not strong_catalog_hit or prefer_karnataka):
        portals = list(GOV_SOURCES)
        if prefer_karnataka:
            portals = sorted(
                portals, key=lambda p: 0 if p.get("id") == "karnataka" else 1
            )
        for portal in portals:
            url = portal.get("url")
            if not url or not verify_source(url) or url in seen:
                continue
            if len(seeds) >= max_sources:
                break
            seen.add(url)
            seeds.append(
                {
                    "url": url,
                    "scheme_name": portal.get("name"),
                    "state": portal.get("state"),
                    "scope": portal.get("state"),
                    "link_text": portal.get("name") or "",
                    "stage": "portal_expand",
                }
            )

    logger.info(
        "live_seed_discovery query_categories=%s selected_departments=%s seed_count=%s",
        categories,
        selected_departments[:8],
        len(seeds),
    )
    return seeds[:max_sources]


class LiveGovRetrievalService:
    """Orchestrates trusted-source discovery → ingest → index refresh."""

    def __init__(self, db: Session, uploaded_by: Optional[str] = None):
        # Use a dedicated session for live ingest so rollbacks never undo
        # the citizen conversation/message rows on the request session.
        from app.database.session import SessionLocal

        self._owns_session = True
        self.db = SessionLocal()
        self._request_db = db
        self.uploaded_by = uploaded_by
        self.web = WebIngestionService(self.db, uploaded_by=uploaded_by)

    def close(self) -> None:
        if getattr(self, "_owns_session", False) and self.db is not None:
            try:
                self.db.close()
            except Exception:  # noqa: BLE001
                pass

    def discover_sources(self, query: str) -> List[Dict[str, Any]]:
        """Staged trusted seeds for this query (registry + catalog)."""
        return discover_seed_urls(query)

    def classify_query(self, query: str) -> List[str]:
        return classify_query(query)

    def validate_domain(self, url: str) -> bool:
        return verify_source(url)

    def search_sources(self, query: str) -> List[Dict[str, Any]]:
        return self.discover_candidate_pages(query)

    def score_relevance(self, url: str, query: str, *, link_text: str = "") -> float:
        return score_candidate(url, query, link_text=link_text)

    def select_candidate(
        self, candidates: Sequence[Dict[str, Any]], query: str, *, limit: int
    ) -> List[Dict[str, Any]]:
        return select_best_candidates(candidates, query, limit=limit)

    def fetch_page(self, url: str) -> Tuple[Optional[bytes], Optional[str], Optional[str]]:
        if not verify_source(url):
            logger.info("Rejected untrusted URL: %s", url)
            return None, None, "untrusted"
        try:
            # Temporarily tighten timeout via attribute if present
            content, ctype = self.web.fetch_url(url)
            return content, ctype, None
        except Exception as e:  # noqa: BLE001
            logger.warning("fetch_page failed url=%s err=%s", url, type(e).__name__)
            return None, None, str(e)

    def discover_pdf_links(self, base_url: str, html: str) -> List[Dict[str, Any]]:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return []
        soup = BeautifulSoup(html, "html.parser")
        out: List[Dict[str, Any]] = []
        seen = set()
        from urllib.parse import urljoin

        for a in soup.find_all("a", href=True):
            href = (a.get("href") or "").strip()
            if not href:
                continue
            absolute = urljoin(base_url, href).split("#")[0]
            if absolute in seen:
                continue
            if not verify_source(absolute):
                continue
            lower = absolute.lower()
            if not (lower.endswith(".pdf") or "/pdf" in lower):
                continue
            seen.add(absolute)
            out.append(
                {
                    "url": absolute,
                    "link_text": (a.get_text(" ", strip=True) or "")[:200],
                }
            )
        return out

    def discover_candidate_pages(
        self, query: str
    ) -> List[Dict[str, Any]]:
        """Fetch seed pages and collect PDF (+ page) candidates."""
        seeds = discover_seed_urls(query)
        candidates: List[Dict[str, Any]] = []
        for seed in seeds:
            url = seed["url"]
            content, ctype, err = self.fetch_page(url)
            if err or content is None:
                continue
            is_pdf = "pdf" in (ctype or "") or url.lower().endswith(".pdf")
            if is_pdf:
                candidates.append(
                    {
                        **seed,
                        "url": url,
                        "kind": "pdf",
                        "content": content,
                        "content_type": ctype,
                        "link_text": seed.get("link_text") or "",
                    }
                )
                continue
            html = content.decode("utf-8", errors="ignore")
            # Prefer PDFs linked from the page
            pdfs = self.discover_pdf_links(url, html)
            for p in pdfs:
                candidates.append(
                    {
                        **seed,
                        **p,
                        "kind": "pdf_link",
                    }
                )
            # Skip empty JS shells / error pages (common on myScheme)
            text_preview = self.web.extract_text_from_html(html, base_url=url)
            low = (text_preview or "").lower()
            if (
                len(text_preview) < 200
                or "something went wrong" in low
                or "please try again later" in low
            ):
                logger.info("Skipping low-content HTML seed url=%s", url)
                continue
            # Keep HTML page as lower-priority candidate
            candidates.append(
                {
                    **seed,
                    "url": url,
                    "kind": "html",
                    "content": content,
                    "content_type": ctype,
                    "link_text": seed.get("link_text") or "",
                }
            )
        return candidates

    def _find_by_hash(self, document_hash: str) -> Optional[RagDocument]:
        if not document_hash:
            return None
        return (
            self.db.query(RagDocument)
            .filter(RagDocument.document_hash == document_hash)
            .first()
        )

    def ingest_verified_document(
        self,
        *,
        url: str,
        content: bytes,
        content_type: str,
        scheme_name: Optional[str],
        ministry: Optional[str],
        state: Optional[str],
        kind: str,
        live_query: Optional[str] = None,
        live_request_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        rid = live_request_id or "-"
        if not verify_source(url):
            return {"status": "rejected", "reason": "untrusted", "source_url": url}

        max_bytes = int(float(settings.LIVE_GOV_MAX_PDF_SIZE_MB) * 1024 * 1024)
        if len(content) > max_bytes:
            return {"status": "error", "reason": "too_large", "source_url": url}

        document_hash = compute_hash(content)
        existing = self._find_by_hash(document_hash)
        if existing:
            _live_log(
                rid,
                "LIVE_DUPLICATE_DETECTED",
                url=url,
                document_id=str(existing.id),
                document_hash=document_hash[:12],
            )
            return {
                "status": "skipped",
                "reason": "duplicate",
                "source_url": url,
                "document_id": str(existing.id),
                "document_hash": document_hash,
                "scheme_name": existing.scheme_name,
            }

        is_pdf = "pdf" in (content_type or "") or url.lower().endswith(".pdf") or kind.startswith("pdf")
        resolved_state = state or (
            "Karnataka" if source_category(url) == "karnataka" else "India"
        )
        extra_meta = {
            "ingestion_type": "live_web",
            "live_query": (live_query or "")[:500],
            "live_request_id": rid,
        }

        try:
            if is_pdf:
                # Reject empty / non-PDF payloads early
                if not content.startswith(b"%PDF") and b"%PDF" not in content[:1024]:
                    return {
                        "status": "error",
                        "reason": "invalid_pdf",
                        "source_url": url,
                    }
                # Pre-ingest relevance: avoid storing holiday lists / unrelated PDFs
                from app.services.rag import extract_text_from_bytes

                try:
                    pages = extract_text_from_bytes(content, ".pdf")
                    preview = " ".join((p.get("text") or "") for p in pages)[:12000]
                except Exception:  # noqa: BLE001
                    preview = ""
                if live_query and preview and not content_relevant_to_query(preview, live_query):
                    _live_log(
                        rid,
                        "LIVE_PDF_IRRELEVANT",
                        url=url,
                        preview_len=len(preview),
                    )
                    return {
                        "status": "rejected",
                        "reason": "irrelevant_content",
                        "source_url": url,
                    }

                _live_log(
                    rid,
                    "LIVE_INGEST_START",
                    url=url,
                    bytes=len(content),
                    document_hash=document_hash[:12],
                )
                result = self.web._push_to_pipeline(
                    url=url,
                    contents=content,
                    ext=".pdf",
                    document_type="LIVE_PDF",
                    scheme_name=scheme_name,
                    ministry=ministry,
                    state=resolved_state,
                    category="GOVERNMENT_SCHEMES",
                    document_hash=document_hash,
                    ingestion_type="live_web",
                    text_preview=preview[:500] if preview else "",
                    extra_metadata=extra_meta,
                )
            else:
                # HTML → text via existing path
                text = self.web.extract_text_from_html(
                    content.decode("utf-8", errors="ignore"), base_url=url
                )
                if len(text) < 200:
                    return {"status": "error", "reason": "low_content", "source_url": url}
                if live_query and not content_relevant_to_query(text, live_query):
                    return {
                        "status": "rejected",
                        "reason": "irrelevant_content",
                        "source_url": url,
                    }
                # Re-hash normalized text bytes for HTML path consistency with web ingest
                text_bytes = text.encode("utf-8")
                document_hash = compute_hash(text_bytes)
                existing = self._find_by_hash(document_hash)
                if existing:
                    return {
                        "status": "skipped",
                        "reason": "duplicate",
                        "source_url": url,
                        "document_id": str(existing.id),
                        "document_hash": document_hash,
                    }
                _live_log(
                    rid,
                    "LIVE_INGEST_START",
                    url=url,
                    bytes=len(text_bytes),
                    document_hash=document_hash[:12],
                )
                result = self.web._push_to_pipeline(
                    url=url,
                    contents=text_bytes,
                    ext=".txt",
                    document_type="LIVE_HTML",
                    scheme_name=scheme_name,
                    ministry=ministry,
                    state=resolved_state,
                    category="GOVERNMENT_SCHEMES",
                    document_hash=document_hash,
                    text_preview=text[:500],
                    ingestion_type="live_web",
                    extra_metadata=extra_meta,
                )
        except Exception as e:  # noqa: BLE001
            try:
                self.db.rollback()
            except Exception:  # noqa: BLE001
                pass
            logger.warning(
                "live ingest exception url=%s err=%s", url, type(e).__name__
            )
            return {
                "status": "error",
                "reason": "ingest_exception",
                "source_url": url,
                "detail": str(e)[:200],
            }

        if result.get("status") == "error":
            try:
                self.db.rollback()
            except Exception:  # noqa: BLE001
                pass
            return result

        # Ensure live_web tag is present in document metadata path
        if result.get("status") == "ok":
            result["ingestion_type"] = "live_web"
        return result

    def refresh_indexes(self, *, live_request_id: str = "-") -> Dict[str, Any]:
        from app.services.index_builder import IndexBuilder, set_index_builder

        builder = IndexBuilder()
        stats = builder.build_all(self.db)
        set_index_builder(builder)
        _live_log(
            live_request_id,
            "LIVE_INDEX_REBUILT",
            chunk_count=stats.get("chunk_count"),
            faiss=stats.get("faiss"),
            bm25=stats.get("bm25"),
            index_dir=stats.get("index_dir"),
        )
        return stats

    def _probe_evidence_ready(self, query: str, *, live_request_id: str) -> bool:
        """After ingest+index: does existing hybrid+validator PASS for this query?"""
        try:
            from app.services.evidence_validator import EvidenceValidator
            from app.services.rag import hybrid_retrieve

            docs = hybrid_retrieve(self.db, query, top_k=int(settings.HYBRID_TOP_K))
            result = EvidenceValidator().validate(query, docs)
            _live_log(
                live_request_id,
                "LIVE_EVIDENCE_PROBE",
                ok=result.ok,
                reason=result.reason,
                doc_count=len(docs),
            )
            return bool(result.ok)
        except Exception as e:  # noqa: BLE001
            _live_log(
                live_request_id,
                "LIVE_EVIDENCE_PROBE_ERROR",
                err=type(e).__name__,
            )
            return False

    def search_government_sources(
        self,
        query: str,
        *,
        language: Optional[str] = None,
        conversation_context: Any = None,
        live_request_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Discover + ingest relevant trusted government documents for `query`.

        Does NOT call Ollama. Caller must re-run Evidence Validator + RAG.
        Success means at least one ingest that makes evidence probe PASS.
        """
        _ = language, conversation_context
        rid = live_request_id or str(uuid.uuid4())
        started = time.perf_counter()
        overall_deadline = started + float(settings.LIVE_GOV_OVERALL_TIMEOUT_SECONDS)

        if not looks_like_gov_scheme_query(query):
            _live_log(rid, "LIVE_SKIP_NOT_SCHEME_QUERY")
            return {
                "status": NO_TRUSTED_INFORMATION_FOUND,
                "ingested": [],
                "candidates_tried": 0,
                "live_request_id": rid,
                "latency_ms": int((time.perf_counter() - started) * 1000),
            }

        categories = classify_query(query)
        _live_log(
            rid,
            "LIVE_FALLBACK_START",
            query=(query or "")[:200],
            source_category=categories,
            live_fallback_enabled=settings.LIVE_GOV_FALLBACK_ENABLED,
        )
        status = LIVE_SEARCH_STARTED
        rejected_urls: List[str] = []
        accepted_url: Optional[str] = None
        evidence_ready = False
        index_stats: Dict[str, Any] = {}
        try:
            raw_candidates = self.discover_candidate_pages(query)
        except Exception as e:  # noqa: BLE001
            _live_log(rid, "LIVE_SOURCE_SEARCH_FAILED", err=type(e).__name__)
            return {
                "status": NO_TRUSTED_INFORMATION_FOUND,
                "detail": LIVE_UNAVAILABLE,
                "ingested": [],
                "live_request_id": rid,
                "latency_ms": int((time.perf_counter() - started) * 1000),
            }

        ranked = select_best_candidates(
            raw_candidates,
            query,
            limit=int(settings.LIVE_GOV_MAX_CANDIDATES),
        )
        candidate_urls = [c.get("url") for c in ranked if c.get("url")]
        _live_log(
            rid,
            "LIVE_SOURCE_SEARCH",
            candidates=len(ranked),
            candidate_urls=candidate_urls[:12],
        )
        if not ranked:
            return {
                "status": NO_TRUSTED_INFORMATION_FOUND,
                "ingested": [],
                "live_request_id": rid,
                "latency_ms": int((time.perf_counter() - started) * 1000),
            }

        status = LIVE_CANDIDATE_FOUND
        ingested: List[Dict[str, Any]] = []
        pdfs_used = 0
        max_pdfs = int(settings.LIVE_GOV_MAX_PDFS)

        for cand in ranked:
            if time.perf_counter() > overall_deadline:
                _live_log(rid, "LIVE_OVERALL_TIMEOUT")
                break
            url = cand.get("url") or ""
            if not verify_source(url):
                rejected_urls.append(url)
                continue

            kind = cand.get("kind") or "html"
            content = cand.get("content")
            ctype = cand.get("content_type") or ""

            if content is None:
                content, ctype, err = self.fetch_page(url)
                if err or content is None:
                    rejected_urls.append(url)
                    continue

            is_pdf = (
                kind.startswith("pdf")
                or "pdf" in (ctype or "")
                or url.lower().endswith(".pdf")
            )
            if is_pdf:
                if pdfs_used >= max_pdfs:
                    continue
                pdfs_used += 1
                _live_log(
                    rid,
                    "LIVE_PDF_DOWNLOADED",
                    url=url,
                    bytes=len(content or b""),
                    content_type=ctype,
                )

            result = self.ingest_verified_document(
                url=url,
                content=content,
                content_type=ctype or ("application/pdf" if is_pdf else "text/html"),
                scheme_name=cand.get("scheme_name"),
                ministry=cand.get("ministry"),
                state=cand.get("state"),
                kind=kind,
                live_query=query,
                live_request_id=rid,
            )
            if result.get("status") in ("rejected", "error"):
                rejected_urls.append(url)
                _live_log(
                    rid,
                    "LIVE_INGEST_FAILED",
                    url=url,
                    reason=result.get("reason") or result.get("detail"),
                )
                continue
            if result.get("reason") == "duplicate":
                _live_log(rid, "LIVE_DUPLICATE_REUSED", url=url)

            if result.get("status") in ("ok", "skipped"):
                ingested.append(result)
                accepted_url = url
                if result.get("status") == "ok":
                    status = LIVE_DOCUMENT_INGESTED
                    _live_log(
                        rid,
                        "LIVE_RAG_DOCUMENT_CREATED",
                        document_id=result.get("document_id"),
                        chunk_count=result.get("chunk_count"),
                        url=url,
                    )

                # Rebuild indexes and probe — only stop when evidence would PASS
                try:
                    index_stats = self.refresh_indexes(live_request_id=rid)
                except Exception as e:  # noqa: BLE001
                    _live_log(rid, "LIVE_INDEX_FAILED", err=type(e).__name__)
                    index_stats = {"error": str(e)}
                    continue

                if self._probe_evidence_ready(query, live_request_id=rid):
                    evidence_ready = True
                    _live_log(rid, "LIVE_SECOND_RETRIEVAL_READY", url=url)
                    break
                # Wrong/insufficient document — try next candidate
                _live_log(rid, "LIVE_PROBE_INSUFFICIENT_TRY_NEXT", url=url)

        latency_ms = int((time.perf_counter() - started) * 1000)
        _live_log(
            rid,
            "LIVE_FALLBACK_SUMMARY",
            accepted_url=accepted_url,
            rejected=len(rejected_urls),
            evidence_ready=evidence_ready,
            latency_ms=latency_ms,
        )
        if not ingested:
            return {
                "status": NO_TRUSTED_INFORMATION_FOUND,
                "ingested": [],
                "candidates_tried": len(ranked),
                "rejected_urls": rejected_urls,
                "live_request_id": rid,
                "latency_ms": latency_ms,
            }

        # If we ingested but never rebuilt (edge), rebuild once
        if not index_stats:
            try:
                index_stats = self.refresh_indexes(live_request_id=rid)
            except Exception as e:  # noqa: BLE001
                index_stats = {"error": str(e)}

        return {
            "status": status if evidence_ready or ingested else NO_TRUSTED_INFORMATION_FOUND,
            "ingested": ingested,
            "candidates_tried": len(ranked),
            "accepted_url": accepted_url,
            "rejected_urls": rejected_urls,
            "index_stats": index_stats,
            "evidence_ready": evidence_ready,
            "live_request_id": rid,
            "latency_ms": latency_ms,
        }


def try_live_gov_fallback(
    db: Session,
    query: str,
    *,
    language: Optional[str] = None,
    conversation_context: Any = None,
    uploaded_by: Optional[str] = None,
) -> Dict[str, Any]:
    """Public entry used by the RAG gate after indexed evidence FAIL."""
    if not settings.LIVE_GOV_FALLBACK_ENABLED:
        return {
            "status": NO_TRUSTED_INFORMATION_FOUND,
            "ingested": [],
            "skipped": True,
            "live_request_id": None,
        }
    rid = str(uuid.uuid4())
    svc = LiveGovRetrievalService(db, uploaded_by=uploaded_by)
    try:
        return svc.search_government_sources(
            query,
            language=language,
            conversation_context=conversation_context,
            live_request_id=rid,
        )
    finally:
        svc.close()
