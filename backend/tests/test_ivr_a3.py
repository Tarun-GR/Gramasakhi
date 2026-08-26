"""IVR-A3 — transcription into existing GramSakhi chat/RAG pipeline."""

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
from app.models import citizen_account, user, rag, audit, conversation  # noqa: F401
from app.models.conversation import Conversation
from app.models.citizen_account import CitizenAccount
from app.services.ivr.chat_adapter import (
    IvrChatFailure,
    map_chat_evidence_status,
    process_ivr_chat,
    resolve_chat_language,
    validate_chat_service_result,
)
from app.services.ivr.language_session import (
    get_conversation_id,
    get_session_store,
    reset_session_store,
    set_language,
)
from app.services.ivr.call_state import IvrCallState, set_state
from app.services.ivr import ivr_auth

CALL_SID_A = "CA_A3_AAAAAAAAAAAAAAAAAAAAAAAAAAAA"
CALL_SID_B = "CA_A3_BBBBBBBBBBBBBBBBBBBBBBBBBBBB"
TRANSCRIPT = "What is PM-KISAN eligibility?"
SECRET = "JWT_SECRET_SHOULD_NOT_APPEAR"
OVERSIZED = "x" * 8001


def _chat_ok(**overrides):
    base = {
        "conversation_id": "conv-ivr-1",
        "created_new_conversation": True,
        "answer": "PM-KISAN helps farmers.",
        "validated": True,
        "llm_invoked": True,
        "sources": [{"url": "https://www.myscheme.gov.in/schemes/pm-kisan", "scheme_name": "PM-KISAN"}],
        "official_sources": [],
        "response_language": "EN",
        "confidence": "high",
    }
    base.update(overrides)
    return base


class TestIvrA3(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db_path = "test_ivr_a3.db"
        if os.path.exists(cls.db_path):
            try:
                os.remove(cls.db_path)
            except OSError:
                pass
        cls.engine = create_engine(
            f"sqlite:///{cls.db_path}", connect_args={"check_same_thread": False}
        )
        Base.metadata.drop_all(bind=cls.engine)
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
            try:
                os.remove(cls.db_path)
            except OSError:
                pass

    def setUp(self):
        reset_session_store()
        db = self.SessionLocal()
        db.query(Conversation).delete()
        db.query(CitizenAccount).delete()
        self.ivr_account = CitizenAccount(
            phone_number="+910000000099",
            password_hash=security.get_password_hash("ivr-bridge"),
            display_name="IVR Bridge",
        )
        db.add(self.ivr_account)
        db.commit()
        db.refresh(self.ivr_account)
        self.ivr_account_id = str(self.ivr_account.id)
        db.close()
        self._patcher_account = patch.object(
            settings, "IVR_CITIZEN_ACCOUNT_ID", self.ivr_account_id
        )
        self._patcher_account.start()

    def tearDown(self):
        self._patcher_account.stop()

    def _seed(self, sid: str, lang: str, *, transcription: str | None = TRANSCRIPT) -> None:
        set_language(sid, lang)
        set_state(sid, IvrCallState.TRANSCRIBING)
        if transcription is not None:
            from app.services.ivr.language_session import get_session_store

            get_session_store().set_transcription(sid, transcription=transcription)

    def _post(self, **payload):
        return self.client.post("/api/ivr/chat", json=payload)

    def test_missing_call_sid_rejected(self):
        resp = self._post(transcription=TRANSCRIPT)
        self.assertEqual(resp.status_code, 422)

    def test_unknown_call_sid_rejected(self):
        resp = self._post(CallSid=CALL_SID_A, transcription=TRANSCRIPT)
        self.assertEqual(resp.status_code, 400)

    def test_missing_language_rejected(self):
        from app.services.ivr.language_session import get_session_store

        get_session_store().get_session(CALL_SID_A)
        resp = self._post(CallSid=CALL_SID_A, transcription=TRANSCRIPT)
        self.assertEqual(resp.status_code, 400)

    def test_missing_transcription_rejected(self):
        self._seed(CALL_SID_A, "en", transcription=None)
        resp = self._post(CallSid=CALL_SID_A)
        self.assertEqual(resp.status_code, 400)

    def test_empty_transcription_rejected(self):
        self._seed(CALL_SID_A, "en", transcription="   ")
        resp = self._post(CallSid=CALL_SID_A, transcription="   ")
        self.assertEqual(resp.status_code, 400)

    def test_oversized_transcription_rejected(self):
        self._seed(CALL_SID_A, "en")
        resp = self._post(CallSid=CALL_SID_A, transcription=OVERSIZED)
        self.assertIn(resp.status_code, (400, 422))

    def test_kn_maps_to_kn(self):
        self._seed(CALL_SID_A, "kn")
        self.assertEqual(resolve_chat_language(CALL_SID_A), "KN")

    def test_hi_maps_to_hi(self):
        self._seed(CALL_SID_A, "hi")
        self.assertEqual(resolve_chat_language(CALL_SID_A), "HI")

    def test_en_maps_to_en(self):
        self._seed(CALL_SID_A, "en")
        self.assertEqual(resolve_chat_language(CALL_SID_A), "EN")

    def test_caller_cannot_override_language(self):
        self._seed(CALL_SID_A, "kn")
        seen = {}

        def fake_chat(db, citizen, **kwargs):
            seen["language"] = kwargs.get("language")
            return _chat_ok(conversation_id="c1", response_language="KN")

        with patch("app.services.ivr.chat_adapter.conversation_service.handle_citizen_chat", side_effect=fake_chat):
            resp = self._post(
                CallSid=CALL_SID_A,
                transcription=TRANSCRIPT,
                language="EN",
                lang="en",
            )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(seen["language"], "KN")

    def test_call_sid_creates_one_conversation(self):
        self._seed(CALL_SID_A, "en")
        with patch(
            "app.services.ivr.chat_adapter.conversation_service.handle_citizen_chat",
            return_value=_chat_ok(conversation_id="conv-new", created_new_conversation=True),
        ):
            resp = self._post(CallSid=CALL_SID_A, transcription=TRANSCRIPT)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(get_conversation_id(CALL_SID_A), "conv-new")

    def test_repeated_call_sid_reuses_conversation(self):
        self._seed(CALL_SID_A, "en")
        calls = []

        def fake_chat(db, citizen, **kwargs):
            calls.append(kwargs.get("conversation_id"))
            return _chat_ok(
                conversation_id=kwargs.get("conversation_id") or "conv-reuse",
                created_new_conversation=not kwargs.get("conversation_id"),
            )

        with patch(
            "app.services.ivr.chat_adapter.conversation_service.handle_citizen_chat",
            side_effect=fake_chat,
        ):
            self._post(CallSid=CALL_SID_A, transcription=TRANSCRIPT)
            set_state(CALL_SID_A, IvrCallState.TRANSCRIBING)
            get_session_store().set_transcription(CALL_SID_A, transcription="Follow up question")
            self._post(CallSid=CALL_SID_A, transcription="Follow up question")
        self.assertEqual(calls[0], None)
        self.assertEqual(calls[1], "conv-reuse")

    def test_different_call_sid_isolated_conversations(self):
        self._seed(CALL_SID_A, "en")
        self._seed(CALL_SID_B, "hi")
        with patch(
            "app.services.ivr.chat_adapter.conversation_service.handle_citizen_chat",
            side_effect=lambda db, citizen, **kw: _chat_ok(
                conversation_id=f"conv-{kw.get('language')}",
            ),
        ):
            self._post(CallSid=CALL_SID_A, transcription=TRANSCRIPT)
            self._post(CallSid=CALL_SID_B, transcription=TRANSCRIPT)
        self.assertEqual(get_conversation_id(CALL_SID_A), "conv-EN")
        self.assertEqual(get_conversation_id(CALL_SID_B), "conv-HI")

    def test_caller_cannot_supply_arbitrary_conversation_id(self):
        self._seed(CALL_SID_A, "en")
        seen = {}

        def fake_chat(db, citizen, **kwargs):
            seen["conversation_id"] = kwargs.get("conversation_id")
            return _chat_ok(conversation_id="server-conv")

        with patch(
            "app.services.ivr.chat_adapter.conversation_service.handle_citizen_chat",
            side_effect=fake_chat,
        ):
            self._post(
                CallSid=CALL_SID_A,
                transcription=TRANSCRIPT,
                conversation_id="evil-conv",
            )
        self.assertIsNone(seen["conversation_id"])

    def test_call_sid_a_cannot_access_b_conversation(self):
        self._seed(CALL_SID_A, "en")
        self._seed(CALL_SID_B, "hi")
        from app.services.ivr.language_session import get_session_store

        get_session_store().set_conversation_id(CALL_SID_B, "conv-b-only")
        seen = {}

        def fake_chat(db, citizen, **kwargs):
            seen["sid"] = kwargs.get("conversation_id")
            return _chat_ok(conversation_id="conv-a")

        with patch(
            "app.services.ivr.chat_adapter.conversation_service.handle_citizen_chat",
            side_effect=fake_chat,
        ):
            self._post(CallSid=CALL_SID_A, transcription=TRANSCRIPT)
        self.assertNotEqual(seen["sid"], "conv-b-only")

    def test_existing_chat_service_called(self):
        self._seed(CALL_SID_A, "en")
        with patch(
            "app.services.ivr.chat_adapter.conversation_service.handle_citizen_chat",
            return_value=_chat_ok(),
        ) as mocked:
            self._post(CallSid=CALL_SID_A, transcription=TRANSCRIPT)
        mocked.assert_called_once()

    def test_correct_query_sent(self):
        self._seed(CALL_SID_A, "en")
        seen = {}

        def fake_chat(db, citizen, **kwargs):
            seen["message"] = kwargs.get("message")
            return _chat_ok()

        with patch(
            "app.services.ivr.chat_adapter.conversation_service.handle_citizen_chat",
            side_effect=fake_chat,
        ):
            self._post(CallSid=CALL_SID_A, transcription=TRANSCRIPT)
        self.assertEqual(seen["message"], TRANSCRIPT)

    def test_correct_language_sent(self):
        self._seed(CALL_SID_A, "hi")
        seen = {}

        def fake_chat(db, citizen, **kwargs):
            seen["language"] = kwargs.get("language")
            seen["stt_language"] = kwargs.get("stt_language")
            return _chat_ok(response_language="HI")

        with patch(
            "app.services.ivr.chat_adapter.conversation_service.handle_citizen_chat",
            side_effect=fake_chat,
        ):
            self._post(CallSid=CALL_SID_A, transcription=TRANSCRIPT)
        self.assertEqual(seen["language"], "HI")
        self.assertEqual(seen["stt_language"], "HI")

    def test_chat_response_preserved(self):
        self._seed(CALL_SID_A, "en")
        with patch(
            "app.services.ivr.chat_adapter.conversation_service.handle_citizen_chat",
            return_value=_chat_ok(answer="Exact grounded answer."),
        ):
            resp = self._post(CallSid=CALL_SID_A, transcription=TRANSCRIPT)
        self.assertEqual(resp.json()["response_text"], "Exact grounded answer.")

    def test_malformed_response_rejected(self):
        self._seed(CALL_SID_A, "en")
        db = self.SessionLocal()
        with patch(
            "app.services.ivr.chat_adapter.conversation_service.handle_citizen_chat",
            return_value={"bad": True},
        ):
            outcome = process_ivr_chat(db, CALL_SID_A, transcription=TRANSCRIPT)
        db.close()
        self.assertEqual(outcome.failure, IvrChatFailure.MALFORMED_CHAT_RESPONSE)

    def test_timeout_handled(self):
        self._seed(CALL_SID_A, "en")
        from fastapi import HTTPException

        db = self.SessionLocal()
        with patch(
            "app.services.ivr.chat_adapter.conversation_service.handle_citizen_chat",
            side_effect=HTTPException(status_code=504, detail="timeout"),
        ):
            outcome = process_ivr_chat(db, CALL_SID_A, transcription=TRANSCRIPT)
        db.close()
        self.assertFalse(outcome.response.success)

    def test_4xx_handled(self):
        self._seed(CALL_SID_A, "en")
        from fastapi import HTTPException

        db = self.SessionLocal()
        with patch(
            "app.services.ivr.chat_adapter.conversation_service.handle_citizen_chat",
            side_effect=HTTPException(status_code=400, detail="bad"),
        ):
            outcome = process_ivr_chat(db, CALL_SID_A, transcription=TRANSCRIPT)
        db.close()
        self.assertEqual(outcome.failure, IvrChatFailure.CHAT_CLIENT_ERROR)

    def test_5xx_handled(self):
        self._seed(CALL_SID_A, "en")
        db = self.SessionLocal()
        with patch(
            "app.services.ivr.chat_adapter.conversation_service.handle_citizen_chat",
            side_effect=RuntimeError("boom"),
        ):
            outcome = process_ivr_chat(db, CALL_SID_A, transcription=TRANSCRIPT)
        db.close()
        self.assertEqual(outcome.failure, IvrChatFailure.CHAT_SERVER_ERROR)

    def test_supported_preserved(self):
        status = map_chat_evidence_status({"validated": True, "llm_invoked": True, "sources": []})
        self.assertEqual(status, "SUPPORTED")

    def test_partial_preserved(self):
        status = map_chat_evidence_status(
            {"validated": False, "llm_invoked": False, "sources": [{"url": "https://x.gov.in"}]}
        )
        self.assertEqual(status, "PARTIAL")

    def test_unsupported_preserved(self):
        status = map_chat_evidence_status(
            {"validated": False, "live_status": "FAILED", "sources": []}
        )
        self.assertEqual(status, "UNSUPPORTED")

    def test_sources_preserved(self):
        self._seed(CALL_SID_A, "en")
        src = [{"url": "https://www.myscheme.gov.in/schemes/pm-kisan", "scheme_name": "PM-KISAN"}]
        with patch(
            "app.services.ivr.chat_adapter.conversation_service.handle_citizen_chat",
            return_value=_chat_ok(sources=src),
        ):
            resp = self._post(CallSid=CALL_SID_A, transcription=TRANSCRIPT)
        self.assertEqual(len(resp.json()["sources"]), 1)

    def test_no_sources_fabricated(self):
        self._seed(CALL_SID_A, "en")
        with patch(
            "app.services.ivr.chat_adapter.conversation_service.handle_citizen_chat",
            return_value=_chat_ok(sources=[]),
        ):
            resp = self._post(CallSid=CALL_SID_A, transcription=TRANSCRIPT)
        self.assertEqual(resp.json()["sources"], [])

    def test_transcript_not_logged(self):
        self._seed(CALL_SID_A, "en")
        with patch(
            "app.services.ivr.chat_adapter.conversation_service.handle_citizen_chat",
            return_value=_chat_ok(),
        ):
            with self.assertLogs("gramsakhi.ivr.chat", level="INFO") as captured:
                self._post(CallSid=CALL_SID_A, transcription="SECRET QUERY TEXT")
        joined = " ".join(captured.output)
        self.assertNotIn("SECRET QUERY TEXT", joined)

    def test_credentials_not_exposed(self):
        self._seed(CALL_SID_A, "en")
        with patch.object(settings, "EXOTEL_API_TOKEN", SECRET):
            with patch(
                "app.services.ivr.chat_adapter.conversation_service.handle_citizen_chat",
                return_value=_chat_ok(),
            ):
                resp = self._post(CallSid=CALL_SID_A, transcription=TRANSCRIPT)
        self.assertNotIn(SECRET, resp.text)

    def test_jwt_not_exposed(self):
        self._seed(CALL_SID_A, "en")
        token = security.create_access_token(subject=self.ivr_account_id)
        with patch(
            "app.services.ivr.chat_adapter.conversation_service.handle_citizen_chat",
            return_value=_chat_ok(),
        ):
            resp = self._post(CallSid=CALL_SID_A, transcription=TRANSCRIPT)
        self.assertNotIn(token, resp.text)

    def test_arbitrary_account_id_rejected(self):
        self._seed(CALL_SID_A, "en")
        with patch(
            "app.services.ivr.chat_adapter.conversation_service.handle_citizen_chat",
            return_value=_chat_ok(),
        ) as mocked:
            self._post(
                CallSid=CALL_SID_A,
                transcription=TRANSCRIPT,
                account_id="00000000-0000-0000-0000-000000000001",
                citizen_id="00000000-0000-0000-0000-000000000002",
            )
        args, _ = mocked.call_args
        self.assertEqual(str(args[1].id), self.ivr_account_id)

    def test_arbitrary_conversation_id_ignored(self):
        self._seed(CALL_SID_A, "en")
        with patch(
            "app.services.ivr.chat_adapter.conversation_service.handle_citizen_chat",
            return_value=_chat_ok(conversation_id="real-id"),
        ) as mocked:
            self._post(
                CallSid=CALL_SID_A,
                transcription=TRANSCRIPT,
                conversation_id="attacker-id",
            )
        self.assertIsNone(mocked.call_args.kwargs.get("conversation_id"))

    def test_cross_call_sid_isolation(self):
        self._seed(CALL_SID_A, "kn")
        self._seed(CALL_SID_B, "en")
        langs = []

        def fake_chat(db, citizen, **kwargs):
            langs.append(kwargs.get("language"))
            return _chat_ok(conversation_id=f"id-{kwargs.get('language')}")

        with patch(
            "app.services.ivr.chat_adapter.conversation_service.handle_citizen_chat",
            side_effect=fake_chat,
        ):
            self._post(CallSid=CALL_SID_A, transcription=TRANSCRIPT)
            self._post(CallSid=CALL_SID_B, transcription=TRANSCRIPT)
        self.assertEqual(langs, ["KN", "EN"])

    def test_unauthorized_when_no_ivr_citizen(self):
        self._seed(CALL_SID_A, "en")
        self._patcher_account.stop()
        with patch.object(settings, "IVR_CITIZEN_ACCOUNT_ID", ""):
            with patch.object(settings, "IVR_SYSTEM_ACCOUNT_PHONE", ""):
                resp = self._post(CallSid=CALL_SID_A, transcription=TRANSCRIPT)
        self._patcher_account.start()
        self.assertEqual(resp.status_code, 503)

    def test_validate_chat_service_result_unit(self):
        ok, err = validate_chat_service_result(_chat_ok())
        self.assertTrue(ok)
        self.assertIsNone(err)
        ok, err = validate_chat_service_result({})
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
