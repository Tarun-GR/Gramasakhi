"""One-off (idempotent) data migration: local SQLite -> Supabase Postgres.

Copies citizen accounts, admin users, knowledge-base documents, chunks and audit
logs from the legacy SQLite files into the Supabase database pointed at by
DATABASE_URL. Safe to re-run: every row is matched on its natural key first and
skipped when it already exists.

Usage (from backend/):
    python -m app.database.migrations.migrate_sqlite_to_supabase
    python -m app.database.migrations.migrate_sqlite_to_supabase --dry-run
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text

from app.core.config import settings

BACKEND_DIR = Path(__file__).resolve().parents[3]
# Newest database last so its rows win on conflicting natural keys.
SQLITE_FILES = ["sahyog.db", "gramsakhi.db"]


def norm_uuid(value: Any) -> str | None:
    if value is None:
        return None
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, AttributeError, TypeError):
        return None


def norm_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        raw = str(value).replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(raw)
        except ValueError:
            return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def norm_json(value: Any) -> str | None:
    if value in (None, ""):
        return None
    if isinstance(value, (dict, list)):
        return json.dumps(value)
    return str(value)


def sqlite_rows(con: sqlite3.Connection, table: str) -> list[dict]:
    try:
        cur = con.execute(f"select * from {table}")
    except sqlite3.OperationalError:
        return []
    return [dict(r) for r in cur.fetchall()]


class Migrator:
    def __init__(self, conn, dry_run: bool):
        self.conn = conn
        self.dry_run = dry_run
        self.user_ids: dict[str, str] = {}  # old sqlite user id -> supabase user id
        self.stats: dict[str, dict[str, int]] = {}

    def bump(self, table: str, key: str) -> None:
        self.stats.setdefault(table, {"inserted": 0, "skipped": 0, "failed": 0})[key] += 1

    def exec(self, sql: str, params: dict) -> None:
        if self.dry_run:
            return
        self.conn.execute(text(sql), params)

    def scalar(self, sql: str, params: dict):
        return self.conn.execute(text(sql), params).scalar()

    # ---------------------------------------------------------------- users
    def migrate_users(self, rows: list[dict]) -> None:
        for row in rows:
            old_id = norm_uuid(row.get("id"))
            email = (row.get("email") or "").strip().lower()
            if not email:
                self.bump("users", "failed")
                continue

            existing = self.scalar(
                "select id from public.users where lower(email) = :email", {"email": email}
            )
            if existing:
                if old_id:
                    self.user_ids[old_id] = str(existing)
                self.bump("users", "skipped")
                continue

            new_id = old_id or str(uuid.uuid4())
            try:
                self.exec(
                    """
                    insert into public.users
                        (id, email, password_hash, first_name, last_name, phone_number,
                         role, is_active, created_at, updated_at, deleted_at)
                    values
                        (:id, :email, :password_hash, :first_name, :last_name, :phone_number,
                         :role, :is_active, :created_at, :updated_at, :deleted_at)
                    """,
                    {
                        "id": new_id,
                        "email": row.get("email"),
                        "password_hash": row.get("password_hash"),
                        "first_name": row.get("first_name") or "",
                        "last_name": row.get("last_name") or "",
                        "phone_number": row.get("phone_number"),
                        "role": row.get("role") or "SUPER_ADMIN",
                        "is_active": bool(row.get("is_active", True)),
                        "created_at": norm_dt(row.get("created_at")) or datetime.now(timezone.utc),
                        "updated_at": norm_dt(row.get("updated_at")) or datetime.now(timezone.utc),
                        "deleted_at": norm_dt(row.get("deleted_at")),
                    },
                )
            except Exception as exc:  # noqa: BLE001
                print(f"    users {email}: {type(exc).__name__} {str(exc)[:120]}")
                self.bump("users", "failed")
                continue
            if old_id:
                self.user_ids[old_id] = new_id
            self.bump("users", "inserted")

    # ------------------------------------------------------ family_accounts
    def migrate_family_accounts(self, rows: list[dict]) -> None:
        for row in rows:
            phone = (row.get("phone_number") or "").strip()
            if not phone:
                self.bump("family_accounts", "failed")
                continue
            if self.scalar(
                "select id from family_accounts where phone_number = :p", {"p": phone}
            ):
                self.bump("family_accounts", "skipped")
                continue
            try:
                self.exec(
                    """
                    insert into family_accounts
                        (id, phone_number, password_hash, display_name, is_active,
                         created_at, updated_at)
                    values
                        (:id, :phone_number, :password_hash, :display_name, :is_active,
                         :created_at, :updated_at)
                    """,
                    {
                        "id": norm_uuid(row.get("id")) or str(uuid.uuid4()),
                        "phone_number": phone,
                        "password_hash": row.get("password_hash"),
                        "display_name": row.get("display_name"),
                        "is_active": bool(row.get("is_active", True)),
                        "created_at": norm_dt(row.get("created_at")) or datetime.now(timezone.utc),
                        "updated_at": norm_dt(row.get("updated_at")) or datetime.now(timezone.utc),
                    },
                )
            except Exception as exc:  # noqa: BLE001
                print(f"    family_accounts {phone}: {type(exc).__name__} {str(exc)[:120]}")
                self.bump("family_accounts", "failed")
                continue
            self.bump("family_accounts", "inserted")

    # ------------------------------------------------------- rag documents
    def migrate_documents(self, docs: list[dict], chunks: list[dict]) -> None:
        migrated_doc_ids: set[str] = set()
        for row in docs:
            doc_id = norm_uuid(row.get("id"))
            if not doc_id:
                self.bump("rag_documents", "failed")
                continue
            if self.scalar("select id from rag_documents where id = :id", {"id": doc_id}):
                migrated_doc_ids.add(doc_id)
                self.bump("rag_documents", "skipped")
                continue

            uploader = norm_uuid(row.get("uploaded_by"))
            uploader = self.user_ids.get(uploader, None) if uploader else None
            try:
                self.exec(
                    """
                    insert into rag_documents
                        (id, hospital_id, uploaded_by, title, file_url, category, version,
                         scheme_name, ministry, state, source, language, document_type,
                         indexing_status, document_hash, last_ingested_at, created_at, updated_at)
                    values
                        (:id, :hospital_id, :uploaded_by, :title, :file_url, :category, :version,
                         :scheme_name, :ministry, :state, :source, :language, :document_type,
                         :indexing_status, :document_hash, :last_ingested_at, :created_at,
                         :updated_at)
                    """,
                    {
                        "id": doc_id,
                        "hospital_id": norm_uuid(row.get("hospital_id")),
                        "uploaded_by": uploader,
                        "title": row.get("title") or "Untitled",
                        "file_url": row.get("file_url") or "",
                        "category": row.get("category") or "schemes",
                        "version": row.get("version") or "1.0",
                        "scheme_name": row.get("scheme_name"),
                        "ministry": row.get("ministry"),
                        "state": row.get("state"),
                        "source": row.get("source"),
                        "language": row.get("language"),
                        "document_type": row.get("document_type"),
                        "indexing_status": row.get("indexing_status") or "INDEXED",
                        "document_hash": row.get("document_hash"),
                        "last_ingested_at": norm_dt(row.get("last_ingested_at")),
                        "created_at": norm_dt(row.get("created_at")) or datetime.now(timezone.utc),
                        "updated_at": norm_dt(row.get("updated_at")) or datetime.now(timezone.utc),
                    },
                )
            except Exception as exc:  # noqa: BLE001
                print(f"    rag_documents {row.get('title')}: {type(exc).__name__} {str(exc)[:120]}")
                self.bump("rag_documents", "failed")
                continue
            migrated_doc_ids.add(doc_id)
            self.bump("rag_documents", "inserted")

        for row in chunks:
            chunk_id = norm_uuid(row.get("id"))
            doc_id = norm_uuid(row.get("document_id"))
            if not chunk_id or doc_id not in migrated_doc_ids:
                self.bump("document_chunks", "skipped")
                continue
            if self.scalar("select id from document_chunks where id = :id", {"id": chunk_id}):
                self.bump("document_chunks", "skipped")
                continue

            embedding = row.get("embedding")
            if isinstance(embedding, (bytes, bytearray)):
                embedding = embedding.decode("utf-8", errors="ignore")
            if isinstance(embedding, str):
                embedding = embedding.strip()
            if not embedding:
                self.bump("document_chunks", "failed")
                continue
            try:
                self.exec(
                    """
                    insert into document_chunks
                        (id, document_id, chunk_index, content, embedding, metadata, created_at)
                    values
                        (:id, :document_id, :chunk_index, :content, cast(:embedding as vector),
                         cast(:metadata as jsonb), :created_at)
                    """,
                    {
                        "id": chunk_id,
                        "document_id": doc_id,
                        "chunk_index": row.get("chunk_index") or 0,
                        "content": row.get("content") or "",
                        "embedding": embedding,
                        "metadata": norm_json(row.get("metadata")),
                        "created_at": norm_dt(row.get("created_at")) or datetime.now(timezone.utc),
                    },
                )
            except Exception as exc:  # noqa: BLE001
                print(f"    document_chunks {chunk_id}: {type(exc).__name__} {str(exc)[:140]}")
                self.bump("document_chunks", "failed")
                continue
            self.bump("document_chunks", "inserted")

    # ----------------------------------------------------------- audit logs
    def migrate_audit_logs(self, rows: list[dict]) -> None:
        for row in rows:
            log_id = norm_uuid(row.get("id"))
            record_id = norm_uuid(row.get("record_id"))
            if not log_id or not record_id:
                self.bump("audit_logs", "skipped")
                continue
            if self.scalar("select id from audit_logs where id = :id", {"id": log_id}):
                self.bump("audit_logs", "skipped")
                continue
            user_id = norm_uuid(row.get("user_id"))
            user_id = self.user_ids.get(user_id, None) if user_id else None
            try:
                self.exec(
                    """
                    insert into audit_logs
                        (id, user_id, action, table_name, record_id, old_values, new_values,
                         ip_address, user_agent, created_at)
                    values
                        (:id, :user_id, :action, :table_name, :record_id,
                         cast(:old_values as jsonb), cast(:new_values as jsonb),
                         :ip_address, :user_agent, :created_at)
                    """,
                    {
                        "id": log_id,
                        "user_id": user_id,
                        "action": row.get("action") or "UNKNOWN",
                        "table_name": row.get("table_name") or "unknown",
                        "record_id": record_id,
                        "old_values": norm_json(row.get("old_values")),
                        "new_values": norm_json(row.get("new_values")),
                        "ip_address": row.get("ip_address"),
                        "user_agent": row.get("user_agent"),
                        "created_at": norm_dt(row.get("created_at")) or datetime.now(timezone.utc),
                    },
                )
            except Exception as exc:  # noqa: BLE001
                print(f"    audit_logs {log_id}: {type(exc).__name__} {str(exc)[:120]}")
                self.bump("audit_logs", "failed")
                continue
            self.bump("audit_logs", "inserted")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="report without writing")
    args = parser.parse_args()

    target = settings.DATABASE_URL
    if target.startswith("sqlite"):
        print("DATABASE_URL still points at SQLite. Point it at Supabase first.")
        return 1

    print(f"Target : {target.split('@')[-1]}")
    print(f"Mode   : {'DRY RUN' if args.dry_run else 'WRITE'}\n")

    engine = create_engine(target)
    with engine.begin() as conn:
        migrator = Migrator(conn, args.dry_run)
        for name in SQLITE_FILES:
            path = BACKEND_DIR / name
            if not path.exists():
                print(f"[skip] {name} (not found)")
                continue
            print(f"[read] {name}")
            src = sqlite3.connect(path)
            src.row_factory = sqlite3.Row
            try:
                migrator.migrate_users(sqlite_rows(src, "users"))
                migrator.migrate_family_accounts(sqlite_rows(src, "family_accounts"))
                migrator.migrate_documents(
                    sqlite_rows(src, "rag_documents"), sqlite_rows(src, "document_chunks")
                )
                migrator.migrate_audit_logs(sqlite_rows(src, "audit_logs"))
            finally:
                src.close()

        if args.dry_run:
            conn.rollback()

    print("\nSummary")
    for table, counts in migrator.stats.items():
        print(
            f"  {table:<18} inserted={counts['inserted']} "
            f"skipped={counts['skipped']} failed={counts['failed']}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
