"""H6 — End-to-end integration regression tests."""

from __future__ import annotations

import json
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
from app.models import audit, conversation, citizen_account, rag, user  # noqa: F401
from app.models.conversation import Conversation, Message
from app.models.citizen_account import CitizenAccount
from app.services import conversation_service as cs
from app.services import rag as rag_service
from app.services.eligibility_questioning import (
    EligibilitySession,
    embed_session_in_sources,
)


class TestH6ActionPlanExplanationIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db_path = "test_h6_integration.db"
        if os.path.exists(cls.db_path):
            try:
                os.remove(cls.db_path)
            except Exception:
                pass
        cls.engine = create_engine(
            f"sqlite:///{cls.db_path}",
            connect_args={"check_same_thread": False},
        )
        Base.metadata.create_all(cls.engine)
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
        self.account = CitizenAccount(
            phone_number="9444444444",
            password_hash=security.get_password_hash("password123"),
            display_name="Citizen",
        )
        db.add(self.account)
        db.commit()
        db.refresh(self.account)
        self.token = security.create_access_token(subject=str(self.account.id))
        db.close()

    def _auth(self):
        return {"Authorization": f"Bearer {self.token}"}

    def _fake_rag(self, *args, **kwargs):
        return {
            "answer": "General scheme information.",
            "confidence": "high",
            "reason": "ok",
            "sources": [
                {
                    "content": "PM-KISAN provides income support to eligible farmer families.",
                    "scheme_name": "PM-KISAN",
                    "source": "https://gov.in/pm-kisan",
                }
            ],
            "validated": True,
            "llm_invoked": True,
            "knowledge_source": "indexed",
            "official_sources": [],
        }

    def test_action_plan_followup_skips_redundant_auto_explanation(self):
        completed = EligibilitySession(
            conversation_id="pending",
            active_scheme="PM-KISAN",
            scheme_id="pm-kisan",
            session_active=False,
            completed=True,
            evaluation_result={
                "status": "ELIGIBLE",
                "scheme_name": "PM-KISAN",
                "criteria_results": [],
            },
        )
        session_sources = embed_session_in_sources([], completed)

        def _apply_plan(**kwargs):
            return {
                "applied": True,
                "answer": "Next step: gather documents and apply on the portal.",
                "action_plan": {"status": "ELIGIBLE", "steps": ["Apply online"]},
                "official_sources": [],
            }

        with patch.object(rag_service, "answer_with_evidence_gate", side_effect=self._fake_rag):
            with patch(
                "app.services.eligibility_explanation.explain_eligibility_evaluation"
            ) as explain_mock:
                explain_mock.return_value = {
                    "answer": "You meet the eligibility criteria.",
                    "llm_invoked": False,
                }
                with patch("app.services.action_plan.apply_action_plan", side_effect=_apply_plan):
                    first = self.client.post(
                        "/api/chat",
                        json={"message": "What is PM-KISAN?"},
                        headers=self._auth(),
                    )
                    self.assertEqual(first.status_code, 200, first.text)
                    cid = first.json()["conversation_id"]

                    db = self.SessionLocal()
                    assistant = (
                        db.query(Message)
                        .filter(Message.conversation_id == cid, Message.role == "assistant")
                        .order_by(Message.id.desc())
                        .first()
                    )
                    assistant.sources_json = json.dumps(session_sources)
                    db.commit()
                    db.close()

                    explain_mock.reset_mock()
                    follow = self.client.post(
                        "/api/chat",
                        json={
                            "message": "What should I do next?",
                            "conversation_id": cid,
                        },
                        headers=self._auth(),
                    )
        self.assertEqual(follow.status_code, 200, follow.text)
        body = follow.json()
        self.assertIn("action_plan", body)
        self.assertIn("Next step", body["answer"])
        explain_mock.assert_not_called()


class TestH6ConversationServiceStagePrecedence(unittest.TestCase):
    def test_auto_explanation_skipped_when_action_plan_followup(self):
        import inspect

        src = inspect.getsource(cs.handle_citizen_chat)
        self.assertIn("not explain_followup and not action_plan_followup", src)


if __name__ == "__main__":
    unittest.main()
