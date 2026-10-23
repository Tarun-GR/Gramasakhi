"""Chat pipeline budgets, cloud retrieval path, and HTTP errors."""

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
from app.models.citizen_account import CitizenAccount
from app.services import rag as rag_service
from app.services.chat_pipeline import (
    ChatPipelineTimeout,
    chat_pipeline_budget_seconds,
    ensure_budget,
    live_gov_effective_overall_seconds,
    set_chat_request_context,
    clear_chat_request_context,
)
from app.services.index_builder import HybridIndexesNotReadyError, hybrid_disk_indexes_present
from app.services.runtime_profile import live_gov_fallback_allowed


class TestChatPipelineCloud(unittest.TestCase):
    def test_cloud_budget_defaults_under_render_proxy(self):
        with patch.object(settings, "RUNTIME_PROFILE", "cloud"):
            with patch.object(settings, "CHAT_PIPELINE_BUDGET_SECONDS", 0.0):
                self.assertLessEqual(chat_pipeline_budget_seconds(), 90.0)

    def test_live_gov_cap_on_cloud(self):
        with patch.object(settings, "RUNTIME_PROFILE", "cloud"):
            with patch.object(settings, "LIVE_GOV_OVERALL_TIMEOUT_SECONDS", 240.0):
                with patch.object(settings, "CLOUD_LIVE_GOV_OVERALL_CAP_SECONDS", 45.0):
                    self.assertLessEqual(live_gov_effective_overall_seconds(), 45.0)

    def test_budget_enforcement_raises(self):
        set_chat_request_context(request_id="t1", deadline_mono=time.monotonic() + 0.01)
        try:
            time.sleep(0.02)
            with self.assertRaises(ChatPipelineTimeout):
                ensure_budget(1.0)
        finally:
            clear_chat_request_context()

    def test_live_gov_disabled_on_cloud_without_disk_indexes(self):
        with patch.object(settings, "RUNTIME_PROFILE", "cloud"):
            with patch.object(settings, "LIVE_GOV_FALLBACK_ENABLED", True):
                with patch.object(settings, "CLOUD_LIVE_GOV_WHEN_INDEXES_MISSING", False):
                    self.assertFalse(live_gov_fallback_allowed(hybrid_disk_indexes_ready=False))
                    self.assertTrue(live_gov_fallback_allowed(hybrid_disk_indexes_ready=True))

    def test_hybrid_disk_indexes_present_false_on_empty_dir(self):
        from pathlib import Path
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(hybrid_disk_indexes_present(Path(tmp)))


class TestChatHttpErrors(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db_path = "test_chat_pipeline_cloud.db"
        if os.path.exists(cls.db_path):
            os.remove(cls.db_path)
        cls.engine = create_engine(
            f"sqlite:///{cls.db_path}", connect_args={"check_same_thread": False}
        )
        Base.metadata.create_all(bind=cls.engine)
        cls.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=cls.engine)

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
            os.remove(cls.db_path)

    def setUp(self):
        db = self.SessionLocal()
        db.query(CitizenAccount).delete()
        acct = CitizenAccount(
            phone_number="9888777666",
            password_hash=security.get_password_hash("x"),
            display_name="Chat",
        )
        db.add(acct)
        db.commit()
        db.refresh(acct)
        self.token = security.create_access_token(subject=str(acct.id), token_use="citizen")
        db.close()

    def test_chat_missing_auth_401(self):
        res = self.client.post("/api/chat", json={"message": "What is PM-KISAN?"})
        self.assertEqual(res.status_code, 401)

    def test_chat_success_mocked_rag(self):
        with patch.object(
            rag_service,
            "answer_with_evidence_gate",
            return_value={
                "answer": "Demo answer",
                "confidence": "high",
                "sources": [],
                "validated": True,
                "llm_invoked": True,
                "knowledge_source": "indexed",
            },
        ):
            res = self.client.post(
                "/api/chat",
                json={"message": "What is PM-KISAN?"},
                headers={"Authorization": f"Bearer {self.token}"},
            )
        self.assertEqual(res.status_code, 200, res.text)

    def test_hybrid_not_ready_is_distinct_error(self):
        err = HybridIndexesNotReadyError("hybrid indexes missing on disk (cloud)")
        self.assertIsInstance(err, RuntimeError)


if __name__ == "__main__":
    unittest.main()
