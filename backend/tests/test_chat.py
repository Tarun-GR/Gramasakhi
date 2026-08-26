"""Phase 6 — chat API ownership / auth smoke tests."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core import security
from app.core.config import settings
from app.database.session import Base, get_db
from app.main import app
from app.models import citizen_account, user, rag, audit, conversation  # noqa: F401
from app.models.conversation import Conversation, Message
from app.models.citizen_account import CitizenAccount
from app.services import rag as rag_service


class TestChatAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db_path = "test_chat_api_phase6.db"
        if os.path.exists(cls.db_path):
            try:
                os.remove(cls.db_path)
            except Exception:
                pass
        cls.engine = create_engine(
            f"sqlite:///{cls.db_path}", connect_args={"check_same_thread": False}
        )
        Base.metadata.drop_all(bind=cls.engine)
        Base.metadata.create_all(bind=cls.engine)
        cls.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=cls.engine)
        settings.QUERY_REWRITE_USE_OLLAMA = False

        def _override_db():
            db = cls.SessionLocal()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = _override_db
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides.clear()
        cls.engine.dispose()
        if os.path.exists(cls.db_path):
            try:
                os.remove(cls.db_path)
            except Exception:
                pass

    def setUp(self):
        db = self.SessionLocal()
        db.query(Message).delete()
        db.query(Conversation).delete()
        db.query(CitizenAccount).delete()
        self.a = CitizenAccount(
            phone_number="9111111111",
            password_hash=security.get_password_hash("password123"),
            display_name="A",
        )
        self.b = CitizenAccount(
            phone_number="9222222222",
            password_hash=security.get_password_hash("password123"),
            display_name="B",
        )
        db.add_all([self.a, self.b])
        db.commit()
        db.refresh(self.a)
        db.refresh(self.b)
        self.token_a = security.create_access_token(subject=str(self.a.id))
        self.token_b = security.create_access_token(subject=str(self.b.id))
        self.a_id = str(self.a.id)
        self.b_id = str(self.b.id)
        db.close()

    def _auth(self, token: str):
        return {"Authorization": f"Bearer {token}"}

    def test_chat_creates_conversation(self):
        with patch.object(
            rag_service,
            "answer_with_evidence_gate",
            return_value={
                "answer": "PMAY-G answer",
                "confidence": "high",
                "sources": [],
                "validated": True,
                "llm_invoked": True,
            },
        ):
            res = self.client.post(
                "/api/chat",
                json={"message": "Tell me about PMAY-G.", "conversation_id": None},
                headers=self._auth(self.token_a),
            )
        self.assertEqual(res.status_code, 200, res.text)
        data = res.json()
        self.assertTrue(data["conversation_id"])
        self.assertEqual(data["original_query"], "Tell me about PMAY-G.")
        self.assertTrue(data["llm_invoked"])

    def test_cross_citizen_denied(self):
        with patch.object(
            rag_service,
            "answer_with_evidence_gate",
            return_value={
                "answer": "ok",
                "confidence": "high",
                "sources": [],
                "validated": True,
                "llm_invoked": True,
            },
        ):
            created = self.client.post(
                "/api/chat",
                json={"message": "Tell me about PMAY-G."},
                headers=self._auth(self.token_a),
            ).json()
            denied = self.client.post(
                "/api/chat",
                json={
                    "message": "Who is eligible?",
                    "conversation_id": created["conversation_id"],
                },
                headers=self._auth(self.token_b),
            )
            hist = self.client.get(
                f"/api/chat/{created['conversation_id']}",
                headers=self._auth(self.token_b),
            )
        self.assertEqual(denied.status_code, 404)
        self.assertEqual(hist.status_code, 404)


if __name__ == "__main__":
    unittest.main()
