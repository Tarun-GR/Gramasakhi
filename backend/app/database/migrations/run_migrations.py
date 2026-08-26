"""
GramSakhi schema helpers.

`ensure_sqlite_columns` is invoked on API startup to add missing GramSakhi
columns on older local SQLite databases.

Usage:
  cd backend
  python app/database/migrations/run_migrations.py
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from sqlalchemy import text
from app.database.session import engine


def ensure_sqlite_columns(eng=None) -> None:
    """
    SQLite cannot ADD COLUMN IF NOT EXISTS on older versions reliably via SQLAlchemy
    the same way Postgres does — probe pragma and ALTER missing GramSakhi columns.
    """
    eng = eng or engine
    dialect = eng.dialect.name
    columns = [
        ("rag_documents", "document_hash", "VARCHAR(64)"),
        ("rag_documents", "last_ingested_at", "DATETIME"),
        ("rag_documents", "scheme_name", "VARCHAR(255)"),
        ("rag_documents", "ministry", "VARCHAR(255)"),
        ("rag_documents", "state", "VARCHAR(100)"),
        ("rag_documents", "source", "VARCHAR(255)"),
        ("rag_documents", "language", "VARCHAR(20)"),
        ("rag_documents", "document_type", "VARCHAR(100)"),
        ("rag_documents", "indexing_status", "VARCHAR(50)"),
        ("conversations", "deleted_at", "DATETIME"),
        ("conversations", "last_message_at", "DATETIME"),
        ("messages", "input_mode", "VARCHAR(20)"),
        ("messages", "knowledge_source", "VARCHAR(50)"),
        ("messages", "sources_json", "TEXT"),
        ("messages", "official_sources_json", "TEXT"),
    ]
    with eng.connect() as conn:
        for table, col, coltype in columns:
            try:
                if dialect == "sqlite":
                    rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
                    existing = {r[1] for r in rows}
                    if col in existing:
                        continue
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {coltype}"))
                    conn.commit()
                else:
                    pg_type = (
                        "TIMESTAMPTZ"
                        if coltype.upper() in ("DATETIME", "TIMESTAMP")
                        else coltype
                    )
                    conn.execute(text(f"SAVEPOINT ensure_{table}_{col}"))
                    try:
                        conn.execute(
                            text(
                                f"ALTER TABLE {table} "
                                f"ADD COLUMN IF NOT EXISTS {col} {pg_type}"
                            )
                        )
                        conn.execute(text(f"RELEASE SAVEPOINT ensure_{table}_{col}"))
                        conn.commit()
                    except Exception:
                        conn.execute(text(f"ROLLBACK TO SAVEPOINT ensure_{table}_{col}"))
            except Exception:
                try:
                    conn.rollback()
                except Exception:
                    pass

    if dialect == "postgresql":
        ensure_postgres_rls(eng)


_RLS_TABLES = (
    "users",
    "family_accounts",
    "family_sessions",
    "otp_verifications",
    "rag_documents",
    "document_chunks",
    "conversations",
    "messages",
    "audit_logs",
    "activity_logs",
)


def ensure_postgres_rls(eng=None) -> None:
    """Enable RLS without permissive policies (PostgREST/anon denied; owner API still works)."""
    eng = eng or engine
    if eng.dialect.name != "postgresql":
        return
    with eng.connect() as conn:
        for table in _RLS_TABLES:
            try:
                conn.execute(text(f"ALTER TABLE IF EXISTS {table} ENABLE ROW LEVEL SECURITY"))
                conn.commit()
            except Exception:
                try:
                    conn.rollback()
                except Exception:
                    pass


def run():
    print("=" * 55)
    print("GramSakhi — ensuring schema columns")
    print("=" * 55)
    ensure_sqlite_columns(engine)
    print("=" * 55)
    print("Done.")

if __name__ == "__main__":
    run()
