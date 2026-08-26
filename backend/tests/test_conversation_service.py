"""Phase 6 — conversation service, ownership, persistence, RAG wiring."""

from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock, patch

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core import security
from app.core.config import settings
from app.database.session import Base
from app.models import citizen_account, user, rag, audit, conversation  # noqa: F401
from app.models.conversation import Conversation, Message
from app.models.citizen_account import CitizenAccount
from app.services import conversation_service as cs
from app.services import rag as rag_service


class TestConversationService(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db_path = "test_conversation_phase6.db"
        if os.path.exists(cls.db_path):
            try:
                os.remove(cls.db_path)
            except Exception:
                pass
        cls.engine = create_engine(f"sqlite:///{cls.db_path}")
        Base.metadata.drop_all(bind=cls.engine)
        Base.metadata.create_all(bind=cls.engine)
        cls.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=cls.engine)
        settings.QUERY_REWRITE_USE_OLLAMA = False
        settings.CONVERSATION_HISTORY_LIMIT = 6

    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()
        if os.path.exists(cls.db_path):
            try:
                os.remove(cls.db_path)
            except Exception:
                pass

    def setUp(self):
        self.db = self.SessionLocal()
        self.db.query(Message).delete()
        self.db.query(Conversation).delete()
        self.db.query(CitizenAccount).delete()
        self.db.commit()
        self.citizen_a = CitizenAccount(
            phone_number="9000000001",
            password_hash=security.get_password_hash("password123"),
            display_name="Citizen A",
        )
        self.citizen_b = CitizenAccount(
            phone_number="9000000002",
            password_hash=security.get_password_hash("password123"),
            display_name="Citizen B",
        )
        self.db.add_all([self.citizen_a, self.citizen_b])
        self.db.commit()
        self.db.refresh(self.citizen_a)
        self.db.refresh(self.citizen_b)

    def tearDown(self):
        self.db.close()

    def _fake_rag(self, db, query, **kwargs):
        return {
            "answer": f"Grounded answer for: {query}",
            "confidence": "high",
            "reason": "ok",
            "sources": [{"scheme_name": "TEST", "page": 1, "source": "gov"}],
            "validated": True,
            "llm_invoked": True,
        }

    def test_create_conversation_and_store_user_message(self):
        with patch.object(rag_service, "answer_with_evidence_gate", side_effect=self._fake_rag):
            out = cs.handle_citizen_chat(
                self.db, self.citizen_a, message="Tell me about PMAY-G."
            )
        self.assertTrue(out["created_new_conversation"])
        self.assertTrue(out["conversation_id"])
        msgs = cs.load_recent_messages(self.db, out["conversation_id"])
        self.assertEqual(len(msgs), 2)
        self.assertEqual(msgs[0].role, "user")
        self.assertEqual(msgs[0].content, "Tell me about PMAY-G.")
        self.assertEqual(msgs[1].role, "assistant")

    def test_load_conversation_and_recent_messages(self):
        with patch.object(rag_service, "answer_with_evidence_gate", side_effect=self._fake_rag):
            first = cs.handle_citizen_chat(
                self.db, self.citizen_a, message="Tell me about PMAY-G."
            )
            cs.handle_citizen_chat(
                self.db,
                self.citizen_a,
                message="Who is eligible?",
                conversation_id=first["conversation_id"],
            )
        msgs = cs.load_recent_messages(self.db, first["conversation_id"], limit=6)
        self.assertGreaterEqual(len(msgs), 4)
        user_texts = [m.content for m in msgs if m.role == "user"]
        self.assertIn("Who is eligible?", user_texts)
        # Stored user text is original, not rewritten
        self.assertNotIn("Who is eligible for PMAY-G?", user_texts)

    def test_followup_uses_rewritten_query_for_retrieval(self):
        seen = {}

        def capture(db, query, **kwargs):
            seen["query"] = query
            return self._fake_rag(db, query)

        with patch.object(rag_service, "answer_with_evidence_gate", side_effect=capture):
            first = cs.handle_citizen_chat(
                self.db, self.citizen_a, message="Tell me about PMAY-G."
            )
            out = cs.handle_citizen_chat(
                self.db,
                self.citizen_a,
                message="Who is eligible?",
                conversation_id=first["conversation_id"],
            )
        self.assertEqual(out["original_query"], "Who is eligible?")
        self.assertEqual(out["rewritten_query"], "Who is eligible for PMAY-G?")
        self.assertEqual(seen["query"], "Who is eligible for PMAY-G?")
        self.assertTrue(out["was_rewritten"])

    def test_assistant_response_stored(self):
        with patch.object(rag_service, "answer_with_evidence_gate", side_effect=self._fake_rag):
            out = cs.handle_citizen_chat(
                self.db, self.citizen_a, message="What is PM-KISAN?"
            )
        msgs = cs.load_recent_messages(self.db, out["conversation_id"])
        self.assertEqual(msgs[-1].role, "assistant")
        self.assertIn("Grounded answer", msgs[-1].content)

    def test_evidence_fail_still_prevents_ollama_flag(self):
        def fail_rag(db, query, **kwargs):
            return {
                "answer": "I don't have enough reliable information to answer that.",
                "confidence": "low",
                "reason": "low_coverage",
                "sources": [],
                "validated": False,
                "llm_invoked": False,
            }

        with patch.object(rag_service, "answer_with_evidence_gate", side_effect=fail_rag):
            out = cs.handle_citizen_chat(
                self.db, self.citizen_a, message="What penalties exist?"
            )
        self.assertFalse(out["llm_invoked"])
        self.assertFalse(out["validated"])
        msgs = cs.load_recent_messages(self.db, out["conversation_id"])
        self.assertEqual(msgs[-1].evidence_status, "UNSUPPORTED")

    def test_evidence_pass_invokes_llm_flag(self):
        with patch.object(rag_service, "answer_with_evidence_gate", side_effect=self._fake_rag):
            out = cs.handle_citizen_chat(
                self.db, self.citizen_a, message="Tell me about PM-KISAN."
            )
        self.assertTrue(out["llm_invoked"])
        self.assertTrue(out["validated"])

    def test_citizen_b_cannot_access_citizen_a_conversation(self):
        with patch.object(rag_service, "answer_with_evidence_gate", side_effect=self._fake_rag):
            a_out = cs.handle_citizen_chat(
                self.db, self.citizen_a, message="Tell me about PMAY-G."
            )
        with self.assertRaises(HTTPException) as ctx:
            cs.get_owned_conversation(
                self.db, a_out["conversation_id"], str(self.citizen_b.id)
            )
        self.assertEqual(ctx.exception.status_code, 404)

        with self.assertRaises(HTTPException) as ctx2:
            with patch.object(rag_service, "answer_with_evidence_gate") as rag_mock:
                cs.handle_citizen_chat(
                    self.db,
                    self.citizen_b,
                    message="Who is eligible?",
                    conversation_id=a_out["conversation_id"],
                )
                rag_mock.assert_not_called()
        self.assertEqual(ctx2.exception.status_code, 404)

    def test_independent_conversations_identical_followup(self):
        seen = []

        def capture(db, query, **kwargs):
            seen.append(query)
            return self._fake_rag(db, query)

        with patch.object(rag_service, "answer_with_evidence_gate", side_effect=capture):
            a1 = cs.handle_citizen_chat(
                self.db, self.citizen_a, message="Tell me about PMAY-G."
            )
            a2 = cs.handle_citizen_chat(
                self.db,
                self.citizen_a,
                message="Who is eligible?",
                conversation_id=a1["conversation_id"],
            )
            b1 = cs.handle_citizen_chat(
                self.db, self.citizen_b, message="Tell me about PM-KISAN."
            )
            b2 = cs.handle_citizen_chat(
                self.db,
                self.citizen_b,
                message="Who is eligible?",
                conversation_id=b1["conversation_id"],
            )
        self.assertEqual(a2["rewritten_query"], "Who is eligible for PMAY-G?")
        self.assertEqual(b2["rewritten_query"], "Who is eligible for PM-KISAN?")
        self.assertIn("Who is eligible for PMAY-G?", seen)
        self.assertIn("Who is eligible for PM-KISAN?", seen)

    def test_conversation_survives_backend_restart(self):
        """History persists on disk — reopen engine/session like a restart."""
        with patch.object(rag_service, "answer_with_evidence_gate", side_effect=self._fake_rag):
            first = cs.handle_citizen_chat(
                self.db, self.citizen_a, message="Tell me about PMAY-G."
            )
        conv_id = first["conversation_id"]
        citizen_id = str(self.citizen_a.id)
        self.db.close()

        # Simulate process restart: new engine on same SQLite file
        engine2 = create_engine(f"sqlite:///{self.db_path}")
        Session2 = sessionmaker(autocommit=False, autoflush=False, bind=engine2)
        db2 = Session2()
        try:
            citizen = db2.query(CitizenAccount).filter(CitizenAccount.id == citizen_id).first()
            self.assertIsNotNone(citizen)
            prior = cs.load_recent_messages(db2, conv_id)
            self.assertGreaterEqual(len(prior), 2)

            seen = {}

            def capture(db, query, **kwargs):
                seen["query"] = query
                return self._fake_rag(db, query)

            with patch.object(rag_service, "answer_with_evidence_gate", side_effect=capture):
                out = cs.handle_citizen_chat(
                    db2,
                    citizen,
                    message="Who is eligible?",
                    conversation_id=conv_id,
                )
            self.assertEqual(out["rewritten_query"], "Who is eligible for PMAY-G?")
            self.assertEqual(seen["query"], "Who is eligible for PMAY-G?")
        finally:
            db2.close()
            engine2.dispose()
            # reopen class session for tearDown cleanup
            self.db = self.SessionLocal()

    def test_rewriter_failure_falls_back_and_still_retrieves(self):
        seen = {}

        def capture(db, query, **kwargs):
            seen["query"] = query
            return self._fake_rag(db, query)

        with patch(
            "app.services.conversation_service.rewrite_query",
            return_value={
                "original_query": "Who is eligible?",
                "rewritten_query": "Who is eligible?",
                "was_rewritten": False,
                "method": "fallback",
                "active_scheme": None,
            },
        ):
            with patch.object(rag_service, "answer_with_evidence_gate", side_effect=capture):
                first = cs.handle_citizen_chat(
                    self.db, self.citizen_a, message="Tell me about PMAY-G."
                )
                out = cs.handle_citizen_chat(
                    self.db,
                    self.citizen_a,
                    message="Who is eligible?",
                    conversation_id=first["conversation_id"],
                )
        self.assertEqual(out["rewritten_query"], "Who is eligible?")
        self.assertEqual(seen["query"], "Who is eligible?")


if __name__ == "__main__":
    unittest.main()
