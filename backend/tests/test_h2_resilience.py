"""H2 — API, error, and dependency resilience regression tests."""

from __future__ import annotations

import json
import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from app.core import security
from app.database.session import Base, get_db
from app.main import app
from app.models import audit, conversation, citizen_account, rag, user  # noqa: F401
from app.models.conversation import Conversation, Message
from app.models.citizen_account import CitizenAccount
from app.services import conversation_service as cs
from app.services import rag as rag_service
from app.services.assistance_continuity import (
    ASSISTANCE_META_MARKER,
    sanitize_assistance_state_for_api,
)
from app.services.eligibility_questioning import SESSION_MARKER


class TestH2HistoryResilience(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db_path = "test_h2_history.db"
        if os.path.exists(cls.db_path):
            os.remove(cls.db_path)
        cls.engine = create_engine(
            f"sqlite:///{cls.db_path}", connect_args={"check_same_thread": False}
        )
        Base.metadata.create_all(bind=cls.engine)
        cls.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=cls.engine)

        def override():
            db = cls.SessionLocal()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override
        cls.client = TestClient(app, raise_server_exceptions=False)

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides.clear()
        cls.engine.dispose()
        if os.path.exists(cls.db_path):
            os.remove(cls.db_path)

    def setUp(self):
        db = self.SessionLocal()
        db.query(Message).delete()
        db.query(Conversation).delete()
        db.query(CitizenAccount).delete()
        self.account = CitizenAccount(
            phone_number="9666666666",
            password_hash=security.get_password_hash("password123"),
            display_name="H2",
        )
        db.add(self.account)
        db.commit()
        db.refresh(self.account)
        self.token = security.create_access_token(subject=str(self.account.id))
        db.close()

    def _auth(self):
        return {"Authorization": f"Bearer {self.token}"}

    def test_malformed_sources_json_loads_safely(self):
        db = self.SessionLocal()
        conv = cs.create_conversation(db, self.account)
        msg = Message(
            conversation_id=str(conv.id),
            role="assistant",
            content="Hello",
            sources_json=json.dumps(123),
            official_sources_json=json.dumps({"bad": True}),
        )
        db.add(msg)
        db.commit()
        cid = str(conv.id)
        db.close()

        res = self.client.get(f"/api/chat/conversations/{cid}", headers=self._auth())
        self.assertEqual(res.status_code, 200, res.text)
        assistant = next(m for m in res.json()["messages"] if m["role"] == "assistant")
        self.assertEqual(assistant["sources"], [])
        self.assertEqual(assistant["official_sources"], [])

    def test_corrupt_eligibility_session_does_not_500_history(self):
        db = self.SessionLocal()
        conv = cs.create_conversation(db, self.account)
        bad_session = {"conversation_id": str(conv.id), "known_information": 42}
        sources = [
            {"_internal": SESSION_MARKER, "session": bad_session},
            {
                "_internal": ASSISTANCE_META_MARKER,
                "meta": {"missing_information": "income", "detected_scheme": "PM-KISAN"},
            },
        ]
        db.add(
            Message(
                conversation_id=str(conv.id),
                role="assistant",
                content="Check eligibility",
                sources_json=json.dumps(sources),
            )
        )
        conv.active_scheme_context = "PM-KISAN"
        db.commit()
        cid = str(conv.id)
        db.close()

        res = self.client.get(f"/api/chat/conversations/{cid}", headers=self._auth())
        self.assertEqual(res.status_code, 200, res.text)
        body = res.json()
        self.assertIn("messages", body)
        state = body.get("assistance_state") or {}
        self.assertEqual(state.get("detected_scheme"), "PM-KISAN")
        self.assertEqual(state.get("missing_information"), ["income"])

    def test_sanitize_assistance_state_coerces_types(self):
        raw = {
            "missing_information": "income",
            "known_information": {"age": 30},
            "eligibility_session_active": 1,
            "detected_scheme": "PM-KISAN",
            "scheme_guidance": {"documents": ["Aadhaar"]},
        }
        clean = sanitize_assistance_state_for_api(raw)
        self.assertEqual(clean["missing_information"], ["income"])
        self.assertTrue(clean["eligibility_session_active"])
        self.assertEqual(clean["scheme_guidance"]["documents"], ["Aadhaar"])


class TestH2APIErrors(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db_path = "test_h2_api.db"
        if os.path.exists(cls.db_path):
            os.remove(cls.db_path)
        cls.engine = create_engine(
            f"sqlite:///{cls.db_path}", connect_args={"check_same_thread": False}
        )
        Base.metadata.create_all(bind=cls.engine)
        cls.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=cls.engine)

        def override():
            db = cls.SessionLocal()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override
        cls.client = TestClient(app, raise_server_exceptions=False)

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides.clear()
        cls.engine.dispose()
        if os.path.exists(cls.db_path):
            os.remove(cls.db_path)

    def setUp(self):
        db = self.SessionLocal()
        db.query(Message).delete()
        db.query(Conversation).delete()
        db.query(CitizenAccount).delete()
        self.account = CitizenAccount(
            phone_number="9777777777",
            password_hash=security.get_password_hash("password123"),
            display_name="H2",
        )
        db.add(self.account)
        db.commit()
        self.token = security.create_access_token(subject=str(self.account.id))
        db.close()

    def _auth(self):
        return {"Authorization": f"Bearer {self.token}"}

    def test_database_error_returns_503_not_stack_trace(self):
        with patch.object(
            cs,
            "list_conversations",
            side_effect=SQLAlchemyError("connection lost"),
        ):
            res = self.client.get("/api/chat/conversations", headers=self._auth())
        self.assertEqual(res.status_code, 503)
        self.assertIn("temporarily unavailable", res.json()["detail"].lower())
        self.assertNotIn("connection lost", res.text)

    def test_chat_pipeline_failure_returns_503(self):
        with patch.object(
            cs,
            "handle_citizen_chat",
            side_effect=RuntimeError("pipeline exploded"),
        ):
            res = self.client.post(
                "/api/chat",
                json={"message": "Tell me about PM-KISAN"},
                headers=self._auth(),
            )
        self.assertEqual(res.status_code, 503)
        self.assertIn("could not complete", res.json()["detail"].lower())
        self.assertNotIn("pipeline exploded", res.text)

    def test_ollama_unavailable_uses_existing_fallback(self):
        from app.services import llm_service

        evidence = [
            {
                "content": (
                    "PM-KISAN provides income support of Rs 6000 per year to eligible "
                    "landholding farmer families across India."
                ),
                "source": "https://gov.in/pm-kisan",
            }
        ]
        with patch.object(
            llm_service,
            "_generate_once",
            side_effect=ConnectionError("refused"),
        ):
            out = llm_service.generate_answer(
                "What is PM-KISAN?",
                evidence,
                response_language="EN",
            )
        self.assertFalse(out.get("success"))
        self.assertEqual(out.get("error"), llm_service.LLM_UNAVAILABLE)


if __name__ == "__main__":
    unittest.main()
