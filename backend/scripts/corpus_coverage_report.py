#!/usr/bin/env python3
"""Report indexed chunk coverage per scheme_catalog entry (read-only)."""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.database.session import SessionLocal, engine
from app.models import audit, citizen_account, conversation, rag, user  # noqa: F401
from app.services.scheme_search_service import corpus_coverage_counts, load_scheme_catalog


def main() -> int:
    if engine.dialect.name != "postgresql":
        print("SKIP: requires PostgreSQL")
        return 0
    db = SessionLocal()
    try:
        counts = corpus_coverage_counts(db)
        catalog = load_scheme_catalog()
        print(f"catalog_schemes={len(catalog)}")
        supported = 0
        thin = 0
        missing = 0
        for entry in catalog:
            eid = str(entry.get("id") or "")
            n = int(counts.get(eid, 0))
            name = str(entry.get("name") or eid)[:50]
            if n >= 5:
                supported += 1
                band = "ok"
            elif n >= 1:
                thin += 1
                band = "thin"
            else:
                missing += 1
                band = "missing"
            print(f"  {band:7} chunks={n:4} id={eid!r} name={name!r}")
        print(f"summary supported(>=5)={supported} thin(1-4)={thin} missing(0)={missing}")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
