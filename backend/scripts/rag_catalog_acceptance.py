#!/usr/bin/env python3
"""Catalog-driven cloud-indexless gate checks (skip_llm). Read-only on DB."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import patch

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

_QUERY = "What is {name}? Explain eligibility and benefits."


def _run_scheme(name: str, query: str) -> Dict[str, Any]:
    from app.core.config import settings
    from app.database.session import SessionLocal, engine
    from app.models import audit, citizen_account, conversation, rag, user  # noqa: F401
    from app.services import rag as rag_service

    if engine.dialect.name != "postgresql":
        return {"skipped": True}

    patches = [
        patch.object(settings, "RUNTIME_PROFILE", "cloud"),
        patch("app.services.index_builder.hybrid_disk_indexes_present", return_value=False),
        patch.object(rag_service, "_pgvector_retrieve", return_value=[]),
    ]
    for p in patches:
        p.start()
    try:
        db = SessionLocal()
        try:
            out = rag_service.answer_with_evidence_gate(
                db,
                query,
                enable_live_fallback=False,
                skip_llm=True,
                response_language="EN",
            )
        finally:
            db.close()
    finally:
        for p in reversed(patches):
            p.stop()

    return {
        "validated": bool(out.get("validated")),
        "reason": out.get("reason"),
        "sources_n": len(out.get("sources") or []),
    }


def main() -> int:
    from app.database.session import SessionLocal, engine
    from app.models import audit, citizen_account, conversation, rag, user  # noqa: F401
    from app.services.scheme_search_service import corpus_coverage_counts, load_scheme_catalog

    parser = argparse.ArgumentParser()
    parser.add_argument("--min-chunks", type=int, default=5)
    parser.add_argument(
        "--exclude-ids",
        default="national-portal,myscheme-hub,seva-sindhu,karnataka-rdpr,karnataka-ahvs,karnataka-food",
        help="Catalog ids that are portals/hubs, not single-scheme evidence",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    skip_ids = {x.strip() for x in (args.exclude_ids or "").split(",") if x.strip()}

    if engine.dialect.name != "postgresql":
        print("SKIP: requires PostgreSQL")
        return 0

    db = SessionLocal()
    try:
        counts = corpus_coverage_counts(db)
    finally:
        db.close()

    results: List[Dict[str, Any]] = []
    for entry in load_scheme_catalog():
        eid = str(entry.get("id") or "")
        if eid in skip_ids:
            continue
        n = int(counts.get(eid, 0))
        if n < args.min_chunks:
            continue
        name = str(entry.get("name") or eid)
        q = _QUERY.format(name=name)
        row = _run_scheme(name, q)
        row["scheme_id"] = eid
        row["chunks"] = n
        results.append(row)

    passed = sum(1 for r in results if r.get("validated"))
    total = len(results)
    summary = {
        "min_chunks": args.min_chunks,
        "schemes_tested": total,
        "passed": passed,
        "pass_rate": round(passed / total, 3) if total else 0.0,
        "results": results,
    }
    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        print(f"catalog_gate schemes={total} passed={passed} rate={summary['pass_rate']}")
        for r in results:
            print(
                f"  {r.get('scheme_id')}: validated={r.get('validated')} "
                f"reason={r.get('reason')} sources={r.get('sources_n')}"
            )
    # Expect most catalog-backed schemes to pass gate when chunks >= min-chunks
    ok = total >= 3 and summary["pass_rate"] >= 0.55
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
