"""H1 — core stability and regression hardening tests."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.core import security
from app.core.config import settings
from app.database.session import Base, SessionLocal, get_db
from app.main import _guard_production_config
from app.models import audit, conversation, citizen_account, rag, user  # noqa: F401
from app.models.conversation import Conversation, Message
from app.models.citizen_account import CitizenAccount
from app.services import conversation_service as cs
from app.services import rag as rag_service


class TestH1StabilityHelpers(unittest.TestCase):
    def test_malformed_conversation_id_returns_404_not_500(self):
        db_path = "test_h1_malformed_conv.db"
        if os.path.exists(db_path):
            os.remove(db_path)
        engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
        Base.metadata.create_all(bind=engine)
        Session = sessionmaker(bind=engine)

        def override():
            db = Session()
            try:
                yield db
            finally:
                db.close()

        from app.main import app

        app.dependency_overrides[get_db] = override
        client = TestClient(app)
        db = Session()
        account = CitizenAccount(
            phone_number="9444444444",
            password_hash=security.get_password_hash("password123"),
            display_name="H1",
        )
        db.add(account)
        db.commit()
        token = security.create_access_token(subject=str(account.id))
        db.close()

        res = client.get(
            "/api/chat/conversations/not-a-valid-uuid",
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(res.status_code, 404, res.text)
        app.dependency_overrides.clear()
        engine.dispose()
        os.remove(db_path)

    def test_oversized_chat_message_rejected(self):
        from pydantic import ValidationError

        from app.schemas.chat import ChatRequest

        with self.assertRaises(ValidationError):
            ChatRequest(message="x" * 8001)

    def test_guard_production_config_skips_under_unittest(self):
        with patch.object(settings, "SECRET_KEY", "gramsakhi_very_secret_key_change_me_in_production"):
            with patch.object(settings, "DATABASE_URL", "postgresql://user:pass@host/db"):
                _guard_production_config()


class TestH1DatabaseSession(unittest.TestCase):
    def test_get_db_rolls_back_on_exception(self):
        from app.database import session as db_session

        db_path = "test_h1_rollback.db"
        if os.path.exists(db_path):
            os.remove(db_path)
        engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        original = db_session.SessionLocal
        db_session.SessionLocal = TestSession
        try:
            gen = db_session.get_db()
            db = next(gen)
            db.execute(text("SELECT 1"))
            with self.assertRaises(RuntimeError):
                gen.throw(RuntimeError("simulated handler failure"))
            fresh = TestSession()
            self.assertEqual(fresh.execute(text("SELECT 1")).scalar(), 1)
            fresh.close()
        finally:
            db_session.SessionLocal = original
            engine.dispose()
            if os.path.exists(db_path):
                os.remove(db_path)


class TestH1ChatContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db_path = "test_h1_chat.db"
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

        from app.main import app

        cls.app = app
        app.dependency_overrides[get_db] = override
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        cls.app.dependency_overrides.clear()
        cls.engine.dispose()
        if os.path.exists(cls.db_path):
            os.remove(cls.db_path)

    def setUp(self):
        db = self.SessionLocal()
        db.query(Message).delete()
        db.query(Conversation).delete()
        db.query(CitizenAccount).delete()
        self.account = CitizenAccount(
            phone_number="9555555555",
            password_hash=security.get_password_hash("password123"),
            display_name="H1",
        )
        db.add(self.account)
        db.commit()
        db.refresh(self.account)
        self.token = security.create_access_token(subject=str(self.account.id))
        db.close()

    def _auth(self):
        return {"Authorization": f"Bearer {self.token}"}

    def test_assistant_message_id_null_when_persist_fails(self):
        def fake_rag(*args, **kwargs):
            return {
                "answer": "Answer",
                "confidence": "high",
                "reason": "ok",
                "sources": [],
                "validated": True,
                "llm_invoked": True,
                "knowledge_source": "indexed",
                "official_sources": [],
            }

        real_store = cs.store_message

        def store_side_effect(db, conversation_id, *, role, **kwargs):
            if role == "assistant":
                raise RuntimeError("db write failed")
            return real_store(db, conversation_id, role=role, **kwargs)

        with patch.object(rag_service, "answer_with_evidence_gate", side_effect=fake_rag):
            with patch.object(cs, "store_message", side_effect=store_side_effect):
                res = self.client.post(
                    "/api/chat",
                    json={"message": "Tell me about PM-KISAN"},
                    headers=self._auth(),
                )
        self.assertEqual(res.status_code, 200, res.text)
        body = res.json()
        self.assertIsNone(body.get("assistant_message_id"))
        self.assertNotEqual(body.get("assistant_message_id"), "None")


if __name__ == "__main__":
    unittest.main()
