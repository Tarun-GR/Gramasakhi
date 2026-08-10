"""Data-driven trusted government source registry (IGOD-backed).

Citizen queries never refresh the registry. Admins (or deploy) refresh it.
Validation requires an enabled registry domain — not bare .gov.in suffix alone.
"""

from __future__ import annotations

import json
import logging
import re
import threading
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import urljoin, urlparse

logger = logging.getLogger("gramsakhi.gov_registry")

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
REGISTRY_PATH = DATA_DIR / "trusted_gov_registry.json"
SEED_PATH = REGISTRY_PATH  # seed is the same file checked into the repo

IGOD_HOME = "https://igod.gov.in/"
IGOD_KA_DEPTS = "https://igod.gov.in/sg/KA/E003/organizations"
IGOD_UNION_MINISTRIES = "https://igod.gov.in/ug/E002/organizations"

# Suffixes that MAY appear on government sites — still require registry membership
_GOV_SUFFIXES = (".gov.in", ".nic.in", ".karnataka.gov.in")

_CATEGORY_KEYWORDS: Dict[str, Tuple[str, ...]] = {
    "agriculture": ("agriculture", "farmer", "kisan", "crop", "pm-kisan", "pmfby", "raitamitra"),
    "housing": ("housing", "pmay", "awas", "house", "ghar", "rural housing"),
    "education": ("education", "school", "scholarship", "student", "college"),
    "employment": ("employment", "mgnrega", "nrega", "job", "labour", "labor"),
    "health": ("health", "ayushman", "pmjay", "hospital", "medical"),
    "welfare": ("welfare", "pension", "social", "backward", "disability", "senior"),
    "food": ("food", "ration", "civil supplies", "pds", "ahara"),
    "finance": ("finance", "insurance", "bima", "bank", "loan"),
    "energy": ("energy", "power", "electricity", "ujjwala"),
    "environment": ("environment", "forest", "climate"),
    "women": ("women", "child", "wcd", "maternity"),
    "industry": ("industry", "commerce", "msme", "startup"),
    "general": ("scheme", "yojana", "government", "karnataka", "india"),
}

_lock = threading.RLock()
_cache: Optional[Dict[str, Any]] = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _host(url_or_host: str) -> str:
    raw = (url_or_host or "").strip().lower()
    if "://" in raw:
        return (urlparse(raw).hostname or "").lower()
    return raw.split("/")[0].split(":")[0]


def _looks_like_gov_domain(host: str) -> bool:
    if not host or _is_ip_or_local(host):
        return False
    return any(host == s.lstrip(".") or host.endswith(s) for s in _GOV_SUFFIXES)


def _is_ip_or_local(host: str) -> bool:
    h = (host or "").lower().strip("[]")
    if h in {"localhost", "0.0.0.0", "::1"}:
        return True
    if re.fullmatch(r"(?:\d{1,3}\.){3}\d{1,3}", h):
        return True
    return False


def _default_registry() -> Dict[str, Any]:
    return {
        "version": 1,
        "source_directory": "IGOD",
        "directory_urls": {
            "home": IGOD_HOME,
            "karnataka_departments": IGOD_KA_DEPTS,
            "union_ministries": IGOD_UNION_MINISTRIES,
        },
        "last_refreshed_at": None,
        "last_refresh_status": "empty",
        "sources": [],
        "rejected": [],
    }


def load_registry(*, force_reload: bool = False) -> Dict[str, Any]:
    global _cache
    with _lock:
        if _cache is not None and not force_reload:
            return deepcopy(_cache)
        if REGISTRY_PATH.exists():
            try:
                data = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
            except Exception as e:  # noqa: BLE001
                logger.warning("Failed to read registry: %s", e)
                data = _default_registry()
        else:
            data = _default_registry()
        data.setdefault("sources", [])
        data.setdefault("rejected", [])
        _cache = data
        return deepcopy(data)


def ensure_curated_hosts_merged() -> None:
    """Merge legacy CENTRAL_HOSTS into registry (memory) without overwriting curated rows."""
    global _cache
    try:
        from app.config.gov_sources import CENTRAL_HOSTS
    except Exception:
        return
    with _lock:
        data = load_registry()
        by_domain = {
            (s.get("domain") or "").lower(): s
            for s in (data.get("sources") or [])
            if s.get("domain")
        }
        changed = False
        for host in CENTRAL_HOSTS:
            h = (host or "").lower()
            if h.startswith("www."):
                h = h[4:]
            if not h or h in by_domain:
                continue
            # Skip non-gov commercial domains unless already curated in seed
            if not (
                h.endswith(".gov.in")
                or h.endswith(".nic.in")
                or h.endswith("gov.in")
                or h.endswith("nic.in")
            ):
                continue
            entry = {
                "id": _slug_id("curated", h, h),
                "name": h,
                "level": "central",
                "state": None,
                "organization": h,
                "domain": h,
                "base_urls": [f"https://{h}/"],
                "categories": ["general"],
                "source_directory": "curated",
                "enabled": True,
                "priority": 450,
                "health": "active",
            }
            by_domain[h] = entry
            changed = True
        if changed:
            data["sources"] = list(by_domain.values())
            # Memory-only merge — avoids rewriting seed JSON on every boot/test
            _cache = deepcopy(data)


def save_registry(data: Dict[str, Any]) -> None:
    global _cache
    with _lock:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        REGISTRY_PATH.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        _cache = deepcopy(data)


def list_sources(
    *,
    level: Optional[str] = None,
    enabled_only: bool = False,
    category: Optional[str] = None,
) -> List[Dict[str, Any]]:
    data = load_registry()
    out = []
    for s in data.get("sources") or []:
        if enabled_only and not s.get("enabled", True):
            continue
        if level and (s.get("level") or "").lower() != level.lower():
            continue
        if category:
            cats = [c.lower() for c in (s.get("categories") or [])]
            if category.lower() not in cats and "general" not in cats:
                # still include if name matches category loosely
                blob = f"{s.get('name')} {s.get('organization')}".lower()
                if category.lower() not in blob:
                    continue
        out.append(s)
    out.sort(key=lambda x: (int(x.get("priority") or 9999), x.get("name") or ""))
    return out


def registry_domains(*, enabled_only: bool = True) -> Set[str]:
    return {
        (s.get("domain") or "").lower()
        for s in list_sources(enabled_only=enabled_only)
        if s.get("domain")
    }


def is_domain_in_registry(host: str, *, enabled_only: bool = True) -> bool:
    """True if host equals a registered domain or is a subdomain of one."""
    h = _host(host)
    if not h or _is_ip_or_local(h):
        return False
    domains = registry_domains(enabled_only=enabled_only)
    if h in domains:
        return True
    for d in domains:
        if h.endswith("." + d):
            return True
    return False


def find_source_for_url(url: str) -> Optional[Dict[str, Any]]:
    h = _host(url)
    best = None
    best_len = -1
    for s in list_sources(enabled_only=True):
        d = (s.get("domain") or "").lower()
        if not d:
            continue
        if h == d or h.endswith("." + d):
            if len(d) > best_len:
                best = s
                best_len = len(d)
    return best


def set_source_enabled(source_id: str, enabled: bool) -> Dict[str, Any]:
    data = load_registry(force_reload=True)
    found = None
    for s in data.get("sources") or []:
        if s.get("id") == source_id:
            s["enabled"] = bool(enabled)
            s["health"] = "active" if enabled else "disabled"
            found = s
            break
    if not found:
        raise KeyError(f"Unknown source_id: {source_id}")
    save_registry(data)
    return found


def classify_query(query: str) -> List[str]:
    """Return ranked category tags for staged department search."""
    q = (query or "").lower()
    scored: List[Tuple[int, str]] = []
    for cat, kws in _CATEGORY_KEYWORDS.items():
        score = sum(3 for kw in kws if kw in q)
        if score:
            scored.append((score, cat))
    scored.sort(key=lambda x: -x[0])
    cats = [c for _, c in scored]
    if "karnataka" in q and "general" not in cats:
        cats.append("general")
    return cats or ["general"]


def prioritize_sources_for_query(query: str, *, limit: int = 8) -> List[Dict[str, Any]]:
    """Stage matching departments first, then expand to other trusted sources."""
    cats = classify_query(query)
    prefer_state = "karnataka" in (query or "").lower()
    enabled = list_sources(enabled_only=True)
    ranked: List[Tuple[int, Dict[str, Any]]] = []
    for s in enabled:
        score = 0
        scats = [c.lower() for c in (s.get("categories") or [])]
        for i, cat in enumerate(cats):
            if cat in scats:
                score += 50 - i * 5
        if prefer_state and (s.get("level") == "state" or (s.get("state") or "").lower() == "karnataka"):
            score += 15
        if not prefer_state and s.get("level") == "central":
            score += 8
        # Always allow some score so expansion stage can use remaining sources
        score += max(0, 20 - int(s.get("priority") or 999) // 50)
        ranked.append((score, s))
    ranked.sort(key=lambda x: (-x[0], int(x[1].get("priority") or 9999)))
    return [s for _, s in ranked[: max(1, limit)]]


def _fetch_html(url: str, timeout: float = 25.0) -> str:
    import httpx

    headers = {
        "User-Agent": "GramSakhiRegistryBot/1.0 (+local; IGOD refresh)",
        "Accept": "text/html,application/xhtml+xml",
    }
    with httpx.Client(follow_redirects=True, timeout=timeout, verify=True) as client:
        resp = client.get(url, headers=headers)
        resp.raise_for_status()
        final = str(resp.url)
        # Redirect must remain on igod / trusted gov
        fh = _host(final)
        if fh not in {"igod.gov.in", "www.igod.gov.in"} and not _looks_like_gov_domain(fh):
            raise ValueError(f"Untrusted redirect destination: {final}")
        return resp.text


def _extract_org_links(html: str, base_url: str) -> List[Dict[str, str]]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html, "html.parser")
    out: List[Dict[str, str]] = []
    seen = set()
    for a in soup.find_all("a", href=True):
        href = (a.get("href") or "").strip()
        text = (a.get_text(" ", strip=True) or "").strip()
        if not href or href.startswith("#"):
            continue
        absolute = urljoin(base_url, href).split("#")[0]
        host = _host(absolute)
        if not host or host in seen:
            continue
        # Organization detail pages on IGOD or external gov sites
        if "igod.gov.in" in host or _looks_like_gov_domain(host):
            seen.add(host if _looks_like_gov_domain(host) else absolute)
            out.append({"url": absolute, "name": text or host, "host": host})
    return out


def _slug_id(prefix: str, name: str, domain: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", (name or domain).lower()).strip("-")[:60]
    return f"{prefix}-{base or domain.replace('.', '-')}"


def _merge_source(
    sources_by_domain: Dict[str, Dict[str, Any]],
    entry: Dict[str, Any],
    *,
    preserve_manual: bool = True,
) -> str:
    """Merge entry; returns 'added' | 'updated' | 'skipped'."""
    domain = (entry.get("domain") or "").lower()
    if not domain or not _looks_like_gov_domain(domain):
        return "skipped"
    existing = sources_by_domain.get(domain)
    if existing:
        if preserve_manual and (existing.get("source_directory") == "curated"):
            # Keep curated priorities/URLs; enrich categories only
            cats = set(existing.get("categories") or [])
            cats.update(entry.get("categories") or [])
            existing["categories"] = sorted(cats)
            return "updated"
        # Refresh non-curated
        for key in ("name", "organization", "base_urls", "level", "state", "categories"):
            if entry.get(key):
                existing[key] = entry[key]
        existing["source_directory"] = entry.get("source_directory") or existing.get(
            "source_directory"
        )
        existing["enabled"] = existing.get("enabled", True)
        return "updated"
    sources_by_domain[domain] = entry
    return "added"


def refresh_registry_from_igod(*, timeout: float = 30.0) -> Dict[str, Any]:
    """
    Refresh trusted registry from IGOD directory pages.

    Does NOT block citizen Q&A — call from admin/deploy only.
    Preserves curated sources. Adds discovered gov domains.
    """
    data = load_registry(force_reload=True)
    sources_by_domain: Dict[str, Dict[str, Any]] = {
        (s.get("domain") or "").lower(): s
        for s in (data.get("sources") or [])
        if s.get("domain")
    }
    rejected: List[Dict[str, Any]] = list(data.get("rejected") or [])
    added: List[str] = []
    updated: List[str] = []
    rejected_now: List[Dict[str, Any]] = []

    targets = [
        ("state", "Karnataka", IGOD_KA_DEPTS),
        ("central", None, IGOD_UNION_MINISTRIES),
        ("central", None, IGOD_HOME),
    ]

    for level, state, page_url in targets:
        try:
            html = _fetch_html(page_url, timeout=timeout)
        except Exception as e:  # noqa: BLE001
            rejected_now.append(
                {"url": page_url, "reason": f"fetch_failed:{type(e).__name__}"}
            )
            continue
        for link in _extract_org_links(html, page_url):
            host = link["host"]
            if host.endswith("igod.gov.in"):
                # Follow IGOD org detail pages for external website links
                try:
                    detail_html = _fetch_html(link["url"], timeout=timeout)
                    for sub in _extract_org_links(detail_html, link["url"]):
                        sh = sub["host"]
                        if sh.endswith("igod.gov.in"):
                            continue
                        if not _looks_like_gov_domain(sh):
                            rejected_now.append(
                                {"url": sub["url"], "reason": "not_gov_suffix"}
                            )
                            continue
                        entry = {
                            "id": _slug_id("igod", sub["name"] or link["name"], sh),
                            "name": sub["name"] or link["name"] or sh,
                            "level": level,
                            "state": state,
                            "organization": sub["name"] or link["name"],
                            "domain": sh,
                            "base_urls": [sub["url"]],
                            "categories": classify_query(sub["name"] or "") or ["general"],
                            "source_directory": "IGOD",
                            "enabled": True,
                            "priority": 500,
                            "health": "active",
                        }
                        result = _merge_source(sources_by_domain, entry)
                        if result == "added":
                            added.append(sh)
                        elif result == "updated":
                            updated.append(sh)
                except Exception as e:  # noqa: BLE001
                    rejected_now.append(
                        {"url": link["url"], "reason": f"detail_failed:{type(e).__name__}"}
                    )
                continue

            if not _looks_like_gov_domain(host):
                rejected_now.append({"url": link["url"], "reason": "not_gov_suffix"})
                continue
            entry = {
                "id": _slug_id("igod", link["name"], host),
                "name": link["name"] or host,
                "level": level,
                "state": state,
                "organization": link["name"],
                "domain": host,
                "base_urls": [link["url"]],
                "categories": classify_query(link["name"] or "") or ["general"],
                "source_directory": "IGOD",
                "enabled": True,
                "priority": 500,
                "health": "active",
            }
            result = _merge_source(sources_by_domain, entry)
            if result == "added":
                added.append(host)
            elif result == "updated":
                updated.append(host)

    # Deduplicate rejected
    seen_rej = {(r.get("url"), r.get("reason")) for r in rejected}
    for r in rejected_now:
        key = (r.get("url"), r.get("reason"))
        if key not in seen_rej:
            rejected.append(r)
            seen_rej.add(key)

    data["sources"] = list(sources_by_domain.values())
    data["rejected"] = rejected[-200:]  # cap growth
    data["last_refreshed_at"] = _now_iso()
    data["last_refresh_status"] = "ok" if (added or updated) else "ok_no_new"
    data["last_refresh_summary"] = {
        "added": sorted(set(added)),
        "updated": sorted(set(updated)),
        "rejected_count": len(rejected_now),
        "total_sources": len(data["sources"]),
        "karnataka_count": sum(
            1
            for s in data["sources"]
            if s.get("level") == "state" or (s.get("state") or "").lower() == "karnataka"
        ),
        "central_count": sum(1 for s in data["sources"] if s.get("level") == "central"),
    }
    save_registry(data)
    logger.info(
        "Registry refresh complete added=%s updated=%s total=%s",
        len(set(added)),
        len(set(updated)),
        len(data["sources"]),
    )
    return data["last_refresh_summary"]


def registry_stats() -> Dict[str, Any]:
    data = load_registry()
    sources = data.get("sources") or []
    enabled = [s for s in sources if s.get("enabled", True)]
    return {
        "total_sources": len(sources),
        "enabled_sources": len(enabled),
        "karnataka_sources": sum(
            1
            for s in sources
            if s.get("level") == "state" or (s.get("state") or "").lower() == "karnataka"
        ),
        "central_sources": sum(1 for s in sources if s.get("level") == "central"),
        "last_refreshed_at": data.get("last_refreshed_at"),
        "last_refresh_status": data.get("last_refresh_status"),
        "last_refresh_summary": data.get("last_refresh_summary"),
        "directory_urls": data.get("directory_urls"),
    }
