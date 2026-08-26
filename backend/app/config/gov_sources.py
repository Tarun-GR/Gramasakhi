"""
Government / state website source configuration for web ingestion.

This is a data-source layer only — it does not implement retrieval or embeddings.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

CATALOG_PATH = Path(__file__).resolve().parents[2] / "data" / "scheme_catalog.json"

# High-level portal sources (admin can trigger by "source" key)
GOV_SOURCES: List[Dict[str, Any]] = [
    {
        "id": "central",
        "name": "Central Schemes",
        "url": "https://www.myscheme.gov.in/",
        "type": "mixed",
        "state": "central",
        "description": "Curated central/national scheme pages and PDFs",
    },
    {
        "id": "karnataka",
        "name": "Karnataka Schemes",
        "url": "https://sevasindhu.karnataka.gov.in/",
        "type": "mixed",
        "state": "karnataka",
        "description": "Curated Karnataka state scheme portals",
    },
]

CENTRAL_HOSTS = {
    "myscheme.gov.in",
    "www.myscheme.gov.in",
    "rules.myscheme.gov.in",
    "www.rules.myscheme.gov.in",
    "pmkisan.gov.in",
    "www.pmkisan.gov.in",
    "pmfby.gov.in",
    "www.pmfby.gov.in",
    "nha.gov.in",
    "www.nha.gov.in",
    "pmjay.gov.in",
    "www.pmjay.gov.in",
    "india.gov.in",
    "www.india.gov.in",
    "data.gov.in",
    "www.data.gov.in",
    "pib.gov.in",
    "www.pib.gov.in",
    "financialservices.gov.in",
    "www.financialservices.gov.in",
    "nhm.gov.in",
    "www.nhm.gov.in",
    "mohfw.gov.in",
    "www.mohfw.gov.in",
    "rural.nic.in",
    "nrega.nic.in",
    "mnregaweb4.nic.in",
    "nrlm.gov.in",
    "aajeevika.gov.in",
    "www.aajeevika.gov.in",
    "uidai.gov.in",
    "www.uidai.gov.in",
    "digilocker.gov.in",
    "www.digilocker.gov.in",
    "umang.gov.in",
    "www.umang.gov.in",
    "web.umang.gov.in",
    "ap.gov.in",
    "www.ap.gov.in",
    "wcd.karnataka.gov.in",
    "bhagyalaxmi.karnataka.gov.in",
    "education.gov.in",
    "www.education.gov.in",
    "labour.gov.in",
    "www.labour.gov.in",
    "socialjustice.gov.in",
    "www.socialjustice.gov.in",
    "tribal.nic.in",
    "wcd.gov.in",
    "www.wcd.gov.in",
    "jalshakti.gov.in",
    "www.jalshakti.gov.in",
    "powermin.gov.in",
    "www.powermin.gov.in",
    "mnre.gov.in",
    "www.mnre.gov.in",
    "nsdcindia.org",
}


def _host(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


def _is_blocked_host(host: str) -> bool:
    """SSRF guard — block localhost / private / link-local style hosts."""
    if not host:
        return True
    h = host.lower().strip("[]")
    if h in {"localhost", "localhost.localdomain", "0.0.0.0", "::1"}:
        return True
    if h.endswith(".local") or h.endswith(".internal") or h.endswith(".localhost"):
        return True
    # IPv4 private / loopback / link-local
    if re.fullmatch(r"(?:\d{1,3}\.){3}\d{1,3}", h):
        parts = [int(x) for x in h.split(".")]
        if any(p < 0 or p > 255 for p in parts):
            return True
        a, b = parts[0], parts[1]
        if a in (0, 10, 127):
            return True
        if a == 169 and b == 254:
            return True
        if a == 172 and 16 <= b <= 31:
            return True
        if a == 192 and b == 168:
            return True
    if h.startswith("fc") or h.startswith("fd") or h.startswith("fe80"):
        return True
    return False


def is_allowed_url(url: str) -> bool:
    """Trusted-registry domains only (plus SSRF / scheme guards).

    Bare ``.gov.in`` / ``.karnataka.gov.in`` suffix is NOT enough — the host
    (or a registered parent domain) must appear in the trusted source registry.
    Curated CENTRAL_HOSTS are merged into the registry at load time.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return False
    # Block dangerous schemes / userinfo tricks
    if parsed.username or parsed.password:
        return False
    host = _host(url)
    if not host or _is_blocked_host(host):
        return False
    try:
        from app.services.gov_source_registry import (
            ensure_curated_hosts_merged,
            is_domain_in_registry,
        )

        ensure_curated_hosts_merged()
        return is_domain_in_registry(host, enabled_only=True)
    except Exception:
        # Fail closed for citizen/live paths if registry cannot load
        return False


def source_category(url: str) -> str:
    """Return 'karnataka' | 'central' | 'unknown' for an allowed URL."""
    try:
        from app.services.gov_source_registry import find_source_for_url

        src = find_source_for_url(url)
        if src:
            if (src.get("level") or "").lower() == "state" or (
                (src.get("state") or "").lower() == "karnataka"
            ):
                return "karnataka"
            if (src.get("level") or "").lower() == "central":
                return "central"
    except Exception:
        pass
    host = _host(url)
    if host == "karnataka.gov.in" or host.endswith(".karnataka.gov.in"):
        return "karnataka"
    if is_allowed_url(url):
        return "central"
    return "unknown"


def load_catalog() -> Dict[str, Any]:
    if not CATALOG_PATH.exists():
        return {"schemes": []}
    try:
        return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"schemes": []}


def list_catalog_schemes() -> List[Dict[str, Any]]:
    data = load_catalog()
    out = []
    for s in data.get("schemes", []):
        out.append(
            {
                "id": s.get("id"),
                "name": s.get("name"),
                "scope": s.get("scope"),
                "keywords": s.get("keywords", []),
                "ministry": s.get("ministry"),
                "state": s.get("state"),
                "url_count": len(s.get("urls") or []),
            }
        )
    return out


def get_source(source_id: str) -> Optional[Dict[str, Any]]:
    sid = (source_id or "").strip().lower()
    for src in GOV_SOURCES:
        if src["id"] == sid:
            return src
    return None


def schemes_for_source(source_id: str) -> List[Dict[str, Any]]:
    """Return catalog schemes matching a GOV_SOURCES id (central|karnataka)."""
    src = get_source(source_id)
    if not src:
        return []
    scope = src["state"]
    return [
        s
        for s in load_catalog().get("schemes", [])
        if (s.get("scope") or "").lower() == scope
    ]
