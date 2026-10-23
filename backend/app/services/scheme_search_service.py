"""
Catalog-driven scheme identification and SQL search needles (scheme-agnostic).

Uses data/scheme_catalog.json plus existing slug/alias helpers — not per-scheme code patches.
"""

from __future__ import annotations

import json
import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger("gramsakhi.scheme_search")

_CATALOG_PATH = Path(__file__).resolve().parents[2] / "data" / "scheme_catalog.json"


@lru_cache(maxsize=1)
def load_scheme_catalog() -> List[Dict[str, Any]]:
    if not _CATALOG_PATH.is_file():
        return []
    try:
        data = json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))
        schemes = data.get("schemes") if isinstance(data, dict) else None
        return list(schemes) if isinstance(schemes, list) else []
    except Exception as exc:  # noqa: BLE001
        logger.warning("scheme_catalog_load_failed err=%s", type(exc).__name__)
        return []


def catalog_entries_for_slug(slug: str) -> List[Dict[str, Any]]:
    s = (slug or "").strip().lower()
    if not s:
        return []
    out: List[Dict[str, Any]] = []
    for entry in load_scheme_catalog():
        eid = str(entry.get("id") or "").strip().lower()
        if eid == s or eid.replace("-", "") == s.replace("-", ""):
            out.append(entry)
    return out


def match_catalog_entries(query: str, *, limit: int = 3) -> List[Tuple[Dict[str, Any], float]]:
    """Score catalog schemes mentioned in the citizen query."""
    from app.services.myscheme_service import normalize_scheme_key, slug_hint_from_query

    q_key = normalize_scheme_key(query or "")
    slug = (slug_hint_from_query(query or "") or "").strip().lower()
    scored: List[Tuple[Dict[str, Any], float]] = []
    for entry in load_scheme_catalog():
        score = 0.0
        eid = str(entry.get("id") or "").strip().lower()
        name = str(entry.get("name") or "")
        name_key = normalize_scheme_key(name)
        if slug and eid == slug:
            score += 3.0
        if eid and eid.replace("-", "") in q_key.replace(" ", ""):
            score += 2.0
        if name_key and name_key in q_key:
            score += 2.5
        for kw in entry.get("keywords") or []:
            kk = normalize_scheme_key(str(kw))
            if len(kk) >= 3 and kk in q_key:
                score += 1.5
        if score > 0:
            scored.append((entry, score))
    scored.sort(key=lambda x: -x[1])
    return scored[:limit]


def build_search_needles(
    query_text: str,
    *,
    scheme_hint: Optional[str] = None,
    scheme_id_hint: Optional[str] = None,
    restrict_to_scheme_id: Optional[str] = None,
) -> List[str]:
    """Tokens for PostgreSQL LIKE / lexical retrieval (catalog + slug + query hints)."""
    from app.services.myscheme_service import normalize_scheme_key, slug_hint_from_query

    restrict = (restrict_to_scheme_id or "").strip().lower()
    if restrict:
        entries = catalog_entries_for_slug(restrict)
        if entries:
            e = entries[0]
            scoped: List[str] = []
            for raw in [e.get("id"), e.get("name"), *(e.get("keywords") or [])]:
                scoped.append(normalize_scheme_key(str(raw)))
                scoped.append(str(raw).strip().lower())
            out: List[str] = []
            for s in scoped:
                if len(s) >= 3 and s not in out:
                    out.append(s)
            return out[:10]

    needles: List[str] = []
    slug_raw = (scheme_id_hint or slug_hint_from_query(query_text or "") or "").strip().lower()

    def _add(raw: Optional[str]) -> None:
        t = (raw or "").strip()
        if len(t) >= 3 and t not in needles:
            needles.append(t)

    if scheme_id_hint:
        _add(normalize_scheme_key(scheme_id_hint))
        _add(scheme_id_hint.strip().lower())
    if scheme_hint:
        _add(normalize_scheme_key(scheme_hint))
    slug = slug_hint_from_query(query_text or "")
    if slug:
        _add(normalize_scheme_key(slug))
        _add(slug.strip().lower())

    for entry, _score in match_catalog_entries(query_text, limit=2):
        _add(str(entry.get("name") or ""))
        _add(str(entry.get("id") or ""))
        for kw in entry.get("keywords") or []:
            _add(normalize_scheme_key(str(kw)))
            _add(str(kw).strip().lower())

    if slug_raw:
        for entry in catalog_entries_for_slug(slug_raw):
            _add(str(entry.get("name") or ""))
            for kw in entry.get("keywords") or []:
                _add(normalize_scheme_key(str(kw)))

    try:
        from app.services.myscheme_service import _NAME_ALIASES

        for canon, names in _NAME_ALIASES.items():
            ck = normalize_scheme_key(canon)
            if slug_raw and (
                slug_raw == ck.replace(" ", "-")
                or slug_raw in ck
                or ck in slug_raw.replace("-", " ")
            ):
                _add(ck)
                for n in names:
                    _add(normalize_scheme_key(n))
    except Exception:  # noqa: BLE001
        pass

    return needles[:10]


def catalog_scheme_ids() -> List[str]:
    return [
        str(e.get("id") or "").strip()
        for e in load_scheme_catalog()
        if str(e.get("id") or "").strip()
    ]


def corpus_coverage_counts(db) -> Dict[str, int]:
    """Chunk counts per catalog scheme id (read-only, no credentials)."""
    from sqlalchemy import text

    from app.services.myscheme_service import normalize_scheme_key

    if db.bind is None or db.bind.dialect.name != "postgresql":
        return {}
    out: Dict[str, int] = {}
    for entry in load_scheme_catalog():
        eid = str(entry.get("id") or "").strip()
        if not eid:
            continue
        needles = [normalize_scheme_key(eid)] + [
            normalize_scheme_key(str(k)) for k in (entry.get("keywords") or [])[:6]
        ]
        needles = [n for n in dict.fromkeys(needles) if n and len(n) >= 3][:6]
        if not needles:
            continue
        clauses = []
        params: Dict[str, Any] = {}
        for i, n in enumerate(needles):
            key = f"p{i}"
            params[key] = f"%{n.replace('-', '%')}%"
            clauses.append(
                f"(lower(coalesce(d.scheme_name,'')) LIKE :{key} "
                f"OR lower(coalesce(d.title,'')) LIKE :{key} "
                f"OR lower(c.content) LIKE :{key})"
            )
        where = " OR ".join(clauses)
        n = db.execute(
            text(
                f"""
                SELECT COUNT(*) FROM document_chunks c
                JOIN rag_documents d ON c.document_id = d.id
                WHERE {where}
                """
            ),
            params,
        ).scalar() or 0
        out[eid] = int(n)
    return out


# Intent markers shared by SQL ranking (Latin script; KN/HI often routed via validation_query EN).
_INTENT_CONTENT_RE = re.compile(
    r"(eligible|eligibility|benefit|benefits|criteria|who can apply|beneficiary|"
    r"application|apply|document|deadline|installment|assistance|pension)",
    re.I,
)
