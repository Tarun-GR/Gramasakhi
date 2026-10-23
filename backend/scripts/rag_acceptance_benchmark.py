#!/usr/bin/env python3
"""
RAG acceptance benchmark — local cloud-indexless gate checks (no secrets).

Usage:
  python scripts/rag_acceptance_benchmark.py
  python scripts/rag_acceptance_benchmark.py --profile hybrid
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import patch

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

# Canonical cases: id, query, language, expect_validated (None = informational only)
CASES: List[Dict[str, Any]] = [
    {
        "id": "pm_kisan_en",
        "query": "What is PM-KISAN? Explain eligibility and benefits.",
        "lang": "EN",
        "expect_validated": True,
    },
    {
        "id": "pmjay_en",
        "query": "What is Ayushman Bharat PM-JAY? Explain eligibility and benefits for citizens.",
        "lang": "EN",
        "expect_validated": True,
    },
    {
        "id": "gruha_lakshmi_en",
        "query": "What is Gruha Lakshmi scheme? Explain eligibility and benefits.",
        "lang": "EN",
        "expect_validated": True,
    },
    {
        "id": "gruha_jyothi_en",
        "query": "What is Gruha Jyothi? Explain eligibility and benefits.",
        "lang": "EN",
        "expect_validated": None,  # corpus may be missing — report only
    },
    {
        "id": "pmsby_en",
        "query": "What is PM-SBY? Explain eligibility and benefits.",
        "lang": "EN",
        "expect_validated": True,
    },
    {
        "id": "mgnrega_en",
        "query": "What is MGNREGA? Explain eligibility and benefits.",
        "lang": "EN",
        "expect_validated": True,
    },
    {
        "id": "pm_kisan_kn",
        "query": "PM-KISAN ಅರ್ಹತೆ ಮತ್ತು ಪ್ರಯೋಜನಗಳು ಏನು?",
        "lang": "KN",
        "expect_validated": True,
    },
    {
        "id": "unsupported_en",
        "query": "What is the Mars farmer subsidy eligibility in Karnataka?",
        "lang": "EN",
        "expect_validated": False,
    },
]


def _run_case(case: Dict[str, Any], *, cloud_indexless: bool) -> Dict[str, Any]:
    from app.core.config import settings
    from app.database.session import SessionLocal, engine
    from app.models import audit, citizen_account, conversation, rag, user  # noqa: F401
    from app.services import rag as rag_service

    if engine.dialect.name != "postgresql":
        return {"id": case["id"], "skipped": True, "reason": "no_postgresql"}

    patches = []
    if cloud_indexless:
        patches.append(patch.object(settings, "RUNTIME_PROFILE", "cloud"))
        patches.append(
            patch(
                "app.services.index_builder.hybrid_disk_indexes_present",
                return_value=False,
            )
        )
        patches.append(patch.object(rag_service, "_pgvector_retrieve", return_value=[]))

    for p in patches:
        p.start()
    try:
        db = SessionLocal()
        try:
            out = rag_service.answer_with_evidence_gate(
                db,
                case["query"],
                enable_live_fallback=False,
                skip_llm=True,
                response_language=case.get("lang") or "EN",
            )
        finally:
            db.close()
    finally:
        for p in reversed(patches):
            p.stop()

    return {
        "id": case["id"],
        "validated": bool(out.get("validated")),
        "reason": out.get("reason"),
        "sources_n": len(out.get("sources") or []),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--profile",
        choices=("cloud_indexless", "hybrid"),
        default="cloud_indexless",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    cloud = args.profile == "cloud_indexless"

    results = [_run_case(c, cloud_indexless=cloud) for c in CASES]
    failures: List[str] = []
    for c, r in zip(CASES, results):
        exp = c.get("expect_validated")
        if exp is None or r.get("skipped"):
            continue
        if bool(r.get("validated")) != bool(exp):
            failures.append(f"{c['id']}: got validated={r.get('validated')} reason={r.get('reason')}")

    summary = {
        "profile": args.profile,
        "cases": results,
        "failures": failures,
        "pass": len(failures) == 0,
    }
    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        print(f"profile={args.profile} pass={summary['pass']}")
        for r in results:
            print(
                f"  {r.get('id')}: validated={r.get('validated')} "
                f"reason={r.get('reason')} sources={r.get('sources_n')}"
            )
        if failures:
            print("FAILURES:", ", ".join(failures))
    return 0 if summary["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
