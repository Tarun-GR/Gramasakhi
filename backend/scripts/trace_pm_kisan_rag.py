#!/usr/bin/env python3
"""Trace PM-KISAN retrieval + evidence gate (read-only, sanitized logs)."""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.core.config import settings
from app.database.session import SessionLocal
from app.models import audit, citizen_account, conversation, rag, user  # noqa: F401
from app.services import rag as rag_service
from app.services.evidence_validator import EvidenceValidator
from app.services.index_builder import hybrid_disk_indexes_present
from app.services.runtime_profile import is_cloud_runtime


QUERY = "What is PM-KISAN? Explain eligibility and benefits."


def _summarize_docs(docs, limit=5):
    for d in docs[:limit]:
        cid = str(d.get("chunk_id") or "")[:8]
        score = d.get("similarity_score") or d.get("hybrid_score")
        title = (d.get("document_title") or d.get("scheme_name") or "")[:40]
        clen = len(str(d.get("content") or ""))
        print(f"    chunk={cid} score={score} title={title!r} chars={clen}")


def main() -> int:
    print(f"cloud_runtime={is_cloud_runtime()}")
    print(f"hybrid_disk={hybrid_disk_indexes_present()}")
    print(f"embedding_provider={settings.EMBEDDING_PROVIDER}")
    print(f"query={QUERY!r}")

    db = SessionLocal()
    try:
        # Direct paths
        try:
            pv = rag_service._pgvector_retrieve(db, QUERY, limit=5)
            print(f"pgvector_hits={len(pv)}")
            _summarize_docs(pv)
        except Exception as e:
            print(f"pgvector_error={type(e).__name__}: {e}")

        try:
            st = rag_service._scheme_text_retrieve(
                db, QUERY, scheme_hint="PM-KISAN", scheme_id_hint="pm-kisan", limit=5
            )
            print(f"scheme_text_hits={len(st)}")
            _summarize_docs(st)
        except Exception as e:
            print(f"scheme_text_error={type(e).__name__}: {e}")

        result = rag_service.answer_with_evidence_gate(
            db,
            QUERY,
            enable_live_fallback=False,
            response_language="EN",
        )
        print(f"gate_reason={result.get('reason')}")
        print(f"validated={result.get('validated')} llm_invoked={result.get('llm_invoked')}")
        print(f"knowledge_source={result.get('knowledge_source')}")
        print(f"sources_count={len(result.get('sources') or [])}")
        sig = result.get("signals") or {}
        if isinstance(sig, dict) and sig:
            for k in ("relevance", "coverage", "agreement"):
                if k in sig:
                    print(f"  signal_{k}={sig[k]}")

        # Validator alone on scheme_text docs
        if st:
            v = EvidenceValidator()
            vr = v.validate(QUERY, st)
            print(f"validator_on_scheme_text ok={vr.ok} reason={vr.reason}")
            if vr.signals.get("coverage"):
                print(f"  coverage={vr.signals['coverage']}")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
