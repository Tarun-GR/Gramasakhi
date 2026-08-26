#!/usr/bin/env python3
"""Deterministic IVR-A3 contract verification (no live telephony).

Run from backend/:
  .venv/Scripts/python.exe scripts/ivr_a3_verify.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.core import security  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.database.session import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import citizen_account, user, rag, audit, conversation  # noqa: F401,E402
from app.models.citizen_account import CitizenAccount  # noqa: E402
from app.services.ivr.call_state import IvrCallState, set_state  # noqa: E402
from app.services.ivr.chat_adapter import map_chat_evidence_status, resolve_chat_language  # noqa: E402
from app.services.ivr.language_session import (  # noqa: E402
    get_conversation_id,
    reset_session_store,
    set_language,
)

CALL_SID = "CA_VERIFY_IVR_A3"
DB_PATH = "test_ivr_a3_verify.db"


def _check(name: str, ok: bool, detail: str = "") -> bool:
    status = "PASS" if ok else "FAIL"
    suffix = f" — {detail}" if detail else ""
    print(f"  [{status}] {name}{suffix}")
    return ok


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    print("IVR-A3 verification (static contract, no telephony)")

    if os.path.exists(DB_PATH):
        try:
            os.remove(DB_PATH)
        except OSError:
            pass

    engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    db = SessionLocal()
    acct = CitizenAccount(
        phone_number="+910000000088",
        password_hash=security.get_password_hash("verify"),
        display_name="IVR Verify",
    )
    db.add(acct)
    db.commit()
    db.refresh(acct)
    account_id = str(acct.id)
    db.close()

    def _override_db():
        session = SessionLocal()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = _override_db
    reset_session_store()
    client = TestClient(app)
    passed = 0
    total = 0

    def record(name: str, ok: bool, detail: str = "") -> None:
        nonlocal passed, total
        total += 1
        if _check(name, ok, detail):
            passed += 1

    record("PARTIAL evidence mapping", map_chat_evidence_status({"validated": False, "sources": [{"url": "x"}]}) == "PARTIAL")

    set_language(CALL_SID, "hi")
    set_state(CALL_SID, IvrCallState.TRANSCRIBING)
    record("hi → HI", resolve_chat_language(CALL_SID) == "HI")

    missing = client.post("/api/ivr/chat", json={"transcription": "hello"})
    record("CallSid required", missing.status_code == 422)

    with patch.object(settings, "IVR_CITIZEN_ACCOUNT_ID", account_id), patch.object(
        settings, "IVR_WEBHOOK_SHARED_SECRET", ""
    ):
        chat_ok = {
            "conversation_id": "verify-conv",
            "answer": "Verified answer.",
            "validated": True,
            "llm_invoked": True,
            "sources": [],
            "response_language": "HI",
        }
        with patch(
            "app.services.ivr.chat_adapter.conversation_service.handle_citizen_chat",
            return_value=chat_ok,
        ):
            from app.services.ivr.language_session import get_session_store

            get_session_store().set_transcription(CALL_SID, transcription="PM-KISAN question")
            resp = client.post(
                "/api/ivr/chat",
                json={"CallSid": CALL_SID, "language": "EN", "conversation_id": "evil"},
            )
    record("Chat success", resp.status_code == 200 and resp.json().get("success") is True)
    record("Conversation reused on session", get_conversation_id(CALL_SID) == "verify-conv")
    record("Language from session", resp.json().get("language") == "hi")
    record("Transcript not in body", "PM-KISAN question" not in resp.text)

    app.dependency_overrides.clear()
    engine.dispose()
    try:
        os.remove(DB_PATH)
    except OSError:
        pass

    print()
    print(f"Result: {passed}/{total} checks passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
