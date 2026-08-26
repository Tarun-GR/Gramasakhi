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


# Minimal Kn/Hi -> English aliases for live discovery (answer language unchanged)
_LANG_ALIASES: Tuple[Tuple[str, str], ...] = (
    ("ಆಯುಷ್ಮಾನ್", "ayushman"),
    ("ಪಿಎಂ ಕಿಸಾನ್", "pm-kisan"),
    ("ಪಿಎಂಕಿಸಾನ್", "pm-kisan"),
    ("ಗೃಹ ಲಕ್ಷ್ಮಿ", "gruha lakshmi"),
    ("ಗೃಹಲಕ್ಷ್ಮಿ", "gruha lakshmi"),
    ("ಅನ್ನ ಭಾಗ್ಯ", "anna bhagya"),
    ("ಅನ್ನಭಾಗ್ಯ", "anna bhagya"),
    ("ಉದ್ಯೋಗಿನಿ", "udyogini"),
    ("उद्योगिनी", "udyogini"),
    ("आयुष्मान", "ayushman"),
    ("पीएम किसान", "pm-kisan"),
    ("गृह लक्ष्मी", "gruha lakshmi"),
    ("अन्न भाग्य", "anna bhagya"),
    ("योजना", "scheme"),
    ("ಪ್ರಯೋಜನ", "benefits"),
    ("ಅರ್ಹತೆ", "eligibility"),
    ("पात्रता", "eligibility"),
    ("लाभ", "benefits"),
    ("दस्तावेज", "documents"),
)

_FRESHNESS_TERMS = (
    "latest",
    "current",
    "today",
    "now",
    "updated",
    "new rules",
    "current eligibility",
    "current benefit",
    "deadline",
    "application deadline",
    "2025",
    "2026",
    "recent",
)


def expand_search_query(query: str) -> str:
    """Append English aliases for Kannada/Hindi tokens used in source discovery."""
    # Prefer shared multilingual bridge (retrieval-only expansion).
    try:
        from app.services.multilingual_retrieval_service import expand_for_live_search

        bridged = expand_for_live_search(query)
        if bridged and bridged.strip() and bridged.strip() != (query or "").strip():
            return bridged
    except Exception:
        pass
    q = query or ""
    extras: List[str] = []
    for src, eng in _LANG_ALIASES:
        if src in q and eng not in q.lower():
            extras.append(eng)
    if not extras:
        return q
    return f"{q} {' '.join(extras)}"


def is_freshness_sensitive(query: str) -> bool:
    q = (query or "").lower()
    return any(t in q for t in _FRESHNESS_TERMS)


def content_relevant_to_query(text: str, query: str) -> bool:
    """Lightweight pre-ingest gate: reject PDFs that share almost no query terms."""
    tokens = [t for t in _query_tokens(query) if len(t) >= 4]
    if not tokens:
        return True
    blob = (text or "").lower()
    if len(blob) < 80:
        return False
    # Packaged myScheme evidence: scheme identity in the blob is sufficient.
    try:
        from app.services.myscheme_service import (
            extract_scheme_name_hint,
            normalize_scheme_key,
            slug_hint_from_query,
        )

        hint = normalize_scheme_key(extract_scheme_name_hint(query) or "")
        sid = (slug_hint_from_query(query) or "").lower()
        blob_key = normalize_scheme_key(blob)
        if hint and len(hint) >= 4 and hint in blob_key:
            return True
        if sid and (f"scheme_id:\n{sid}" in blob or f"/schemes/{sid}" in blob):
            return True
    except Exception:
        pass
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


def score_candidate(url: str, query: str, *, link_text: str = "", kind: str = "") -> float:
    """Higher = more relevant PDF/page for this query. Logo/branding docs penalized."""
    if not verify_source(url):
        return -1.0
    blob = f"{url} {link_text} {kind}".lower()
    q_tokens = _query_tokens(query)
    score = 0.0
    if blob.endswith(".pdf") or "/pdf" in blob:
        score += 10.0
    # Prefer myScheme scheme detail pages over bare portal homes
    if "myscheme.gov.in/schemes/" in blob:
        score += 14.0
    if kind in ("scheme_page", "html") and "myscheme.gov.in" in blob:
        score += 4.0
    if kind == "public_api":
        score += 5.0
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
        "refund",
        "mechanism",
        "grievance",
        "faq",
    ):
        if bonus in blob:
            score += 1.5
    # Strong intent alignment: query asks about refunds → prefer refund PDFs
    q_l = (query or "").lower()
    if "refund" in q_l and "refund" in blob:
        score += 16.0
    if "grievance" in q_l and "grievance" in blob:
        score += 12.0
    if "mechanism" in q_l and "mechanism" in blob:
        score += 6.0
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
        "press-release",
        "unrelated",
    ):
        if pen in blob:
            score -= 20.0
    # Homepage chrome alone is weak evidence
    path = (urlparse(url).path or "").strip("/")
    if not path or path.lower() in ("index", "index.php", "home", "default.aspx"):
        score -= 4.0
    cat = source_category(url)
    if "karnataka" in (query or "").lower() and cat == "karnataka":
        score += 3.0
    # Prefer URLs that mention schemes named in the query; penalize mismatches
    for marker, aliases in (
        ("mgnrega", ("mgnrega", "nrega", "rural.nic", "nrega.nic")),
        ("pmfby", ("pmfby", "fasal", "crop insurance")),
        ("pm-kisan", ("pmkisan", "pm-kisan", "kisan")),
        ("pmjjby", ("pmjjby", "jeevan", "jyoti", "jyothi")),
        ("pmsby", ("pmsby", "suraksha bima")),
        ("pmay", ("pmay", "awas", "housing")),
        ("ayushman", ("ayushman", "pmjay", "pm-jay", "nha.gov", "jan arogya")),
        ("gruha lakshmi", ("gruha", "gruhalakshmi", "wcd.karnataka")),
        ("anna bhagya", ("anna", "bhagya", "food.karnataka")),
    ):
        if marker in q_l or any(a in q_l for a in aliases if len(a) > 4):
            if any(a in blob for a in aliases):
                score += 6.0
            elif marker in q_l and "pmkisan" in blob and marker != "pm-kisan":
                score -= 8.0
    # Freshness-sensitive queries: prefer dated / latest / notification docs
    if is_freshness_sensitive(query):
        for bonus in ("2026", "2025", "latest", "revised", "updated", "notification", "circular", "order"):
            if bonus in blob:
                score += 3.0
        if blob.endswith(".pdf") or "/pdf" in blob:
            score += 2.0
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
        kind = (c.get("kind") or "").lower()
        s = score_candidate(
            url, query, link_text=c.get("link_text") or "", kind=kind
        )
        if s < 0:
            continue
        blob = f"{url} {c.get('link_text') or ''}".lower()
        # Drop unrelated PDFs (e.g. holiday lists) that share almost no query tokens
        if kind.startswith("pdf"):
            overlap = sum(1 for t in q_tokens if t in blob)
            if overlap == 0 and s < 12:
                continue
        # Prefer already-packaged scheme-page evidence over bare API/PDF links.
        if kind == "scheme_page" and c.get("content") is not None:
            s += 40
        elif kind == "scheme_page":
            s += 15
        scored.append({**c, "relevance_score": s})
    scored.sort(key=lambda x: -float(x.get("relevance_score") or 0))
    # Hard scheme identity filter BEFORE ingest / PARTIAL / sufficiency.
    try:
        from app.services.myscheme_service import request_accepts_candidate

        scored = [c for c in scored if request_accepts_candidate(query, c)]
    except Exception:
        pass
    return scored[: max(0, limit)]


def discover_seed_urls(
    query: str,
    *,
    phase: str = "all",
    already: Optional[Sequence[str]] = None,
) -> List[Dict[str, Any]]:
    """Staged trusted seeds with myScheme-first priority for scheme queries.

    phase:
      - \"all\": myScheme → catalog → registry → portals (default / tests)
      - \"myscheme\": myScheme (+ catalog URLs on myscheme.gov.in) only
      - \"fallback\": catalog/registry/portals excluding myScheme hosts already tried

    Does not crawl every registry site. Expands only up to LIVE_GOV_MAX_SOURCES.
    """
    from app.services.myscheme_service import (
        build_myscheme_seeds_for_query,
        is_myscheme_url,
    )

    ensure_curated_hosts_merged()
    seeds: List[Dict[str, Any]] = []
    seen = set(already or [])
    schemes = match_catalog_schemes(query)
    max_sources = int(settings.LIVE_GOV_MAX_SOURCES)
    categories = classify_query(query)
    selected_departments: List[str] = []
    prefer_karnataka = "karnataka" in (query or "").lower() or "sevasindhu" in (
        query or ""
    ).lower()
    phase_norm = (phase or "all").strip().lower()

    def _add(seed: Dict[str, Any]) -> bool:
        url = seed.get("url") or ""
        if not url or url in seen or not verify_source(url):
            return False
        seen.add(url)
        seeds.append(seed)
        return True

    # ------------------------------------------------------------------
    # PRIORITY: myScheme.gov.in FIRST (scheme-related queries only)
    # ------------------------------------------------------------------
    if phase_norm in ("all", "myscheme") and looks_like_gov_scheme_query(query):
        try:
            # Leave capacity for Karnataka portals when the query is state-scoped.
            room = max(
                1,
                max_sources - (1 if prefer_karnataka and phase_norm == "all" else 0),
            )
            for seed in build_myscheme_seeds_for_query(
                query,
                verify_fn=verify_source,
                already=seen,
                limit=room,
                include_search=not prefer_karnataka,
            ):
                if _add(seed) and len(seeds) >= room:
                    break
            # Catalog URLs hosted on myScheme (precision scheme pages)
            if len(seeds) < room:
                for scheme in schemes[:max_sources]:
                    for url in scheme.get("urls") or []:
                        if not is_myscheme_url(url):
                            continue
                        if _add(
                            {
                                "url": url,
                                "scheme_name": scheme.get("name"),
                                "ministry": scheme.get("ministry"),
                                "state": scheme.get("state"),
                                "scope": scheme.get("scope"),
                                "link_text": scheme.get("name") or "",
                                "stage": "catalog_myscheme",
                                "source": "myscheme",
                            }
                        ) and len(seeds) >= room:
                            break
                    if len(seeds) >= room:
                        break
        except Exception as e:  # noqa: BLE001
            logger.warning("myscheme priority seed stage failed: %s", type(e).__name__)

    if phase_norm == "myscheme":
        logger.info(
            "live_seed_discovery phase=myscheme query_categories=%s seed_count=%s",
            categories,
            len(seeds),
        )
        return seeds[:max_sources]

    # ------------------------------------------------------------------
    # Catalog (ministry / state official URLs). Skip myScheme hosts on
    # fallback phase — those were already attempted in priority phase.
    # ------------------------------------------------------------------
    for scheme in schemes[:max_sources]:
        for url in scheme.get("urls") or []:
            if phase_norm == "fallback" and is_myscheme_url(url):
                continue
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

    # Strong catalog hit (non-myScheme) can skip generic expansion — except Karnataka.
    strong_catalog_hit = (
        any(s.get("stage") == "catalog" for s in seeds) and not prefer_karnataka
    )

    # Registry departments
    if len(seeds) < max_sources and not strong_catalog_hit:
        for src in prioritize_sources_for_query(query, limit=max_sources * 2):
            if len(seeds) >= max_sources:
                break
            selected_departments.append(src.get("name") or src.get("domain") or "")
            for url in src.get("base_urls") or []:
                if phase_norm == "fallback" and is_myscheme_url(url):
                    continue
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

    # Portal expand
    if len(seeds) < max_sources and not strong_catalog_hit:
        portals = list(GOV_SOURCES)
        if prefer_karnataka:
            portals = sorted(
                portals, key=lambda p: 0 if p.get("id") == "karnataka" else 1
            )
        for portal in portals:
            url = portal.get("url")
            if not url or not verify_source(url) or url in seen:
                continue
            if phase_norm == "fallback" and is_myscheme_url(url):
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
        "live_seed_discovery phase=%s query_categories=%s selected_departments=%s seed_count=%s",
        phase_norm,
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
        from app.services.acquisition import SourceAcquisitionOrchestrator

        self.acquisition = SourceAcquisitionOrchestrator(self.web)
        self._live_request_id: str = "-"
        self._live_query: str = ""

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

    def fetch_page(
        self,
        url: str,
        *,
        deadline_ts: Optional[float] = None,
        force_browser: bool = False,
    ) -> Tuple[Optional[bytes], Optional[str], Optional[str]]:
        """Acquire URL via adaptive orchestrator (static → browser if needed)."""
        content, ctype, err, _meta = self.fetch_page_rich(
            url, deadline_ts=deadline_ts, force_browser=force_browser
        )
        return content, ctype, err

    def fetch_page_rich(
        self,
        url: str,
        *,
        deadline_ts: Optional[float] = None,
        force_browser: bool = False,
    ) -> Tuple[Optional[bytes], Optional[str], Optional[str], Dict[str, Any]]:
        """Acquire URL and return content plus rendered_text / discovery meta."""
        if not verify_source(url):
            logger.info("Rejected untrusted URL: %s", url)
            return None, None, "untrusted", {}
        result = self.acquisition.acquire(
            url,
            verify_fn=verify_source,
            live_request_id=getattr(self, "_live_request_id", "-"),
            query=getattr(self, "_live_query", ""),
            deadline_ts=deadline_ts,
            force_browser=force_browser,
        )
        meta: Dict[str, Any] = {
            "rendered_text": getattr(result, "rendered_text", None) or "",
            "method": getattr(getattr(result, "method", None), "value", None),
            "final_url": result.final_url or url,
            "discovered_links": list(result.discovered_links or []),
            "health": getattr(getattr(result, "health", None), "value", None),
        }
        if not result.ok:
            return (
                None,
                result.content_type,
                result.error or result.health.value,
                meta,
            )
        return result.content, result.content_type, None, meta

    def discover_pdf_links(self, base_url: str, html: str) -> List[Dict[str, Any]]:
        from app.services.acquisition.static_http import discover_document_links

        return discover_document_links(base_url, html, verify_fn=verify_source)

    def discover_candidate_pages(
        self,
        query: str,
        *,
        overall_deadline: Optional[float] = None,
        seeds: Optional[List[Dict[str, Any]]] = None,
        max_pages: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Fetch seed pages (static→browser) and collect document (+ page) candidates.

        If ``seeds`` is provided, only those seeds are walked (myScheme-priority
        or fallback phases). Otherwise uses full ``discover_seed_urls``.
        """
        search_q = expand_search_query(query)
        self._live_query = search_q or ""
        seed_list = list(seeds) if seeds is not None else discover_seed_urls(search_q)
        candidates: List[Dict[str, Any]] = []
        page_cap = int(
            max_pages
            if max_pages is not None
            else getattr(settings, "LIVE_GOV_MAX_PAGES", 6)
        )
        pages_used = 0
        per_source = float(getattr(settings, "LIVE_GOV_TIMEOUT_SECONDS", 25.0))

        for seed in seed_list:
            if pages_used >= page_cap:
                break
            if overall_deadline is not None and time.time() >= overall_deadline:
                break
            url = seed["url"]
            pages_used += 1
            myscheme_packed_ok = False
            # Scheme pages need Playwright headroom — static shells are common.
            is_scheme_seed = (
                (seed.get("kind") or "").lower() == "scheme_page"
                or "/schemes/" in (url or "").lower()
            )
            browser_budget = float(
                getattr(settings, "LIVE_GOV_BROWSER_TIMEOUT_SECONDS", 45.0)
            )
            seed_timeout = max(per_source, browser_budget) if is_scheme_seed else per_source
            source_deadline = time.time() + seed_timeout
            if overall_deadline is not None:
                source_deadline = min(source_deadline, overall_deadline)
            # Skip seeds that already have no remaining budget for browser render.
            if is_scheme_seed and source_deadline - time.time() < 12:
                logger.info(
                    "Skipping scheme seed with insufficient budget url=%s remain=%.1f",
                    url,
                    source_deadline - time.time(),
                )
                continue
            result = self.acquisition.acquire(
                url,
                verify_fn=verify_source,
                live_request_id=getattr(self, "_live_request_id", "-"),
                query=search_q,
                deadline_ts=source_deadline,
                force_browser=bool(is_scheme_seed),
            )
            if result.health.value in (
                "captcha_blocked",
                "login_required",
                "public_access_blocked",
                "untrusted",
            ):
                try:
                    from app.services.myscheme_service import is_myscheme_url, log_myscheme

                    if is_myscheme_url(url):
                        log_myscheme(
                            "MYSCHEME_BLOCKED",
                            url=url,
                            reason=result.health.value,
                        )
                except Exception:
                    pass
                logger.info(
                    "live_request_id=%s SOURCE_BLOCKED url=%s health=%s",
                    getattr(self, "_live_request_id", "-"),
                    url,
                    result.health.value,
                )
                continue
            if not result.ok or result.content is None:
                continue

            content = result.content
            ctype = result.content_type or ""
            method = getattr(result.method, "value", str(result.method))
            # Public JSON/API seed (e.g. NHA Strapi) — keep as API candidate
            if (
                "json" in ctype
                or url.lower().endswith(".json")
                or "/strapi/" in url.lower()
                or "/api/" in url.lower()
            ) and content[:1] in (b"{", b"["):
                candidates.append(
                    {
                        **seed,
                        "url": result.final_url or url,
                        "kind": "public_api",
                        "content": content,
                        "content_type": ctype or "application/json",
                        "link_text": seed.get("link_text") or "public api",
                        "acquisition_method": method,
                    }
                )
                continue

            looks_like_pdf_url = url.lower().endswith(".pdf") or "pdf" in ctype
            is_real_pdf = bool(content[:4] == b"%PDF")
            if looks_like_pdf_url and not is_real_pdf:
                # SPA/WAF often returns HTML shells for .pdf paths — do not fake-ingest
                logger.info(
                    "live_request_id=%s PDF_SHELL_REJECTED url=%s ctype=%s magic=%s",
                    getattr(self, "_live_request_id", "-"),
                    url,
                    ctype,
                    (content[:12] if content else b""),
                )
                # Fall through: try link discovery / browser-rendered HTML if any
            elif is_real_pdf:
                candidates.append(
                    {
                        **seed,
                        "url": result.final_url or url,
                        "kind": "pdf",
                        "content": content,
                        "content_type": "application/pdf",
                        "link_text": seed.get("link_text") or "",
                        "acquisition_method": method,
                    }
                )
                continue

            # Document / API links discovered from static or browser render
            max_docs = int(getattr(settings, "LIVE_GOV_MAX_DOCUMENTS", 6))
            link_budget = max(12, max_docs * 4)
            added_links = 0
            for p in result.discovered_links or []:
                if added_links >= link_budget:
                    break
                link_url = p.get("url") or ""
                if not link_url or not verify_source(link_url):
                    continue
                kind = p.get("kind") or "pdf_link"
                if kind == "public_api":
                    candidates.append(
                        {
                            **seed,
                            "url": link_url,
                            "kind": "public_api",
                            "link_text": p.get("link_text") or "public api",
                            "acquisition_method": method,
                        }
                    )
                    added_links += 1
                    continue
                if kind == "scheme_page":
                    candidates.append(
                        {
                            **seed,
                            "url": link_url,
                            "kind": "scheme_page",
                            "link_text": p.get("link_text") or "",
                            "scheme_name": p.get("link_text") or seed.get("scheme_name"),
                            "acquisition_method": method,
                            "source": "myscheme",
                        }
                    )
                    added_links += 1
                    continue
                candidates.append(
                    {
                        **seed,
                        "url": link_url,
                        "kind": "pdf_link" if link_url.lower().endswith(".pdf") else "document_link",
                        "link_text": p.get("link_text") or "",
                        "acquisition_method": method,
                    }
                )
                added_links += 1

            html = content.decode("utf-8", errors="ignore")

            # myScheme: shell detect → resolve canonical → expand links/media
            try:
                from app.services.myscheme_service import (
                    assess_myscheme_content_quality,
                    discover_myscheme_scheme_links,
                    discover_relevant_media,
                    is_myscheme_url,
                    log_myscheme,
                    resolve_canonical_scheme,
                )

                page_url = result.final_url or url
                if is_myscheme_url(page_url):
                    quality = assess_myscheme_content_quality(
                        html, rendered_text=result.rendered_text or ""
                    )
                    stage_tag = (
                        "catalogue"
                        if "rules.myscheme.gov.in" in page_url.lower()
                        else (
                            "external"
                            if "/external/search" in page_url.lower()
                            else (
                                "search"
                                if "/search" in page_url.lower()
                                else "page"
                            )
                        )
                    )
                    if quality.get("is_shell"):
                        log_myscheme(
                            "MYSCHEME_SHELL",
                            url=page_url,
                            reason=quality.get("failure_class"),
                            method=method,
                        )
                        log_myscheme(
                            "MYSCHEME_DISCOVERY_STATIC",
                            stage=stage_tag,
                            candidates=0,
                            shell=True,
                        )
                        # Shell ≠ zero candidates: still mine JSON/links/cache/aliases.
                    else:
                        log_myscheme(
                            "MYSCHEME_STATIC",
                            url=page_url,
                            method=method,
                            bytes=len(content),
                            sections=quality.get("section_count"),
                        )
                    # Prefer dynamically resolved canonical scheme page (even on shells)
                    resolved = resolve_canonical_scheme(
                        search_q,
                        html=html,
                        base_url=page_url,
                        verify_fn=verify_source,
                    )
                    if resolved and resolved.get("url"):
                        if not any(
                            c.get("url") == resolved["url"] for c in candidates
                        ):
                            candidates.append(
                                {
                                    **seed,
                                    **resolved,
                                    "kind": "scheme_page",
                                    "acquisition_method": method,
                                }
                            )
                            added_links += 1
                            log_myscheme(
                                "MYSCHEME_CANDIDATE_FOUND",
                                stage=stage_tag,
                                scheme_id=resolved.get("scheme_id"),
                                url=resolved.get("url"),
                            )
                    if stage_tag in ("search", "external", "catalogue"):
                        log_myscheme(
                            f"MYSCHEME_DISCOVERY_{stage_tag.upper()}",
                            candidates=sum(
                                1
                                for c in candidates
                                if c.get("kind") == "scheme_page"
                            ),
                            method=method,
                        )
                    # Enrich HTML candidate with section text when on a scheme page
                    if "/schemes/" in page_url.lower():
                        from app.services.myscheme_service import (
                            package_myscheme_evidence,
                        )

                        scheme_label = seed.get("scheme_name")
                        if resolved and resolved.get("scheme_name"):
                            scheme_label = resolved.get("scheme_name")
                        packed = package_myscheme_evidence(
                            html=html,
                            rendered_text=result.rendered_text or "",
                            scheme_name=scheme_label or "",
                            source_url=page_url,
                            query=search_q,
                        )
                        if packed.get("ok") and packed.get("content"):
                            content = packed["content"]
                            result.content = packed["content"]  # type: ignore[attr-defined]
                            # CRITICAL: packaged evidence must enter candidates even if
                            # the raw SPA preview looks like a shell.
                            sid = packed.get("scheme_id") or (
                                resolved.get("scheme_id") if resolved else None
                            ) or seed.get("scheme_id")
                            candidates.append(
                                {
                                    **seed,
                                    "url": page_url,
                                    "kind": "scheme_page",
                                    "content": packed["content"],
                                    "content_type": "text/html",
                                    "rendered_text": packed.get("package_text") or "",
                                    "scheme_name": packed.get("scheme_name")
                                    or scheme_label,
                                    "scheme_id": sid,
                                    "acquisition_method": method,
                                    "source": "myscheme",
                                }
                            )
                            added_links += 1
                            log_myscheme(
                                "MYSCHEME_CONTENT_EXTRACTED",
                                url=page_url,
                                sections=list((packed.get("sections") or {}).keys()),
                                chars=packed.get("text_chars"),
                                scheme_id=sid,
                            )
                            # Skip raw HTML append below — package is the evidence.
                            myscheme_packed_ok = True
                    for p in discover_myscheme_scheme_links(
                        page_url,
                        html,
                        verify_fn=verify_source,
                        query=search_q,
                        limit=8,
                    ):
                        if added_links >= link_budget:
                            break
                        if any(c.get("url") == p.get("url") for c in candidates):
                            continue
                        candidates.append({**seed, **p, "acquisition_method": method})
                        added_links += 1
                    for m in discover_relevant_media(
                        page_url,
                        html,
                        verify_fn=verify_source,
                        query=search_q,
                        limit=2,
                    ):
                        if added_links >= link_budget:
                            break
                        if any(c.get("url") == m.get("url") for c in candidates):
                            continue
                        candidates.append({**seed, **m, "acquisition_method": method})
                        added_links += 1
            except Exception as e:  # noqa: BLE001
                logger.debug("myscheme expand skipped: %s", type(e).__name__)

            # Also scrape anchors from raw HTML (static path)
            for p in self.discover_pdf_links(result.final_url or url, html):
                if added_links >= link_budget:
                    break
                pdf_url = p.get("url") or ""
                if any(c.get("url") == pdf_url for c in candidates):
                    continue
                kind = p.get("kind") or "pdf_link"
                if (pdf_url.lower().endswith(".pdf") or "pdf" in pdf_url.lower()) and kind != "scheme_page":
                    kind = "pdf_link"
                    try:
                        from app.services.myscheme_service import is_myscheme_url, log_myscheme

                        if is_myscheme_url(result.final_url or url) or is_myscheme_url(pdf_url):
                            log_myscheme(
                                "MYSCHEME_DOCUMENT_FOUND",
                                url=pdf_url[:200],
                                scheme_id=seed.get("scheme_id"),
                                scheme_name=seed.get("scheme_name"),
                            )
                    except Exception:
                        pass
                candidates.append(
                    {
                        **seed,
                        **p,
                        "kind": kind,
                        "scheme_id": p.get("scheme_id") or seed.get("scheme_id"),
                        "scheme_name": seed.get("scheme_name") or p.get("link_text"),
                        "acquisition_method": method,
                    }
                )
                added_links += 1

            # Bounded pagination / load-more discovery (depth 1 from seed)
            from app.services.acquisition.static_http import discover_pagination_links

            for page_url in discover_pagination_links(
                result.final_url or url, html, verify_fn=verify_source
            ):
                if pages_used >= page_cap:
                    break
                if any(c.get("url") == page_url for c in candidates):
                    continue
                pages_used += 1
                page_res = self.acquisition.acquire(
                    page_url,
                    verify_fn=verify_source,
                    live_request_id=getattr(self, "_live_request_id", "-"),
                    query=query,
                )
                if not page_res.ok or page_res.content is None:
                    continue
                if page_res.health.value in (
                    "captcha_blocked",
                    "login_required",
                    "public_access_blocked",
                ):
                    break
                for p in page_res.discovered_links or []:
                    link_url = p.get("url") or ""
                    if link_url and verify_source(link_url):
                        candidates.append(
                            {
                                **seed,
                                "url": link_url,
                                "kind": (
                                    "public_api"
                                    if p.get("kind") == "public_api"
                                    else (
                                        "pdf_link"
                                        if link_url.lower().endswith(".pdf")
                                        else "document_link"
                                    )
                                ),
                                "link_text": p.get("link_text") or "",
                                "acquisition_method": getattr(
                                    page_res.method, "value", method
                                ),
                            }
                        )
                page_html = page_res.content.decode("utf-8", errors="ignore")
                for p in self.discover_pdf_links(page_res.final_url or page_url, page_html):
                    candidates.append(
                        {
                            **seed,
                            **p,
                            "kind": "pdf_link",
                            "acquisition_method": getattr(
                                page_res.method, "value", method
                            ),
                        }
                    )

            # Packaged myScheme evidence is already a candidate — never discard it
            # because the raw SPA preview still looks like a shell/error toast.
            if myscheme_packed_ok:
                continue

            text_preview = (result.rendered_text or "").strip()
            if not text_preview:
                text_preview = self.web.extract_text_from_html(
                    html, base_url=result.final_url or url
                )
            low = (text_preview or "").lower()
            skip_low = (
                len(text_preview) < 200
                or "something went wrong" in low
                or "please try again later" in low
            )
            try:
                from app.services.myscheme_service import (
                    is_myscheme_shell_html,
                    is_myscheme_url,
                )

                if is_myscheme_url(result.final_url or url):
                    shell, shell_reason = is_myscheme_shell_html(
                        html, rendered_text=text_preview
                    )
                    if shell:
                        skip_low = True
                        logger.info(
                            "Skipping myScheme shell url=%s reason=%s method=%s",
                            url,
                            shell_reason,
                            method,
                        )
            except Exception:
                pass
            if skip_low:
                logger.info(
                    "Skipping low-content HTML seed url=%s method=%s",
                    url,
                    method,
                )
                continue
            candidates.append(
                {
                    **seed,
                    "url": result.final_url or url,
                    "kind": "html",
                    "content": content,
                    "content_type": ctype or "text/html",
                    "link_text": seed.get("link_text") or "",
                    "acquisition_method": method,
                }
            )
        return candidates

    def _myscheme_browser_discover_candidates(
        self,
        query: str,
        *,
        overall_deadline: Optional[float] = None,
        already_urls: Optional[Sequence[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Escalate discovery when static/external/catalogue yield zero scheme pages.

        Opens myScheme search with Playwright (force_browser), extracts candidates
        from DOM + public JSON network responses, returns scheme_page rows.
        """
        from app.services.myscheme_service import (
            build_myscheme_external_search_url,
            build_myscheme_search_url,
            candidate_to_ingest_row,
            collect_candidates_from_html,
            is_myscheme_url,
            log_myscheme,
            lookup_discovery_cache,
            normalize_myscheme_search_query,
            rank_scheme_candidates,
            resolve_canonical_scheme,
            scheme_query_variants,
        )

        if overall_deadline is not None and time.time() >= overall_deadline:
            return []

        norm = normalize_myscheme_search_query(query)
        log_myscheme(
            "MYSCHEME_DISCOVERY_BROWSER",
            action="start",
            query=(norm or query or "")[:160],
        )

        cached = lookup_discovery_cache(query)
        already = {u for u in (already_urls or []) if u}
        if (
            cached
            and verify_source(cached.get("url") or "")
            and (cached.get("url") or "") not in already
        ):
            log_myscheme(
                "MYSCHEME_CANDIDATE_FOUND",
                source="cache",
                scheme_id=cached.get("scheme_id"),
            )
            return [candidate_to_ingest_row(cached)]

        # Alias / cache resolve without HTML
        resolved = resolve_canonical_scheme(
            query, html="", base_url=build_myscheme_search_url(query), verify_fn=verify_source
        )
        if (
            resolved
            and verify_source(resolved.get("url") or "")
            and (resolved.get("url") or "") not in already
        ):
            log_myscheme(
                "MYSCHEME_CANONICAL_RESOLVED",
                source="alias_or_cache",
                scheme_id=resolved.get("scheme_id"),
                url=resolved.get("url"),
            )
            return [candidate_to_ingest_row(resolved)]

        variants = scheme_query_variants(query) or [norm or query]
        search_urls = [
            build_myscheme_search_url(variants[0]),
            build_myscheme_external_search_url(variants[0]),
        ]
        seen = set(already_urls or [])
        found: List[Dict[str, Any]] = []

        for search_url in search_urls:
            if overall_deadline is not None and time.time() >= overall_deadline:
                break
            if search_url in seen or not verify_source(search_url):
                continue
            seen.add(search_url)
            result = self.acquisition.acquire(
                search_url,
                verify_fn=verify_source,
                live_request_id=getattr(self, "_live_request_id", "-"),
                query=norm or query,
                force_browser=True,
                deadline_ts=overall_deadline,
            )
            if result.health.value in (
                "captcha_blocked",
                "login_required",
                "public_access_blocked",
                "untrusted",
            ):
                log_myscheme(
                    "MYSCHEME_DISCOVERY_BROWSER",
                    action="blocked",
                    health=result.health.value,
                )
                continue
            html = ""
            if result.content:
                html = result.content.decode("utf-8", errors="ignore")
            page_url = result.final_url or search_url
            page_cands = collect_candidates_from_html(
                html,
                query=query,
                base_url=page_url,
                verify_fn=verify_source,
                source_tag="browser",
            )
            for link in result.discovered_links or []:
                if (link.get("kind") or "") != "scheme_page":
                    continue
                link_url = link.get("url") or ""
                if not link_url or not is_myscheme_url(link_url):
                    continue
                if not verify_source(link_url):
                    continue
                page_cands.append(
                    {
                        "url": link_url,
                        "canonical_url": link_url,
                        "scheme_id": link.get("scheme_id"),
                        "scheme_name": link.get("link_text") or "",
                        "stage": "myscheme_browser",
                        "source": "browser",
                        "match_score": 25,
                    }
                )
            ranked = rank_scheme_candidates(page_cands, query)
            log_myscheme(
                "MYSCHEME_DISCOVERY_BROWSER",
                action="page",
                url=page_url[:160],
                candidates=len(ranked),
            )
            for c in ranked:
                found.append(candidate_to_ingest_row(c))
            if found:
                break

        # Dedup
        out: List[Dict[str, Any]] = []
        seen_u: set = set()
        for c in found:
            u = (c.get("url") or "").split("?")[0]
            if not u or u in seen_u:
                continue
            seen_u.add(u)
            out.append(c)
        log_myscheme(
            "MYSCHEME_CANDIDATE_COUNT",
            source="browser",
            count=len(out),
            query=(norm or "")[:100],
        )
        if out:
            log_myscheme(
                "MYSCHEME_CANONICAL_RESOLVED",
                source="browser",
                scheme_id=out[0].get("scheme_id"),
                url=out[0].get("url"),
            )
        return out

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
        scheme_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        rid = live_request_id or "-"
        original_url = url
        sid = scheme_id
        try:
            from app.services.myscheme_service import (
                canonical_myscheme_page_url,
                extract_scheme_id_from_url,
            )

            sid = scheme_id or extract_scheme_id_from_url(url)
            if sid:
                scheme_id = sid
            looks_binary = (
                (content or b"")[:4] == b"%PDF"
                or "pdf" in (content_type or "").lower()
                or (kind or "").startswith("pdf")
                or (kind or "") in ("image", "media", "audio", "video", "pdf_link")
                or bool(
                    re.search(
                        r"\.(pdf|jpe?g|png|webp|gif|mp3|mp4|wav)(\?|$)",
                        url or "",
                        re.I,
                    )
                )
            )
            host = (urlparse(url).hostname or "").lower()
            path = (urlparse(url).path or "").lower()
            # Rewrite API/versioned HTML scheme pages only — never PDFs/media.
            if sid and not looks_binary and ("/schemes/" in path or host.startswith("api.")):
                canon = canonical_myscheme_page_url(url, sid)
                if canon and verify_source(canon):
                    url = canon
        except Exception:
            pass
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
        from datetime import datetime, timezone
        from urllib.parse import urlparse

        host = (urlparse(url).hostname or "").lower()
        sid = scheme_id
        if not sid:
            try:
                from app.services.myscheme_service import extract_scheme_id_from_url

                sid = extract_scheme_id_from_url(url)
            except Exception:
                sid = None
        extra_meta = {
            "ingestion_type": "live_web",
            "live_query": (live_query or "")[:500],
            "live_request_id": rid,
            "scheme_id": sid,
            "scheme_name": scheme_name,
            "canonical_url": url,
            "document_url": original_url,
            "document_type": kind,
            "source_domain": host or None,
            "retrieval_timestamp": datetime.now(timezone.utc).isoformat(),
            "content_hash": document_hash,
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
                preview_stripped = (preview or "").strip()
                # Live path only: scanned PDFs that still have no text after OCR
                if live_query is not None and len(preview_stripped) < 40:
                    _live_log(
                        rid,
                        "LIVE_PDF_EMPTY_TEXT",
                        url=url,
                        preview_len=len(preview_stripped),
                    )
                    return {
                        "status": "rejected",
                        "reason": "empty_pdf_text",
                        "source_url": url,
                    }
                if live_query and not content_relevant_to_query(preview_stripped, live_query):
                    _live_log(
                        rid,
                        "LIVE_PDF_IRRELEVANT",
                        url=url,
                        preview_len=len(preview_stripped),
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
                # HTML / scheme page / media → text via existing path (+ OCR/STT for media)
                text = ""
                document_type = "LIVE_HTML"
                if kind == "image":
                    from app.services.myscheme_service import (
                        log_myscheme,
                        ocr_image_bytes_to_text,
                    )

                    text = ocr_image_bytes_to_text(content)
                    document_type = "LIVE_IMAGE_OCR"
                    if not text or len(text.strip()) < 40:
                        log_myscheme("MYSCHEME_FAILURE", reason="image_unreadable", url=url)
                        return {
                            "status": "rejected",
                            "reason": "unreadable_image",
                            "source_url": url,
                        }
                elif kind in ("audio", "video"):
                    from app.services.myscheme_service import (
                        log_myscheme,
                        transcribe_public_audio_bytes,
                    )

                    # Video: best-effort STT on downloaded bytes (public only)
                    tr = transcribe_public_audio_bytes(
                        content, filename=url.rsplit("/", 1)[-1] or f"{kind}.bin"
                    )
                    text = (tr.get("text") or "").strip()
                    document_type = "LIVE_AUDIO_STT" if kind == "audio" else "LIVE_VIDEO_STT"
                    if not text or len(text) < 40:
                        log_myscheme(
                            "MYSCHEME_FAILURE", reason="media_unreadable", url=url, kind=kind
                        )
                        return {
                            "status": "rejected",
                            "reason": "media_unavailable",
                            "source_url": url,
                        }
                    if tr.get("detected_language"):
                        extra_meta["media_language"] = tr.get("detected_language")
                elif "json" in (content_type or "") or kind == "public_api":
                    from app.services.myscheme_service import public_api_to_evidence_text

                    text = public_api_to_evidence_text(content, source_url=url)
                    document_type = "LIVE_API_JSON"
                    if len(text) < 80:
                        return {
                            "status": "error",
                            "reason": "low_content",
                            "source_url": url,
                        }
                else:
                    raw_html = content.decode("utf-8", errors="ignore")
                    # Prefer already-packaged myScheme evidence text (do not lose sections).
                    if (
                        kind == "scheme_page"
                        and "SCHEME:" in raw_html
                        and "SECTION:" in raw_html
                    ):
                        text = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", raw_html)
                        text = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", text)
                        text = re.sub(r"(?is)<[^>]+>", "\n", text)
                        text = re.sub(r"\n{3,}", "\n\n", text).strip()
                    else:
                        text = self.web.extract_text_from_html(raw_html, base_url=url)
                    if kind == "scheme_page":
                        document_type = "LIVE_MYSCHEME_HTML"
                        try:
                            from app.services.myscheme_service import log_myscheme

                            log_myscheme(
                                "MYSCHEME_STATIC_SUCCESS", url=url, chars=len(text or "")
                            )
                        except Exception:
                            pass

                if len(text) < 200 and document_type not in (
                    "LIVE_IMAGE_OCR",
                    "LIVE_AUDIO_STT",
                    "LIVE_VIDEO_STT",
                ):
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
                    try:
                        from app.services.myscheme_service import log_myscheme

                        log_myscheme(
                            "MYSCHEME_DUPLICATE_REUSED",
                            url=url,
                            document_id=str(existing.id),
                        )
                    except Exception:
                        pass
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
                    document_type=document_type,
                    scheme_name=scheme_name,
                    ministry=ministry,
                    state=resolved_state,
                    category="GOVERNMENT_SCHEMES",
                    document_hash=document_hash,
                    text_preview=text[:500],
                    ingestion_type="live_web",
                    extra_metadata=extra_meta,
                )
                if result.get("status") == "ok":
                    try:
                        from app.services.myscheme_service import log_myscheme

                        log_myscheme(
                            "MYSCHEME_INGEST_SUCCESS",
                            url=url,
                            document_id=result.get("document_id"),
                            document_type=document_type,
                        )
                    except Exception:
                        pass
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
            from app.services.myscheme_service import filter_evidence_by_scheme, log_myscheme
            from app.services.rag import hybrid_retrieve

            docs = hybrid_retrieve(self.db, query, top_k=int(settings.HYBRID_TOP_K))
            docs = filter_evidence_by_scheme(query, docs)
            log_myscheme(
                "MYSCHEME_LOCAL_RETRIEVAL",
                query=(query or "")[:120],
                docs=len(docs),
                live_request_id=live_request_id,
            )
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

    def _ingest_ranked_until_sufficient(
        self,
        ranked: List[Dict[str, Any]],
        *,
        search_q: str,
        rid: str,
        overall_deadline: float,
        per_source: float,
        phase: str,
        ingested: List[Dict[str, Any]],
        rejected_urls: List[str],
        failure_codes: List[str],
        pdfs_used: int,
        max_pdfs: int,
    ) -> Dict[str, Any]:
        """Ingest candidates in order; stop when Evidence Validator probe PASSes.

        Partial/verified docs remain in ``ingested`` / indexes even when probe FAILs
        so later phases can combine evidence.
        """
        from app.services.myscheme_service import (
            is_myscheme_url,
            log_myscheme,
            package_myscheme_evidence,
            request_accepts_candidate,
        )

        accepted_url: Optional[str] = None
        evidence_ready = False
        index_stats: Dict[str, Any] = {}
        status = LIVE_CANDIDATE_FOUND
        tried = 0
        myscheme_page_found_no_content = False

        browser_budget = float(
            getattr(settings, "LIVE_GOV_BROWSER_TIMEOUT_SECONDS", 45.0)
        )
        for cand in ranked:
            if time.time() > overall_deadline:
                _live_log(rid, "LIVE_OVERALL_TIMEOUT", phase=phase)
                break
            url = cand.get("url") or ""
            if not verify_source(url):
                rejected_urls.append(url)
                continue

            # Wrong-scheme documents may stay in the KB; they must not join
            # this request (duplicate reuse / PARTIAL / Ollama context).
            if not request_accepts_candidate(search_q, cand):
                rejected_urls.append(url)
                continue

            kind = cand.get("kind") or "html"
            content = cand.get("content")
            ctype = cand.get("content_type") or ""
            rendered_text = cand.get("rendered_text") or ""
            tried += 1
            is_scheme_page = (
                kind == "scheme_page"
                or "/schemes/" in (url or "").lower()
            ) and is_myscheme_url(url)

            if content is None:
                seed_timeout = (
                    max(per_source, browser_budget) if is_scheme_page else per_source
                )
                source_deadline = time.time() + seed_timeout
                if overall_deadline:
                    source_deadline = min(source_deadline, overall_deadline)
                if is_scheme_page:
                    log_myscheme(
                        "MYSCHEME_ACQUISITION_START",
                        url=url,
                        live_request_id=rid,
                    )
                content, ctype, err, fetch_meta = self.fetch_page_rich(
                    url,
                    deadline_ts=source_deadline,
                    force_browser=bool(is_scheme_page),
                )
                rendered_text = fetch_meta.get("rendered_text") or rendered_text
                if err or content is None:
                    rejected_urls.append(url)
                    if err:
                        failure_codes.append(str(err))
                    if is_scheme_page:
                        myscheme_page_found_no_content = True
                        log_myscheme(
                            "MYSCHEME_STATIC_SHELL",
                            url=url,
                            reason=err,
                            live_request_id=rid,
                        )
                    _live_log(
                        rid,
                        "SOURCE_ATTEMPT",
                        url=url,
                        ok=False,
                        reason=err,
                        phase=phase,
                    )
                    continue
                if is_scheme_page:
                    log_myscheme(
                        "MYSCHEME_BROWSER_RENDERED"
                        if (fetch_meta.get("method") or "").startswith("browser")
                        else "MYSCHEME_STATIC_FETCH",
                        url=url,
                        bytes=len(content or b""),
                        live_request_id=rid,
                    )

            if kind == "public_api" or (
                "json" in (ctype or "").lower() and not url.lower().endswith(".pdf")
            ):
                from app.services.acquisition.static_http import public_api_bytes_to_text

                api_text = public_api_bytes_to_text(content or b"", ctype or "")
                if len(api_text.strip()) < 80:
                    rejected_urls.append(url)
                    _live_log(rid, "API_FAILED", url=url, reason="empty_payload", phase=phase)
                    continue
                # myScheme JSON detail → normalize into section evidence
                if is_myscheme_url(url):
                    packed_api = package_myscheme_evidence(
                        html="",
                        rendered_text=api_text,
                        scheme_name=cand.get("scheme_name") or "",
                        source_url=url,
                        query=search_q,
                        json_blobs=[api_text],
                    )
                    if packed_api.get("ok") and packed_api.get("content"):
                        content = packed_api["content"]
                        ctype = "text/html"
                        kind = "scheme_page"
                        log_myscheme(
                            "MYSCHEME_CONTENT_EXTRACTED",
                            via="api",
                            sections=list((packed_api.get("sections") or {}).keys()),
                            live_request_id=rid,
                        )
                    else:
                        content = (
                            f"<html><body><pre>Public government API extract from {url}\n\n"
                            f"{api_text}</pre></body></html>"
                        ).encode("utf-8")
                        ctype = "text/html"
                        kind = "html"
                else:
                    content = (
                        f"<html><body><pre>Public government API extract from {url}\n\n"
                        f"{api_text}</pre></body></html>"
                    ).encode("utf-8")
                    ctype = "text/html"
                    kind = "html"
                _live_log(rid, "API_SUCCESS", url=url, chars=len(api_text), phase=phase)

            is_pdf = (
                kind.startswith("pdf")
                or "pdf" in (ctype or "")
                or url.lower().endswith(".pdf")
                or (content or b"")[:4] == b"%PDF"
            )
            if is_pdf and (content or b"")[:4] != b"%PDF":
                rejected_urls.append(url)
                failure_codes.append("HTML_SHELL")
                _live_log(
                    rid,
                    "DOCUMENT_REJECTED",
                    url=url,
                    reason="HTML_SHELL",
                    content_type=ctype,
                    phase=phase,
                )
                continue
            if is_pdf:
                if pdfs_used >= max_pdfs:
                    continue
                _live_log(
                    rid,
                    "PDF_DOWNLOADED",
                    url=url,
                    bytes=len(content or b""),
                    content_type=ctype,
                    phase=phase,
                )
                if phase == "myscheme":
                    log_myscheme(
                        "MYSCHEME_PDF_ACQUIRED",
                        url=url[:200],
                        bytes=len(content or b""),
                        scheme_id=cand.get("scheme_id"),
                        live_request_id=rid,
                    )

            # CRITICAL: URL discovery ≠ success — package real scheme sections
            if is_scheme_page and not is_pdf:
                html_txt = (content or b"").decode("utf-8", errors="ignore")
                packed = package_myscheme_evidence(
                    html=html_txt,
                    rendered_text=rendered_text,
                    scheme_name=cand.get("scheme_name") or cand.get("link_text") or "",
                    source_url=url,
                    query=search_q,
                )
                if not packed.get("ok") or not packed.get("content"):
                    myscheme_page_found_no_content = True
                    rejected_urls.append(url)
                    failure_codes.append(str(packed.get("reason") or "HTML_SHELL"))
                    log_myscheme(
                        "MYSCHEME_PARTIAL",
                        url=url,
                        reason=packed.get("reason"),
                        live_request_id=rid,
                    )
                    _live_log(
                        rid,
                        "DOCUMENT_REJECTED",
                        url=url,
                        reason=packed.get("reason") or "NO_SCHEME_CONTENT",
                        phase=phase,
                    )
                    continue
                content = packed["content"]
                ctype = "text/html"
                kind = "scheme_page"
                if packed.get("scheme_id"):
                    cand["scheme_id"] = packed.get("scheme_id")
                if packed.get("scheme_name"):
                    cand["scheme_name"] = packed.get("scheme_name")
                log_myscheme(
                    "MYSCHEME_CONTENT_EXTRACTED",
                    url=url,
                    sections=list((packed.get("sections") or {}).keys()),
                    chars=packed.get("text_chars"),
                    query_sufficient=packed.get("query_sufficient"),
                    scheme_id=cand.get("scheme_id"),
                    live_request_id=rid,
                )

            if phase == "myscheme" and is_myscheme_url(url):
                log_myscheme(
                    "MYSCHEME_INGEST",
                    url=url,
                    scheme_id=cand.get("scheme_id"),
                    live_request_id=rid,
                )

            result = self.ingest_verified_document(
                url=url,
                content=content,
                content_type=ctype or ("application/pdf" if is_pdf else "text/html"),
                scheme_name=cand.get("scheme_name"),
                ministry=cand.get("ministry"),
                state=cand.get("state"),
                kind=kind,
                live_query=search_q,
                live_request_id=rid,
                scheme_id=cand.get("scheme_id"),
            )
            if result.get("status") in ("rejected", "error"):
                rejected_urls.append(url)
                reason = result.get("reason") or result.get("detail") or "PARSE_FAILED"
                if reason in ("empty_extract", "irrelevant", "unreadable"):
                    failure_codes.append(
                        "IRRELEVANT_DOCUMENT" if reason == "irrelevant" else "PARSE_FAILED"
                    )
                elif "ocr" in str(reason).lower():
                    failure_codes.append("OCR_FAILED")
                else:
                    failure_codes.append(str(reason))
                _live_log(rid, "DOCUMENT_REJECTED", url=url, reason=reason, phase=phase)
                continue
            if is_pdf:
                pdfs_used += 1
            if result.get("reason") == "duplicate":
                _live_log(
                    rid,
                    "DUPLICATE_REUSED",
                    url=url,
                    document_hash=result.get("document_hash"),
                    phase=phase,
                )
                if phase == "myscheme":
                    log_myscheme(
                        "MYSCHEME_DUPLICATE_REUSED",
                        url=url,
                        document_hash=result.get("document_hash"),
                        live_request_id=rid,
                    )
                ingested.append(result)
                index_ok = False
                try:
                    index_stats = self.refresh_indexes(live_request_id=rid)
                    index_ok = "error" not in (index_stats or {})
                    if phase == "myscheme":
                        log_myscheme("MYSCHEME_INDEX_REFRESH", live_request_id=rid)
                except Exception as e:  # noqa: BLE001
                    _live_log(rid, "INDEX_FAILED", err=type(e).__name__, attempt=1, phase=phase)
                if index_ok and self._probe_evidence_ready(search_q, live_request_id=rid):
                    evidence_ready = True
                    accepted_url = url
                    _live_log(rid, "EVIDENCE_PASS", url=url, via="duplicate", phase=phase)
                    if phase == "myscheme":
                        log_myscheme(
                            "MYSCHEME_SUFFICIENCY_CHECK",
                            sufficient=True,
                            live_request_id=rid,
                        )
                        log_myscheme("MYSCHEME_SUFFICIENT", url=url, live_request_id=rid)
                        log_myscheme("MYSCHEME_EVIDENCE_PASS", url=url, live_request_id=rid)
                        log_myscheme("MYSCHEME_INDEX", live_request_id=rid)
                        log_myscheme("MYSCHEME_SECOND_RETRIEVAL", ok=True, live_request_id=rid)
                        log_myscheme("MYSCHEME_ANSWER_READY", url=url, live_request_id=rid)
                    break
                if phase == "myscheme":
                    log_myscheme(
                        "MYSCHEME_SUFFICIENCY_CHECK",
                        sufficient=False,
                        live_request_id=rid,
                    )
                    log_myscheme("MYSCHEME_PARTIAL", url=url, live_request_id=rid)
                continue

            if result.get("status") == "ok":
                ingested.append(result)
                accepted_url = url
                status = LIVE_DOCUMENT_INGESTED
                _live_log(
                    rid,
                    "DOCUMENT_ACCEPTED",
                    document_id=result.get("document_id"),
                    chunk_count=result.get("chunk_count"),
                    url=url,
                    phase=phase,
                )

                index_ok = False
                for attempt in (1, 2):
                    try:
                        index_stats = self.refresh_indexes(live_request_id=rid)
                        index_ok = "error" not in (index_stats or {})
                        _live_log(
                            rid, "INDEX_UPDATED", attempt=attempt, phase=phase, **(index_stats or {})
                        )
                        if phase == "myscheme":
                            log_myscheme("MYSCHEME_INDEX_REFRESH", live_request_id=rid)
                            log_myscheme("MYSCHEME_INDEX", live_request_id=rid)
                        break
                    except Exception as e:  # noqa: BLE001
                        _live_log(
                            rid,
                            "INDEX_FAILED",
                            err=type(e).__name__,
                            attempt=attempt,
                            phase=phase,
                        )
                        index_stats = {"error": str(e)}
                        time.sleep(0.2 * attempt)
                if not index_ok:
                    continue

                if self._probe_evidence_ready(search_q, live_request_id=rid):
                    evidence_ready = True
                    _live_log(rid, "EVIDENCE_PASS", url=url, phase=phase)
                    _live_log(rid, "SECOND_RETRIEVAL", url=url, ok=True, phase=phase)
                    if phase == "myscheme":
                        log_myscheme(
                            "MYSCHEME_SUFFICIENCY_CHECK",
                            sufficient=True,
                            live_request_id=rid,
                        )
                        log_myscheme("MYSCHEME_SUFFICIENT", url=url, live_request_id=rid)
                        log_myscheme("MYSCHEME_EVIDENCE_PASS", url=url, live_request_id=rid)
                        log_myscheme("MYSCHEME_SECOND_RETRIEVAL", ok=True, live_request_id=rid)
                        log_myscheme("MYSCHEME_ANSWER_READY", url=url, live_request_id=rid)
                    break
                _live_log(rid, "EVIDENCE_FAIL", url=url, action="try_next", phase=phase)
                if phase == "myscheme":
                    log_myscheme(
                        "MYSCHEME_SUFFICIENCY_CHECK",
                        sufficient=False,
                        live_request_id=rid,
                    )
                    log_myscheme("MYSCHEME_PARTIAL", url=url, live_request_id=rid)

        return {
            "evidence_ready": evidence_ready,
            "accepted_url": accepted_url,
            "index_stats": index_stats,
            "status": status,
            "pdfs_used": pdfs_used,
            "candidates_tried": tried,
            "myscheme_page_found_no_content": myscheme_page_found_no_content,
        }

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

        Scheme-related path (after local KB FAIL at caller):
          1) myScheme.gov.in FIRST → Evidence Validator probe
          2) If insufficient/unavailable → existing registry/catalog/portals
             while retaining any verified myScheme evidence already ingested.

        Does NOT call Ollama. Caller must re-run Evidence Validator + RAG.
        """
        from app.services.myscheme_service import is_myscheme_url, log_myscheme

        _ = language, conversation_context
        rid = live_request_id or str(uuid.uuid4())
        self._live_request_id = rid
        search_q = expand_search_query(query)
        self._live_query = search_q or ""
        started = time.perf_counter()
        # Absolute wall-clock deadlines — acquire/discover compare with time.time().
        wall_start = time.time()
        overall_budget = float(settings.LIVE_GOV_OVERALL_TIMEOUT_SECONDS)
        overall_deadline = wall_start + overall_budget
        per_source = float(getattr(settings, "LIVE_GOV_TIMEOUT_SECONDS", 25.0))

        if not looks_like_gov_scheme_query(search_q):
            _live_log(rid, "LIVE_SKIP_NOT_SCHEME_QUERY")
            return {
                "status": NO_TRUSTED_INFORMATION_FOUND,
                "ingested": [],
                "candidates_tried": 0,
                "live_request_id": rid,
                "latency_ms": int((time.perf_counter() - started) * 1000),
            }

        categories = classify_query(search_q)
        _live_log(
            rid,
            "LIVE_FALLBACK_START",
            query=(query or "")[:200],
            search_query=(search_q or "")[:200],
            freshness_sensitive=is_freshness_sensitive(query),
            source_category=categories,
            live_fallback_enabled=settings.LIVE_GOV_FALLBACK_ENABLED,
            browser_enabled=getattr(settings, "LIVE_GOV_BROWSER_ENABLED", True),
        )
        _live_log(rid, "QUERY_CLASSIFIED", categories=categories)

        status = LIVE_SEARCH_STARTED
        rejected_urls: List[str] = []
        failure_codes: List[str] = []
        accepted_url: Optional[str] = None
        evidence_ready = False
        index_stats: Dict[str, Any] = {}
        ingested: List[Dict[str, Any]] = []
        pdfs_used = 0
        max_pdfs = int(settings.LIVE_GOV_MAX_PDFS)
        candidates_tried = 0
        all_ranked: List[Dict[str, Any]] = []
        myscheme_phase_used = False
        tried_urls: List[str] = []
        myscheme_page_found_no_content = False

        if getattr(settings, "LIVE_GOV_PROVIDER_REGISTRY_ENABLED", True):
            try:
                from app.services.providers.live_integration import search_via_provider_registry

                return search_via_provider_registry(
                    self,
                    query=query,
                    search_q=search_q,
                    rid=rid,
                    wall_start=wall_start,
                    overall_deadline=overall_deadline,
                    per_source=per_source,
                    started=started,
                )
            except Exception as e:  # noqa: BLE001
                _live_log(rid, "PROVIDER_REGISTRY_LEGACY_FALLBACK", err=type(e).__name__)

        # ------------------------------------------------------------------
        # LEGACY orchestration (compatibility fallback if registry disabled/errors)
        # PHASE 1 — myScheme priority (bounded time; do not burn full budget)
        # ------------------------------------------------------------------
        browser_budget = float(
            getattr(settings, "LIVE_GOV_BROWSER_TIMEOUT_SECONDS", 45.0)
        )
        # Reserve enough wall time for Playwright scheme-page acquisition + ingest.
        myscheme_budget = min(
            overall_budget * 0.65,
            max(per_source * 2.5, browser_budget + 35.0, 70.0),
        )
        myscheme_deadline = min(overall_deadline, wall_start + myscheme_budget)
        myscheme_seeds = discover_seed_urls(search_q, phase="myscheme")
        if myscheme_seeds and time.time() < myscheme_deadline:
            myscheme_phase_used = True
            log_myscheme(
                "MYSCHEME_PRIORITY_START",
                live_request_id=rid,
                seeds=len(myscheme_seeds),
                budget_s=round(myscheme_budget, 1),
            )
            _live_log(rid, "MYSCHEME_PRIORITY_START", seeds=len(myscheme_seeds))
            discovery_error = None
            try:
                raw_ms = self.discover_candidate_pages(
                    search_q,
                    overall_deadline=myscheme_deadline,
                    seeds=myscheme_seeds,
                    max_pages=min(4, int(getattr(settings, "LIVE_GOV_MAX_PAGES", 6))),
                )
            except Exception as e:  # noqa: BLE001
                discovery_error = e
                _live_log(rid, "MYSCHEME_DISCOVERY_ERROR", err=type(e).__name__)
                log_myscheme("MYSCHEME_FAILED", reason=type(e).__name__, live_request_id=rid)
                raw_ms = []

            # Prefer myScheme-hosted evidence in this phase; linked external
            # trusted domains wait for fallback (independent registry verify).
            ms_only = [c for c in raw_ms if is_myscheme_url(c.get("url") or "")]
            ranked_ms = select_best_candidates(
                ms_only,
                search_q,
                limit=int(settings.LIVE_GOV_MAX_CANDIDATES),
            )
            log_myscheme(
                "MYSCHEME_DISCOVERY_STATIC",
                live_request_id=rid,
                candidates=len(ranked_ms),
            )
            walked_canonical = any(
                (s.get("kind") == "scheme_page")
                or "/schemes/" in ((s.get("url") or "").lower())
                for s in myscheme_seeds
            )
            # Browser escalate only when static discovery completed with zero
            # candidates and we did not already walk a canonical scheme page.
            # Do not re-queue cache URLs after TimeoutError / mocked empty walks.
            if (
                not ranked_ms
                and discovery_error is None
                and not raw_ms
                and not walked_canonical
            ):
                # Zero static/catalogue candidates ≠ scheme missing — escalate.
                log_myscheme(
                    "NO_STATIC_CANDIDATES",
                    live_request_id=rid,
                    query=(search_q or "")[:160],
                )
                browser_ms = self._myscheme_browser_discover_candidates(
                    search_q,
                    overall_deadline=myscheme_deadline,
                    already_urls=[s.get("url") for s in myscheme_seeds if s.get("url")],
                )
                if browser_ms:
                    ranked_ms = select_best_candidates(
                        browser_ms,
                        search_q,
                        limit=int(settings.LIVE_GOV_MAX_CANDIDATES),
                    )
                    log_myscheme(
                        "MYSCHEME_DISCOVERY_BROWSER",
                        live_request_id=rid,
                        candidates=len(ranked_ms),
                    )
                else:
                    log_myscheme(
                        "NO_BROWSER_CANDIDATES",
                        live_request_id=rid,
                        query=(search_q or "")[:160],
                    )
            elif not ranked_ms:
                log_myscheme(
                    "NO_STATIC_CANDIDATES",
                    live_request_id=rid,
                    query=(search_q or "")[:160],
                    skipped_browser=True,
                    discovery_error=type(discovery_error).__name__ if discovery_error else None,
                )

            all_ranked.extend(ranked_ms)
            log_myscheme(
                "MYSCHEME_DISCOVERY",
                live_request_id=rid,
                candidates=len(ranked_ms),
            )
            log_myscheme(
                "MYSCHEME_CANDIDATE_COUNT",
                live_request_id=rid,
                final=len(ranked_ms),
            )
            if ranked_ms:
                log_myscheme(
                    "MYSCHEME_CANDIDATE_FOUND",
                    live_request_id=rid,
                    count=len(ranked_ms),
                )
                log_myscheme(
                    "MYSCHEME_CONTENT_ACQUIRED",
                    live_request_id=rid,
                    with_content=sum(1 for c in ranked_ms if c.get("content") is not None),
                )
                status = LIVE_CANDIDATE_FOUND
                phase_out = self._ingest_ranked_until_sufficient(
                    ranked_ms,
                    search_q=search_q,
                    rid=rid,
                    overall_deadline=myscheme_deadline,
                    per_source=per_source,
                    phase="myscheme",
                    ingested=ingested,
                    rejected_urls=rejected_urls,
                    failure_codes=failure_codes,
                    pdfs_used=pdfs_used,
                    max_pdfs=max_pdfs,
                )
                pdfs_used = int(phase_out.get("pdfs_used") or pdfs_used)
                candidates_tried += int(phase_out.get("candidates_tried") or 0)
                if phase_out.get("myscheme_page_found_no_content"):
                    myscheme_page_found_no_content = True
                if phase_out.get("index_stats"):
                    index_stats = phase_out["index_stats"]
                if phase_out.get("accepted_url"):
                    accepted_url = phase_out["accepted_url"]
                if phase_out.get("status"):
                    status = phase_out["status"]
                tried_urls.extend(
                    [c.get("url") for c in ranked_ms if c.get("url")]
                )
                if phase_out.get("evidence_ready"):
                    evidence_ready = True
                elif ingested:
                    log_myscheme("MYSCHEME_PARTIAL", live_request_id=rid, kept=len(ingested))
                    log_myscheme("MYSCHEME_FALLBACK", live_request_id=rid)
                    log_myscheme("MYSCHEME_FALLBACK_CONTINUE", live_request_id=rid)
                    _live_log(rid, "MYSCHEME_FALLBACK_CONTINUE", kept=len(ingested))
                else:
                    log_myscheme("MYSCHEME_FAILED", live_request_id=rid, reason="no_usable")
                    log_myscheme("MYSCHEME_FALLBACK_CONTINUE", live_request_id=rid)
                    _live_log(rid, "MYSCHEME_FALLBACK_CONTINUE", kept=0)
            else:
                failure_codes.append("scheme_not_resolved")
                log_myscheme(
                    "MYSCHEME_FAILED",
                    live_request_id=rid,
                    reason="scheme_not_resolved",
                )
                log_myscheme("MYSCHEME_FALLBACK", live_request_id=rid)
                log_myscheme("MYSCHEME_FALLBACK_CONTINUE", live_request_id=rid)
                _live_log(rid, "MYSCHEME_FALLBACK_CONTINUE", kept=0)

        # ------------------------------------------------------------------
        # PHASE 2 — existing trusted registry / catalog / portals
        # ------------------------------------------------------------------
        if not evidence_ready and time.time() < overall_deadline:
            fallback_seeds = discover_seed_urls(
                search_q, phase="fallback", already=tried_urls
            )
            # Also exclude myScheme hosts already walked
            fallback_seeds = [
                s
                for s in fallback_seeds
                if (s.get("url") or "") not in tried_urls
                and not is_myscheme_url(s.get("url") or "")
            ]
            if fallback_seeds:
                _live_log(
                    rid,
                    "LIVE_FALLBACK_REGISTRY_START",
                    seeds=len(fallback_seeds),
                    after_myscheme=myscheme_phase_used,
                )
                try:
                    raw_fb = self.discover_candidate_pages(
                        search_q,
                        overall_deadline=overall_deadline,
                        seeds=fallback_seeds,
                    )
                except Exception as e:  # noqa: BLE001
                    if not ingested:
                        _live_log(rid, "LIVE_SOURCE_SEARCH_FAILED", err=type(e).__name__)
                        return {
                            "status": NO_TRUSTED_INFORMATION_FOUND,
                            "detail": LIVE_UNAVAILABLE,
                            "ingested": [],
                            "failure_codes": ["NETWORK_ERROR"],
                            "live_request_id": rid,
                            "latency_ms": int((time.perf_counter() - started) * 1000),
                        }
                    _live_log(rid, "LIVE_FALLBACK_REGISTRY_ERROR", err=type(e).__name__)
                    raw_fb = []

                ranked_fb = select_best_candidates(
                    raw_fb,
                    search_q,
                    limit=int(settings.LIVE_GOV_MAX_CANDIDATES),
                )
                all_ranked.extend(ranked_fb)
                _live_log(rid, "SOURCES_SELECTED", candidates=len(ranked_fb), phase="fallback")
                if ranked_fb:
                    status = LIVE_CANDIDATE_FOUND
                    phase_out = self._ingest_ranked_until_sufficient(
                        ranked_fb,
                        search_q=search_q,
                        rid=rid,
                        overall_deadline=overall_deadline,
                        per_source=per_source,
                        phase="fallback",
                        ingested=ingested,
                        rejected_urls=rejected_urls,
                        failure_codes=failure_codes,
                        pdfs_used=pdfs_used,
                        max_pdfs=max_pdfs,
                    )
                    pdfs_used = int(phase_out.get("pdfs_used") or pdfs_used)
                    candidates_tried += int(phase_out.get("candidates_tried") or 0)
                    if phase_out.get("index_stats"):
                        index_stats = phase_out["index_stats"]
                    if phase_out.get("accepted_url"):
                        accepted_url = phase_out["accepted_url"]
                    if phase_out.get("status"):
                        status = phase_out["status"]
                    if phase_out.get("evidence_ready"):
                        evidence_ready = True
            elif not myscheme_phase_used:
                # No myScheme seeds and no fallback — try legacy full discovery once
                try:
                    raw_candidates = self.discover_candidate_pages(
                        search_q, overall_deadline=overall_deadline
                    )
                except Exception as e:  # noqa: BLE001
                    _live_log(rid, "LIVE_SOURCE_SEARCH_FAILED", err=type(e).__name__)
                    return {
                        "status": NO_TRUSTED_INFORMATION_FOUND,
                        "detail": LIVE_UNAVAILABLE,
                        "ingested": [],
                        "failure_codes": ["NETWORK_ERROR"],
                        "live_request_id": rid,
                        "latency_ms": int((time.perf_counter() - started) * 1000),
                    }
                ranked = select_best_candidates(
                    raw_candidates,
                    search_q,
                    limit=int(settings.LIVE_GOV_MAX_CANDIDATES),
                )
                all_ranked.extend(ranked)
                if ranked:
                    status = LIVE_CANDIDATE_FOUND
                    phase_out = self._ingest_ranked_until_sufficient(
                        ranked,
                        search_q=search_q,
                        rid=rid,
                        overall_deadline=overall_deadline,
                        per_source=per_source,
                        phase="legacy",
                        ingested=ingested,
                        rejected_urls=rejected_urls,
                        failure_codes=failure_codes,
                        pdfs_used=pdfs_used,
                        max_pdfs=max_pdfs,
                    )
                    candidates_tried += int(phase_out.get("candidates_tried") or 0)
                    if phase_out.get("index_stats"):
                        index_stats = phase_out["index_stats"]
                    if phase_out.get("accepted_url"):
                        accepted_url = phase_out["accepted_url"]
                    if phase_out.get("status"):
                        status = phase_out["status"]
                    evidence_ready = bool(phase_out.get("evidence_ready"))

        latency_ms = int((time.perf_counter() - started) * 1000)
        _live_log(
            rid,
            "LIVE_FALLBACK_SUMMARY",
            accepted_url=accepted_url,
            rejected=len(rejected_urls),
            evidence_ready=evidence_ready,
            latency_ms=latency_ms,
            myscheme_phase=myscheme_phase_used,
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
        preferred_status = None
        has_scheme_url = any(
            "myscheme.gov.in/schemes/" in ((g.get("url") or "").lower())
            for g in guidance_urls
        )
        if (
            not evidence_ready
            and myscheme_page_found_no_content
            and has_scheme_url
        ):
            preferred_status = "scheme_content_unavailable"
        elif not evidence_ready and ingested and has_scheme_url:
            # Content retrieved/ingested but still insufficient for the question.
            preferred_status = "scheme_question_insufficient"
        elif (
            not evidence_ready
            and not ingested
            and has_scheme_url
            and any(c == "scheme_not_resolved" for c in failure_codes)
        ):
            # Canonical URL known but content path failed.
            preferred_status = "scheme_content_unavailable"
        elif (
            not evidence_ready
            and not ingested
            and not has_scheme_url
            and any(c == "scheme_not_resolved" for c in failure_codes)
        ):
            preferred_status = "scheme_not_identified"

        if not ingested:
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
            }

        if not index_stats:
            try:
                index_stats = self.refresh_indexes(live_request_id=rid)
            except Exception as e:  # noqa: BLE001
                index_stats = {"error": str(e)}

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
