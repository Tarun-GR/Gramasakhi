"""Stage 6C-3 — citizen assistance continuity and resume tests."""

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
from app.services.assistance_continuity import (
    ASSISTANCE_META_MARKER,
    build_conversation_assistance_state,
    build_message_assistance_meta,
    embed_assistance_meta_in_sources,
    extract_assistance_meta_from_sources,
    strip_internal_sources_for_api,
)
from app.services.eligibility_questioning import (
    SESSION_MARKER,
    EligibilitySession,
    embed_session_in_sources,
    load_session_from_messages,
)


class TestAssistanceContinuityHelpers(unittest.TestCase):
    def test_embed_extract_roundtrip(self):
        meta = build_message_assistance_meta(
            detected_scheme="PM-KISAN",
            eligibility_status="ELIGIBLE",
            scheme_guidance={"documents": ["Aadhaar"], "extraction_status": "ok"},
            action_plan={"status": "ELIGIBLE", "steps": ["Apply online"]},
        )
        sources = embed_assistance_meta_in_sources([{"source": "https://gov.in"}], meta)
        self.assertEqual(len(sources), 2)
        restored = extract_assistance_meta_from_sources(sources)
        self.assertEqual(restored["detected_scheme"], "PM-KISAN")
        self.assertEqual(restored["action_plan"]["status"], "ELIGIBLE")

    def test_strip_internal_sources(self):
        session = EligibilitySession(conversation_id="c1", active_scheme="PM-KISAN")
        sources = embed_session_in_sources([], session)
        meta = build_message_assistance_meta(detected_scheme="PM-KISAN")
        sources = embed_assistance_meta_in_sources(sources, meta)
        public = strip_internal_sources_for_api(sources)
        self.assertEqual(public, [])
        self.assertEqual(len(sources), 2)

    def test_build_conversation_state_from_session(self):
        session = EligibilitySession(
            conversation_id="conv-a",
            active_scheme="PM-KISAN",
            required_information=["age"],
            known_information={"age": 40},
            missing_information=["income"],
            current_question_type="income",
            session_active=True,
            completed=False,
        )
        msg = type(
            "M",
            (),
            {
                "role": "assistant",
                "sources_json": json.dumps(embed_session_in_sources([], session)),
            },
        )()
        state = build_conversation_assistance_state(
            conversation_id="conv-a",
            active_scheme_context="PM-KISAN",
            messages=[msg],
        )
        self.assertTrue(state["eligibility_session_active"])
        self.assertEqual(state["eligibility_question"], "income")
        self.assertEqual(state["known_information"]["age"], 40)

    def test_session_not_restored_for_wrong_conversation(self):
        session = EligibilitySession(conversation_id="conv-a", active_scheme="PM-KISAN")
        msg = type(
            "M",
            (),
            {
                "role": "assistant",
                "sources_json": json.dumps(embed_session_in_sources([], session)),
            },
        )()
        state = build_conversation_assistance_state(
            conversation_id="conv-b",
            active_scheme_context=None,
            messages=[msg],
        )
        self.assertNotIn("eligibility_session_active", state or {})


class TestAssistanceContinuityAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db_path = "test_assistance_continuity.db"
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
        self.account = CitizenAccount(
            phone_number="9333333333",
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
            "answer": "PM-KISAN provides income support to farmers.",
            "confidence": "high",
            "reason": "ok",
            "sources": [
                {
                    "scheme_name": "PM-KISAN",
                    "source": "https://www.myscheme.gov.in/schemes/pmkisan",
                }
            ],
            "validated": True,
            "llm_invoked": True,
            "knowledge_source": "indexed",
            "official_sources": [],
        }

    def test_history_includes_assistance_meta_after_chat(self):
        guidance = {
            "scheme_name": "PM-KISAN",
            "documents": ["Aadhaar", "Bank passbook"],
            "application_steps": ["Register on portal"],
            "application_url": "https://www.myscheme.gov.in/schemes/pmkisan",
            "extraction_status": "ok",
        }
        plan = {
            "status": "NONE",
            "scheme_name": "PM-KISAN",
            "steps": ["Gather documents", "Apply on portal"],
            "extraction_status": "ok",
        }

        def _apply_guidance(**kwargs):
            return {"applied": True, "answer": "Documents: Aadhaar", "guidance": guidance}

        def _apply_plan(**kwargs):
            return {
                "applied": True,
                "answer": "Next: apply on portal",
                "action_plan": plan,
                "official_sources": [],
            }

        with patch.object(rag_service, "answer_with_evidence_gate", side_effect=self._fake_rag):
            with patch(
                "app.services.scheme_guidance.apply_scheme_guidance",
                side_effect=_apply_guidance,
            ):
                with patch(
                    "app.services.action_plan.apply_action_plan",
                    side_effect=_apply_plan,
                ):
                    post = self.client.post(
                        "/api/chat",
                        json={"message": "What documents do I need for PM-KISAN?"},
                        headers=self._auth(),
                    )
        self.assertEqual(post.status_code, 200, post.text)
        cid = post.json()["conversation_id"]
        self.assertIn("scheme_guidance", post.json())

        hist = self.client.get(f"/api/chat/conversations/{cid}", headers=self._auth())
        self.assertEqual(hist.status_code, 200)
        body = hist.json()
        assistant = next(m for m in body["messages"] if m["role"] == "assistant")
        self.assertIsNotNone(assistant.get("assistance_meta"))
        self.assertEqual(assistant["assistance_meta"]["detected_scheme"], "PM-KISAN")
        self.assertIn("scheme_guidance", assistant["assistance_meta"])
        self.assertEqual(
            assistant["assistance_meta"]["scheme_guidance"]["documents"],
            ["Aadhaar", "Bank passbook"],
        )
        self.assertTrue(body.get("assistance_state"))
        self.assertEqual(body["assistance_state"]["active_scheme_context"], "PM-KISAN")

        # Internal markers must not appear in public sources
        for item in assistant.get("sources") or []:
            self.assertNotEqual(item.get("_internal"), SESSION_MARKER)
            self.assertNotEqual(item.get("_internal"), ASSISTANCE_META_MARKER)

    def test_reload_does_not_invoke_rag(self):
        with patch.object(rag_service, "answer_with_evidence_gate", side_effect=self._fake_rag) as rag_mock:
            post = self.client.post(
                "/api/chat",
                json={"message": "Tell me about PM-KISAN"},
                headers=self._auth(),
            )
            cid = post.json()["conversation_id"]
            rag_mock.reset_mock()
            hist = self.client.get(f"/api/chat/conversations/{cid}", headers=self._auth())
            self.assertEqual(hist.status_code, 200)
            rag_mock.assert_not_called()

    def test_eligibility_session_survives_history_reload(self):
        session = EligibilitySession(
            conversation_id="pending",
            active_scheme="Test Scheme",
            required_information=["age", "income"],
            known_information={"age": 35},
            missing_information=["income"],
            current_question_type="income",
            session_active=True,
            completed=False,
        )

        db = self.SessionLocal()
        conv = cs.create_conversation(db, self.account)
        session.conversation_id = str(conv.id)
        sources = embed_session_in_sources([], session)
        meta = build_message_assistance_meta(
            detected_scheme="Test Scheme",
            eligibility_session_active=True,
            eligibility_question="income",
            known_information={"age": 35},
            missing_information=["income"],
        )
        sources = embed_assistance_meta_in_sources(sources, meta)
        cs.store_message(
            db,
            str(conv.id),
            role="assistant",
            content="What is your income?",
            sources=sources,
        )
        conv.active_scheme_context = "Test Scheme"
        db.commit()
        cid = str(conv.id)
        db.close()

        hist = self.client.get(f"/api/chat/conversations/{cid}", headers=self._auth())
        state = hist.json().get("assistance_state") or {}
        self.assertTrue(state.get("eligibility_session_active"))
        self.assertEqual(state.get("eligibility_question"), "income")
        self.assertEqual(state.get("known_information", {}).get("age"), 35)

        loaded = load_session_from_messages(
            self.SessionLocal().query(Message).filter(Message.conversation_id == cid).all()
        )
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.current_question_type, "income")
        self.assertEqual(loaded.known_information.get("age"), 35)

    def test_conversation_isolation(self):
        db = self.SessionLocal()
        conv_a = cs.create_conversation(db, self.account)
        conv_b = cs.create_conversation(db, self.account)
        session_a = EligibilitySession(
            conversation_id=str(conv_a.id),
            active_scheme="PM-KISAN",
            session_active=True,
            current_question_type="age",
        )
        cs.store_message(
            db,
            str(conv_a.id),
            role="assistant",
            content="Q?",
            sources=embed_session_in_sources([], session_a),
        )
        conv_a.active_scheme_context = "PM-KISAN"
        db.commit()
        id_a, id_b = str(conv_a.id), str(conv_b.id)
        db.close()

        hist_b = self.client.get(f"/api/chat/conversations/{id_b}", headers=self._auth()).json()
        state_b = hist_b.get("assistance_state")
        self.assertTrue(state_b is None or not state_b.get("eligibility_session_active"))

        hist_a = self.client.get(f"/api/chat/conversations/{id_a}", headers=self._auth()).json()
        self.assertEqual(hist_a["assistance_state"]["active_scheme_context"], "PM-KISAN")

    def test_action_plan_meta_restores_on_reload(self):
        plan = {
            "status": "ELIGIBLE",
            "scheme_name": "PM-KISAN",
            "steps": ["Gather documents", "Apply on portal"],
            "extraction_status": "ok",
        }

        def _fake_rag(*args, **kwargs):
            return {
                "answer": "You appear eligible.",
                "confidence": "high",
                "reason": "ok",
                "sources": [{"scheme_name": "PM-KISAN", "source": "https://gov.in/pmkisan"}],
                "validated": True,
                "llm_invoked": True,
                "knowledge_source": "indexed",
                "official_sources": [],
            }

        def _apply_plan(**kwargs):
            return {
                "applied": True,
                "answer": "Next: apply on portal",
                "action_plan": plan,
                "official_sources": [],
            }

        with patch.object(rag_service, "answer_with_evidence_gate", side_effect=_fake_rag):
            with patch("app.services.action_plan.apply_action_plan", side_effect=_apply_plan):
                post = self.client.post(
                    "/api/chat",
                    json={"message": "What should I do next for PM-KISAN?"},
                    headers=self._auth(),
                )
        self.assertEqual(post.status_code, 200, post.text)
        self.assertIn("action_plan", post.json())
        cid = post.json()["conversation_id"]
        hist = self.client.get(f"/api/chat/conversations/{cid}", headers=self._auth()).json()
        assistant = next(m for m in hist["messages"] if m["role"] == "assistant")
        self.assertIn("action_plan", assistant["assistance_meta"])
        self.assertEqual(assistant["assistance_meta"]["action_plan"]["status"], "ELIGIBLE")


if __name__ == "__main__":
    unittest.main()
