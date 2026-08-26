"""ChatGPT-style conversation history APIs — list/search/rename/delete/ownership."""

from __future__ import annotations

import os
import time
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
from app.services import conversation_service as cs
from app.services import rag as rag_service
from app.services.query_rewriter import extract_scheme_mentions, rewrite_query


class TestChatHistory(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db_path = "test_chat_history.db"
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

    def _fake_rag(self, *args, **kwargs):
        q = args[1] if len(args) > 1 else kwargs.get("query", "")
        return {
            "answer": f"Grounded: {q}",
            "confidence": "high",
            "reason": "ok",
            "sources": [{"scheme_name": "TEST", "source": "gov"}],
            "validated": True,
            "llm_invoked": True,
            "knowledge_source": "indexed",
            "official_sources": [],
        }

    def test_create_list_sort_rename_delete_search(self):
        with patch.object(rag_service, "answer_with_evidence_gate", side_effect=self._fake_rag):
            r1 = self.client.post(
                "/api/chat",
                json={"message": "Tell me about PM-KISAN."},
                headers=self._auth(self.token_a),
            )
            self.assertEqual(r1.status_code, 200, r1.text)
            id1 = r1.json()["conversation_id"]
            time.sleep(0.02)
            r2 = self.client.post(
                "/api/chat",
                json={"message": "What documents for Gruha Lakshmi?"},
                headers=self._auth(self.token_a),
            )
            self.assertEqual(r2.status_code, 200, r2.text)
            id2 = r2.json()["conversation_id"]

        listed = self.client.get(
            "/api/chat/conversations?limit=20&offset=0",
            headers=self._auth(self.token_a),
        )
        self.assertEqual(listed.status_code, 200, listed.text)
        data = listed.json()
        self.assertEqual(data["total"], 2)
        # Latest-first: Gruha Lakshmi conversation first
        self.assertEqual(data["conversations"][0]["id"], id2)
        self.assertIn("Gruha Lakshmi", data["conversations"][0]["title"])
        self.assertIn("PM-KISAN", data["conversations"][1]["title"])

        # Open conversation — read only, sources persisted
        hist = self.client.get(
            f"/api/chat/conversations/{id1}",
            headers=self._auth(self.token_a),
        )
        self.assertEqual(hist.status_code, 200)
        msgs = hist.json()["messages"]
        self.assertGreaterEqual(len(msgs), 2)
        self.assertEqual(msgs[0]["content"], "Tell me about PM-KISAN.")
        assistant = next(m for m in msgs if m["role"] == "assistant")
        self.assertTrue(assistant.get("sources"))

        # Rename
        ren = self.client.patch(
            f"/api/chat/conversations/{id1}",
            json={"title": "My Farmer Questions"},
            headers=self._auth(self.token_a),
        )
        self.assertEqual(ren.status_code, 200)
        self.assertEqual(ren.json()["title"], "My Farmer Questions")

        # Search by title
        sr = self.client.get(
            "/api/chat/conversations/search?q=Farmer",
            headers=self._auth(self.token_a),
        )
        self.assertEqual(sr.status_code, 200)
        self.assertEqual(sr.json()["total"], 1)
        self.assertEqual(sr.json()["conversations"][0]["id"], id1)

        # Search by user message content
        sr2 = self.client.get(
            "/api/chat/conversations/search?q=Gruha",
            headers=self._auth(self.token_a),
        )
        self.assertEqual(sr2.status_code, 200)
        self.assertGreaterEqual(sr2.json()["total"], 1)

        # Soft delete
        dele = self.client.delete(
            f"/api/chat/conversations/{id2}",
            headers=self._auth(self.token_a),
        )
        self.assertEqual(dele.status_code, 204)
        listed2 = self.client.get(
            "/api/chat/conversations",
            headers=self._auth(self.token_a),
        )
        ids = [c["id"] for c in listed2.json()["conversations"]]
        self.assertNotIn(id2, ids)
        gone = self.client.get(
            f"/api/chat/conversations/{id2}",
            headers=self._auth(self.token_a),
        )
        self.assertEqual(gone.status_code, 404)

    def test_ownership_isolation(self):
        with patch.object(rag_service, "answer_with_evidence_gate", side_effect=self._fake_rag):
            r = self.client.post(
                "/api/chat",
                json={"message": "Tell me about PM-KISAN."},
                headers=self._auth(self.token_a),
            )
        cid = r.json()["conversation_id"]

        for path in (
            f"/api/chat/conversations/{cid}",
            f"/api/chat/{cid}",
        ):
            res = self.client.get(path, headers=self._auth(self.token_b))
            self.assertEqual(res.status_code, 404, path)

        res = self.client.patch(
            f"/api/chat/conversations/{cid}",
            json={"title": "Hacked"},
            headers=self._auth(self.token_b),
        )
        self.assertEqual(res.status_code, 404)

        res = self.client.delete(
            f"/api/chat/conversations/{cid}",
            headers=self._auth(self.token_b),
        )
        self.assertEqual(res.status_code, 404)

        # B's list must not include A's conversation
        listed = self.client.get(
            "/api/chat/conversations",
            headers=self._auth(self.token_b),
        )
        self.assertEqual(listed.json()["total"], 0)

    def test_new_chat_isolation_no_pmkisan_leak(self):
        with patch.object(rag_service, "answer_with_evidence_gate", side_effect=self._fake_rag):
            a = self.client.post(
                "/api/chat",
                json={"message": "Tell me about PM-KISAN."},
                headers=self._auth(self.token_a),
            )
            cid_a = a.json()["conversation_id"]
            self.client.post(
                "/api/chat",
                json={
                    "message": "Who is eligible?",
                    "conversation_id": cid_a,
                },
                headers=self._auth(self.token_a),
            )
            # New chat — omit conversation_id
            b = self.client.post(
                "/api/chat",
                json={"message": "shakti scheme details"},
                headers=self._auth(self.token_a),
            )
        cid_b = b.json()["conversation_id"]
        self.assertNotEqual(cid_a, cid_b)
        self.assertTrue(b.json().get("created_new_conversation"))

        hist_b = self.client.get(
            f"/api/chat/conversations/{cid_b}",
            headers=self._auth(self.token_a),
        )
        contents = " ".join(m["content"] for m in hist_b.json()["messages"])
        self.assertNotIn("PM-KISAN", contents)
        self.assertIn("shakti", contents.lower())

        # Rewriter must keep Shakti (not collapse to bare government scheme)
        mentions = extract_scheme_mentions("shakti scheme details")
        self.assertIn("Shakti", mentions)
        rw = rewrite_query("shakti scheme details", [], language="EN")
        self.assertIn("shakti", (rw["rewritten_query"] or "").lower())

    def test_title_from_original_not_rewrite(self):
        title = cs.generate_conversation_title("Who is eligible for PM-KISAN?")
        self.assertEqual(title, "PM-KISAN Eligibility")
        title2 = cs.generate_conversation_title("What documents are required for Gruha Lakshmi?")
        self.assertEqual(title2, "Gruha Lakshmi Documents")

    def test_pagination(self):
        with patch.object(rag_service, "answer_with_evidence_gate", side_effect=self._fake_rag):
            for i in range(5):
                self.client.post(
                    "/api/chat",
                    json={"message": f"Question number {i} about PM-KISAN"},
                    headers=self._auth(self.token_a),
                )
        page1 = self.client.get(
            "/api/chat/conversations?limit=2&offset=0",
            headers=self._auth(self.token_a),
        ).json()
        page2 = self.client.get(
            "/api/chat/conversations?limit=2&offset=2",
            headers=self._auth(self.token_a),
        ).json()
        self.assertEqual(len(page1["conversations"]), 2)
        self.assertTrue(page1["has_more"])
        self.assertEqual(page1["total"], 5)
        ids1 = {c["id"] for c in page1["conversations"]}
        ids2 = {c["id"] for c in page2["conversations"]}
        self.assertFalse(ids1 & ids2)

    def test_resume_continues_same_conversation(self):
        with patch.object(rag_service, "answer_with_evidence_gate", side_effect=self._fake_rag):
            first = self.client.post(
                "/api/chat",
                json={"message": "Tell me about PM-KISAN."},
                headers=self._auth(self.token_a),
            )
            cid = first.json()["conversation_id"]
            second = self.client.post(
                "/api/chat",
                json={
                    "message": "Who is eligible?",
                    "conversation_id": cid,
                },
                headers=self._auth(self.token_a),
            )
        self.assertEqual(second.json()["conversation_id"], cid)
        hist = self.client.get(
            f"/api/chat/conversations/{cid}",
            headers=self._auth(self.token_a),
        ).json()
        user_msgs = [m["content"] for m in hist["messages"] if m["role"] == "user"]
        self.assertEqual(user_msgs[0], "Tell me about PM-KISAN.")
        self.assertEqual(user_msgs[1], "Who is eligible?")


if __name__ == "__main__":
    unittest.main()
