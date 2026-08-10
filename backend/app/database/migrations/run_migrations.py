"""
Sahyog — One-Time Schema Migration Script
==========================================
Run this ONCE to add the new audit columns to hospital_users:
  - is_first_login  (BOOLEAN, default TRUE)
  - password_changed (BOOLEAN, default FALSE)

Usage:
  cd backend
  python app/database/migrations/run_migrations.py
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from sqlalchemy import text
from app.database.session import engine

MIGRATIONS = [
    # Add is_first_login column — tracks whether the user is still on their generated temp password
    """
    ALTER TABLE hospital_users
    ADD COLUMN IF NOT EXISTS is_first_login BOOLEAN NOT NULL DEFAULT TRUE;
    """,
    # Add password_changed column — set to TRUE once the user successfully changes their password
    """
    ALTER TABLE hospital_users
    ADD COLUMN IF NOT EXISTS password_changed BOOLEAN NOT NULL DEFAULT FALSE;
    """,
]


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
    ]
    with eng.begin() as conn:
        for table, col, coltype in columns:
            try:
                if dialect == "sqlite":
                    rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
                    existing = {r[1] for r in rows}
                    if col in existing:
                        continue
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {coltype}"))
                else:
                    conn.execute(
                        text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} {coltype}")
                    )
            except Exception:
                # Table may not exist yet or column already present
                pass


def run():
    print("=" * 55)
    print("Sahyog — Running schema migrations on hospital_users")
    print("=" * 55)
    with engine.begin() as conn:
        for i, sql in enumerate(MIGRATIONS, 1):
            try:
                conn.execute(text(sql.strip()))
                print(f"  [OK] Migration {i} executed successfully.")
            except Exception as e:
                print(f"  [SKIP] Migration {i} skipped or already applied: {e}")
    ensure_sqlite_columns(engine)
    print("=" * 55)
    print("Done.")

if __name__ == "__main__":
    run()
