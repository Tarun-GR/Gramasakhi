#!/usr/bin/env python3
"""Compare retrieval + evidence gate for local hybrid vs simulated cloud_indexless."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.database.session import SessionLocal
from app.models import audit, citizen_account, conversation, rag, user  # noqa: F401
from app.services import rag as rag_service
from app.services.index_builder import hybrid_disk_indexes_present

CASES = [
    (
        "A_pmjay",
        "What is Ayushman Bharat PM-JAY? Explain eligibility and benefits for citizens.",
    ),
    (
        "B_pm_kisan",
        "What is PM-KISAN? Explain eligibility and benefits.",
    ),
    (
        "E_unsupported",
        "What is the official Mars colonization farmer subsidy eligibility in Karnataka?",
    ),
]


def _run_case(label: str, query: str, *, cloud_indexless: bool) -> dict:
    patches = []
    if cloud_indexless:
        patches.append(
            patch(
                "app.services.runtime_profile.is_cloud_runtime",
                return_value=True,
            )
        )
        patches.append(
            patch(
                "app.services.index_builder.hybrid_disk_indexes_present",
                return_value=False,
            )
        )
    for p in patches:
        p.start()
    db = SessionLocal()
    try:
        out = rag_service.answer_with_evidence_gate(
            db,
            query,
            enable_live_fallback=False,
            skip_llm=True,
            response_language="EN",
        )
        return {
            "case": label,
            "cloud_indexless": cloud_indexless,
            "validated": out.get("validated"),
            "reason": out.get("reason"),
            "sources_n": len(out.get("sources") or []),
        }
    finally:
        db.close()
        for p in reversed(patches):
            p.stop()


def _weak_pgvector_only(label: str, query: str) -> dict:
    weak = [
        {
            "chunk_id": "weak1",
            "content": "PM-Kisan Samman Nidhi portal reimbursement operational guidelines.",
            "similarity_score": 0.76,
            "document_title": "PM-Kisan Samman Nidhi",
        }
    ]
    with patch("app.services.runtime_profile.is_cloud_runtime", return_value=True):
        with patch(
            "app.services.index_builder.hybrid_disk_indexes_present",
            return_value=False,
        ):
            with patch.object(rag_service, "_pgvector_retrieve", return_value=weak):
                db = SessionLocal()
                try:
                    out = rag_service.answer_with_evidence_gate(
                        db,
                        query,
                        enable_live_fallback=False,
                        skip_llm=True,
                        response_language="EN",
                    )
                    return {
                        "case": label,
                        "cloud_indexless": True,
                        "validated": out.get("validated"),
                        "reason": out.get("reason"),
                        "sources_n": len(out.get("sources") or []),
                    }
                finally:
                    db.close()


def main() -> int:
    print(f"hybrid_disk_indexes_present={hybrid_disk_indexes_present()}")
    for label, q in CASES:
        local = _run_case(label, q, cloud_indexless=False)
        cloud = _run_case(label, q, cloud_indexless=True)
        print(f"{label} local={local}")
        print(f"{label} cloud={cloud}")
    c = _weak_pgvector_only("C_pm_kisan_weak_pg", CASES[1][1])
    print(f"C_pm_kisan_weak_pg={c}")
    with patch("app.services.runtime_profile.is_cloud_runtime", return_value=True):
        with patch(
            "app.services.index_builder.hybrid_disk_indexes_present",
            return_value=False,
        ):
            with patch.object(rag_service, "_pgvector_retrieve", return_value=[]):
                db = SessionLocal()
                try:
                    out = rag_service.answer_with_evidence_gate(
                        db,
                        CASES[1][1],
                        enable_live_fallback=False,
                        skip_llm=True,
                        response_language="EN",
                    )
                    print(
                        f"D_pm_kisan_empty_pg="
                        f"{{'validated': {out.get('validated')}, 'reason': {out.get('reason')!r}, "
                        f"'sources_n': {len(out.get('sources') or [])}}}"
                    )
                finally:
                    db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
