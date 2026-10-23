#!/usr/bin/env python3
"""Per-scheme substance vs navigation heuristics on indexed chunks (read-only)."""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from sqlalchemy import text

from app.database.session import SessionLocal, engine
from app.models import audit, citizen_account, conversation, rag, user  # noqa: F401
from app.services.evidence_quality import navigation_heaviness, policy_substance
from app.services.scheme_search_service import load_scheme_catalog


def main() -> int:
    if engine.dialect.name != "postgresql":
        print("SKIP: requires PostgreSQL")
        return 0
    catalog = {str(e.get("id")): str(e.get("name") or "") for e in load_scheme_catalog()}
    db = SessionLocal()
    try:
        rows = db.execute(
            text(
                """
                SELECT coalesce(d.metadata->>'scheme_id', '') AS sid,
                       c.content AS content
                FROM document_chunks c
                JOIN rag_documents d ON c.document_id = d.id
                WHERE length(coalesce(c.content, '')) >= 40
                """
            )
        ).fetchall()
    finally:
        db.close()

    buckets: dict[str, list[tuple[float, float]]] = {}
    for sid, content in rows:
        sid = (sid or "").strip() or "_unknown"
        nav = navigation_heaviness(content or "")
        pol = policy_substance(content or "")
        buckets.setdefault(sid, []).append((nav, pol))

    print(f"schemes_with_chunks={len(buckets)}")
    for sid in sorted(buckets.keys(), key=lambda s: catalog.get(s, s)):
        samples = buckets[sid]
        avg_nav = sum(x[0] for x in samples) / len(samples)
        avg_pol = sum(x[1] for x in samples) / len(samples)
        noisy = sum(1 for n, p in samples if n > 0.35 and p < 0.15)
        name = catalog.get(sid, sid)[:45]
        band = "noisy" if avg_nav > 0.28 and avg_pol < 0.2 else "ok"
        print(
            f"  {band:5} id={sid!r} chunks={len(samples):4} "
            f"avg_nav={avg_nav:.2f} avg_pol={avg_pol:.2f} noisy_chunks={noisy} name={name!r}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
