"""
Seed small verified demo scheme texts into Supabase + rebuild hybrid indexes.

Usage (from backend/):
  .venv\\Scripts\\python.exe scripts\\seed_demo_schemes.py
"""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.database.session import SessionLocal
from app.models import user as _user_model  # noqa: F401 — mapper dependency
from app.models.rag import RagDocument
from app.services.index_builder import IndexBuilder, set_index_builder
from app.services.rag import ingest_raw_bytes

SEEDS = [
    {
        "file": BACKEND_ROOT / "data" / "demo_seeds" / "shakti_scheme.txt",
        "title": "Karnataka Shakti Scheme — Free Bus Travel",
        "scheme_name": "Shakti Scheme",
        "ministry": "Transport Department, Karnataka",
        "state": "Karnataka",
        "category": "Transport",
        "source": "demo_seed://shakti_scheme",
    },
    {
        "file": BACKEND_ROOT / "data" / "demo_seeds" / "pmfby_scheme.txt",
        "title": "Pradhan Mantri Fasal Bima Yojana (PMFBY)",
        "scheme_name": "PMFBY",
        "ministry": "Ministry of Agriculture & Farmers Welfare",
        "state": "Central",
        "category": "Agriculture",
        "source": "demo_seed://pmfby_scheme",
    },
]


def main() -> int:
    db = SessionLocal()
    created = 0
    reused = 0
    try:
        for seed in SEEDS:
            path: Path = seed["file"]
            if not path.is_file():
                print(f"MISSING {path}")
                continue
            content = path.read_bytes()
            existing = (
                db.query(RagDocument)
                .filter(RagDocument.source == seed["source"])
                .first()
            )
            if existing:
                print(f"REUSE {seed['scheme_name']} id={existing.id}")
                reused += 1
                continue
            doc = ingest_raw_bytes(
                db,
                uploaded_by=None,
                title=seed["title"],
                category=seed["category"],
                version="2026-demo",
                contents=content,
                ext=".txt",
                scheme_name=seed["scheme_name"],
                ministry=seed["ministry"],
                state=seed["state"],
                source=seed["source"],
                language="en",
                document_type="DEMO_SEED",
                extra_metadata={"ingestion_type": "manual_upload", "demo_seed": True},
            )
            print(f"INGEST {seed['scheme_name']} id={doc.id}")
            created += 1

        builder = IndexBuilder()
        stats = builder.build_all(db)
        set_index_builder(builder)
        print("INDEX_REBUILD", stats)
        print(f"Done created={created} reused={reused}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
