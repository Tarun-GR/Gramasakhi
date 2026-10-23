#!/usr/bin/env python3
"""Read-only RAG knowledge-base diagnostics (no secrets printed)."""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from sqlalchemy import text

from app.core.config import settings
from app.database.session import SessionLocal, engine
from app.services.myscheme_service import normalize_scheme_key


def main() -> int:
    dialect = engine.dialect.name
    print(f"dialect={dialect}")
    print(f"embedding_provider={(settings.EMBEDDING_PROVIDER or '').strip()}")
    print(f"embedding_model={settings.EMBEDDING_MODEL}")
    print(f"gemini_embedding_model={getattr(settings, 'GEMINI_EMBEDDING_MODEL', '')}")
    print(f"embedding_dimensions={settings.EMBEDDING_DIMENSIONS}")

    if dialect != "postgresql":
        print("SKIP: not PostgreSQL")
        return 0

    db = SessionLocal()
    try:
        total = db.execute(text("SELECT COUNT(*) FROM document_chunks")).scalar() or 0
        with_emb = db.execute(
            text("SELECT COUNT(*) FROM document_chunks WHERE embedding IS NOT NULL")
        ).scalar() or 0
        with_text = db.execute(
            text(
                "SELECT COUNT(*) FROM document_chunks "
                "WHERE content IS NOT NULL AND length(trim(content)) >= 40"
            )
        ).scalar() or 0
        print(f"chunks_total={total}")
        print(f"chunks_with_embedding={with_emb}")
        print(f"chunks_substantive_text={with_text}")

        key = normalize_scheme_key("pm-kisan")
        like = f"%{key.replace('-', '%')}%"
        pm_rows = db.execute(
            text(
                """
                SELECT COUNT(*) FROM document_chunks c
                JOIN rag_documents d ON c.document_id = d.id
                WHERE lower(coalesce(d.scheme_name,'')) LIKE :p
                   OR lower(coalesce(d.title,'')) LIKE :p
                   OR lower(coalesce(c.content,'')) LIKE :p
                """
            ),
            {"p": like},
        ).scalar() or 0
        print(f"pm_kisan_related_chunks={pm_rows}")

        sample = db.execute(
            text(
                """
                SELECT d.title, d.scheme_name, d.source,
                       length(c.content) AS content_len,
                       c.embedding IS NOT NULL AS has_emb
                FROM document_chunks c
                JOIN rag_documents d ON c.document_id = d.id
                WHERE lower(coalesce(d.scheme_name,'')) LIKE :p
                   OR lower(coalesce(d.title,'')) LIKE :p
                   OR lower(c.content) LIKE :p
                ORDER BY c.chunk_index ASC
                LIMIT 5
                """
            ),
            {"p": like},
        ).fetchall()
        for i, r in enumerate(sample, 1):
            print(
                f"  sample{i}: title={r.title!r} scheme={r.scheme_name!r} "
                f"len={r.content_len} emb={r.has_emb} source={str(r.source)[:60]!r}"
            )

        meta = db.execute(
            text(
                """
                SELECT c.metadata::text FROM document_chunks c
                JOIN rag_documents d ON c.document_id = d.id
                WHERE c.metadata IS NOT NULL
                LIMIT 3
                """
            )
        ).fetchall()
        if meta:
            print("metadata_samples_present=yes")
        else:
            print("metadata_samples_present=no")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
