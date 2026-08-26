"""IVR-A5 — multi-turn conversational loop."""

from __future__ import annotations

import io
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
from app.services.ivr.audio_token_store import get_audio_token_store, reset_audio_token_store
from app.services.ivr.call_state import IvrCallState, get_state, set_state
from app.services.ivr.constants import CONTINUE_MENU_PROMPT, SILENCE_FIRST_PROMPT
from app.services.ivr.language_session import get_session_store, reset_session_store, set_language
from app.services.ivr import ivr_auth
from app.services.voice import stt_service, tts_service
from app.services.voice.audio_utils import make_tone_wav

CALL_SID_A = "CA_A5_AAAAAAAAAAAAAAAAAAAAAAAAAAAA"
CALL_SID_B = "CA_A5_BBBBBBBBBBBBBBBBBBBBBBBBBBBB"
TRANSCRIPT = "What is PM-KISAN?"
FAKE_MP3 = b"\xff\xfb" + b"\x00" * 64


def _chat_ok(**overrides):
    base = {
        "conversation_id": "conv-a5-1",
        "created_new_conversation": True,
        "answer": "PM-KISAN helps farmers.",
        "validated": True,
        "llm_invoked": True,
        "sources": [],
        "response_language": "EN",
    }
    base.update(overrides)
    return base


class TestIvrA5(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db_path = "test_ivr_a5.db"
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
        reset_session_store()
        reset_audio_token_store()
        stt_service.set_test_transcribe_hook(None)
        tts_service.set_test_synthesize_hook(None)
        db = self.SessionLocal()
        db.query(Conversation).delete()
        db.query(CitizenAccount).delete()
        acct = CitizenAccount(
            phone_number="+910000000099",
            password_hash=security.get_password_hash("ivr"),
            display_name="IVR Bridge",
        )
        db.add(acct)
        db.commit()
        db.refresh(acct)
        self.account_id = str(acct.id)
        db.close()
        self._acct = patch.object(settings, "IVR_CITIZEN_ACCOUNT_ID", self.account_id)
        self._pub = patch.object(settings, "IVR_PUBLIC_BASE_URL", "https://api.gramsakhi.example.in")
        self._turns = patch.object(settings, "IVR_MAX_TURNS", 10)
        self._acct.start()
        self._pub.start()
        self._turns.start()

    def tearDown(self):
        self._turns.stop()
        self._pub.stop()
        self._acct.stop()

    def _ready(self, sid: str = CALL_SID_A, lang: str = "en") -> None:
        set_language(sid, lang)
        set_state(sid, IvrCallState.READY_FOR_INPUT)

    def _after_chat(self, sid: str = CALL_SID_A) -> None:
        set_language(sid, "en")
        store = get_session_store()
        store.set_transcription(sid, transcription=TRANSCRIPT)
        set_state(sid, IvrCallState.SYNTHESIZING)
        store.set_last_response_text(sid, "Answer text.")
        store.set_last_response_language(sid, "EN")

    def test_initial_state_language_selection(self):
        session = get_session_store().get_session(CALL_SID_A)
        self.assertEqual(session.state, IvrCallState.LANGUAGE_SELECTION.value)

    def test_language_sets_ready(self):
        self.client.get("/api/ivr/language", params={"CallSid": CALL_SID_A, "digits": "3"})
        self.assertEqual(get_state(CALL_SID_A), IvrCallState.READY_FOR_INPUT)

    def test_stt_transitions_transcribing(self):
        self._ready()
        stt_service.set_test_transcribe_hook(
            lambda *a, **k: {"success": True, "text": TRANSCRIPT, "request_id": "s1"}
        )
        transcribe_ivr_audio = __import__(
            "app.services.ivr.stt_adapter", fromlist=["transcribe_ivr_audio"]
        ).transcribe_ivr_audio
        transcribe_ivr_audio(CALL_SID_A, audio_bytes=make_tone_wav(0.2))
        self.assertEqual(get_state(CALL_SID_A), IvrCallState.TRANSCRIBING)

    def test_chat_transitions_synthesizing(self):
        self._ready()
        get_session_store().set_transcription(CALL_SID_A, transcription=TRANSCRIPT)
        set_state(CALL_SID_A, IvrCallState.TRANSCRIBING)
        with patch.object(
            __import__("app.services.conversation_service", fromlist=["conversation_service"]),
            "handle_citizen_chat",
            return_value=_chat_ok(),
        ):
            resp = self.client.post("/api/ivr/chat", json={"CallSid": CALL_SID_A})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(get_state(CALL_SID_A), IvrCallState.SYNTHESIZING)

    def test_tts_sets_playing(self):
        self._after_chat()
        tts_service.set_test_synthesize_hook(
            lambda *a, **k: {"success": True, "audio": FAKE_MP3, "mime_type": "audio/mpeg"}
        )
        resp = self.client.post("/api/ivr/tts", json={"CallSid": CALL_SID_A})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(get_state(CALL_SID_A), IvrCallState.PLAYING_RESPONSE)

    def test_continue_menu_from_playing(self):
        self._after_chat()
        set_state(CALL_SID_A, IvrCallState.PLAYING_RESPONSE)
        resp = self.client.get("/api/ivr/continue", params={"CallSid": CALL_SID_A})
        self.assertEqual(resp.status_code, 200)
        self.assertIn(CONTINUE_MENU_PROMPT, resp.json()["gather_prompt"]["text"])
        self.assertEqual(get_state(CALL_SID_A), IvrCallState.ASK_CONTINUE)

    def test_continue_one_returns_ready(self):
        set_state(CALL_SID_A, IvrCallState.ASK_CONTINUE)
        set_language(CALL_SID_A, "en")
        resp = self.client.post("/api/ivr/continue", json={"CallSid": CALL_SID_A, "digits": "1"})
        self.assertTrue(resp.json()["continue_loop"])
        self.assertEqual(get_state(CALL_SID_A), IvrCallState.READY_FOR_INPUT)

    def test_continue_two_ends(self):
        set_state(CALL_SID_A, IvrCallState.ASK_CONTINUE)
        set_language(CALL_SID_A, "en")
        resp = self.client.post("/api/ivr/continue", json={"CallSid": CALL_SID_A, "digits": "2"})
        self.assertTrue(resp.json()["end_call"])
        self.assertFalse(get_session_store().session_exists(CALL_SID_A))

    def test_invalid_continue_bounded(self):
        set_state(CALL_SID_A, IvrCallState.ASK_CONTINUE)
        set_language(CALL_SID_A, "en")
        for _ in range(3):
            self.client.post("/api/ivr/continue", json={"CallSid": CALL_SID_A, "digits": "9"})
        self.assertFalse(get_session_store().session_exists(CALL_SID_A))

    def test_invalid_transition_chat_without_stt(self):
        self._ready()
        resp = self.client.post("/api/ivr/chat", json={"CallSid": CALL_SID_A, "transcription": TRANSCRIPT})
        self.assertEqual(resp.status_code, 409)

    def test_same_conversation_reused(self):
        self._ready()
        get_session_store().set_transcription(CALL_SID_A, transcription=TRANSCRIPT)
        set_state(CALL_SID_A, IvrCallState.TRANSCRIBING)
        conv_ids = []

        def hook(*a, **k):
            conv_ids.append(k.get("conversation_id"))
            return _chat_ok(conversation_id="conv-same")

        with patch(
            "app.services.conversation_service.handle_citizen_chat",
            side_effect=hook,
        ):
            self.client.post("/api/ivr/chat", json={"CallSid": CALL_SID_A})
            set_state(CALL_SID_A, IvrCallState.TRANSCRIBING)
            get_session_store().set_transcription(CALL_SID_A, transcription="Second question?")
            self.client.post("/api/ivr/chat", json={"CallSid": CALL_SID_A})
        self.assertEqual(conv_ids[1], "conv-same")

    def test_different_callsid_isolated(self):
        self._ready(CALL_SID_A)
        self._ready(CALL_SID_B, "hi")
        self.assertNotEqual(get_session_store().get_language(CALL_SID_A), get_session_store().get_language(CALL_SID_B))

    def test_language_persists_across_turns(self):
        set_language(CALL_SID_A, "kn")
        set_state(CALL_SID_A, IvrCallState.ASK_CONTINUE)
        self.client.post("/api/ivr/continue", json={"CallSid": CALL_SID_A, "digits": "1"})
        self.assertEqual(get_session_store().get_language(CALL_SID_A), "kn")

    def test_turn_count_increments_once(self):
        self._ready()
        get_session_store().set_transcription(CALL_SID_A, transcription=TRANSCRIPT)
        set_state(CALL_SID_A, IvrCallState.TRANSCRIBING)
        with patch(
            "app.services.conversation_service.handle_citizen_chat",
            return_value=_chat_ok(),
        ):
            self.client.post("/api/ivr/chat", json={"CallSid": CALL_SID_A})
        self.assertEqual(get_session_store().get_session(CALL_SID_A).turn_count, 1)

    def test_turn_limit_enforced(self):
        with patch.object(settings, "IVR_MAX_TURNS", 1):
            self._ready()
            get_session_store().get_session(CALL_SID_A).turn_count = 1
            set_state(CALL_SID_A, IvrCallState.ASK_CONTINUE)
            resp = self.client.post("/api/ivr/continue", json={"CallSid": CALL_SID_A, "digits": "1"})
            self.assertTrue(resp.json()["end_call"])

    def test_silence_first_retry(self):
        self._ready()
        outcome = __import__(
            "app.services.ivr.stt_adapter", fromlist=["transcribe_ivr_audio"]
        ).transcribe_ivr_audio(CALL_SID_A)
        self.assertIn(SILENCE_FIRST_PROMPT, outcome.response.gather_prompt.text)

    def test_silence_second_ends(self):
        self._ready()
        mod = __import__("app.services.ivr.stt_adapter", fromlist=["transcribe_ivr_audio"])
        mod.transcribe_ivr_audio(CALL_SID_A)
        mod.transcribe_ivr_audio(CALL_SID_A)
        self.assertFalse(get_session_store().session_exists(CALL_SID_A))

    def test_stt_failure_bounded(self):
        self._ready()
        stt_service.set_test_transcribe_hook(lambda *a, **k: {"success": False, "error": "stt_failed"})
        mod = __import__("app.services.ivr.stt_adapter", fromlist=["transcribe_ivr_audio"])
        for _ in range(4):
            if not get_session_store().session_exists(CALL_SID_A):
                break
            set_state(CALL_SID_A, IvrCallState.READY_FOR_INPUT)
            mod.transcribe_ivr_audio(CALL_SID_A, audio_bytes=make_tone_wav(0.2))
        self.assertFalse(get_session_store().session_exists(CALL_SID_A))

    def test_chat_failure_handled(self):
        self._ready()
        get_session_store().set_transcription(CALL_SID_A, transcription=TRANSCRIPT)
        set_state(CALL_SID_A, IvrCallState.TRANSCRIBING)
        with patch(
            "app.services.conversation_service.handle_citizen_chat",
            side_effect=RuntimeError("chat boom"),
        ):
            resp = self.client.post("/api/ivr/chat", json={"CallSid": CALL_SID_A})
        self.assertEqual(resp.status_code, 503)
        self.assertEqual(get_state(CALL_SID_A), IvrCallState.READY_FOR_INPUT)

    def test_tts_failure_no_chat_repeat(self):
        self._after_chat()
        tts_service.set_test_synthesize_hook(lambda *a, **k: {"success": False, "error": "tts_failed"})
        with patch("app.services.conversation_service.handle_citizen_chat") as mocked:
            self.client.post("/api/ivr/tts", json={"CallSid": CALL_SID_A})
            mocked.assert_not_called()

    def test_new_token_invalidates_old(self):
        self._after_chat()
        tts_service.set_test_synthesize_hook(
            lambda *a, **k: {"success": True, "audio": FAKE_MP3, "mime_type": "audio/mpeg"}
        )
        r1 = self.client.post("/api/ivr/tts", json={"CallSid": CALL_SID_A})
        token1 = (r1.json().get("audio_url") or "").rsplit("/", 1)[-1]
        set_state(CALL_SID_A, IvrCallState.SYNTHESIZING)
        r2 = self.client.post("/api/ivr/tts", json={"CallSid": CALL_SID_A})
        token2 = (r2.json().get("audio_url") or "").rsplit("/", 1)[-1]
        self.assertNotEqual(token1, token2)
        self.assertIsNone(get_audio_token_store().get(token1))

    def test_concurrent_turn_rejected(self):
        self._ready()
        get_session_store().get_session(CALL_SID_A).turn_in_progress = True
        stt_service.set_test_transcribe_hook(
            lambda *a, **k: {"success": True, "text": TRANSCRIPT, "request_id": "x"}
        )
        outcome = __import__(
            "app.services.ivr.stt_adapter", fromlist=["transcribe_ivr_audio"]
        ).transcribe_ivr_audio(CALL_SID_A, audio_bytes=make_tone_wav(0.2))
        self.assertEqual(outcome.failure.value, "stt_client_error")

    def test_caller_cannot_override_conversation(self):
        self._ready()
        get_session_store().set_transcription(CALL_SID_A, transcription=TRANSCRIPT)
        set_state(CALL_SID_A, IvrCallState.TRANSCRIBING)
        seen = {}

        def hook(db, citizen, **kwargs):
            seen["conversation_id"] = kwargs.get("conversation_id")
            return _chat_ok(conversation_id="server-conv")

        with patch("app.services.conversation_service.handle_citizen_chat", side_effect=hook):
            self.client.post(
                "/api/ivr/chat",
                json={"CallSid": CALL_SID_A, "conversation_id": "evil-conv"},
            )
        self.assertNotEqual(seen.get("conversation_id"), "evil-conv")

    def test_transcript_not_logged(self):
        self._ready()
        stt_service.set_test_transcribe_hook(
            lambda *a, **k: {"success": True, "text": TRANSCRIPT, "request_id": "x"}
        )
        with self.assertLogs("gramsakhi.ivr.stt", level="INFO") as captured:
            __import__(
                "app.services.ivr.stt_adapter", fromlist=["transcribe_ivr_audio"]
            ).transcribe_ivr_audio(CALL_SID_A, audio_bytes=make_tone_wav(0.2))
        self.assertNotIn(TRANSCRIPT, " ".join(captured.output))

    def test_a1_still_importable(self):
        import tests.test_ivr_a1  # noqa: F401

    def test_a2_still_importable(self):
        import tests.test_ivr_a2  # noqa: F401

    def test_a3_still_importable(self):
        import tests.test_ivr_a3  # noqa: F401

    def test_a4_still_importable(self):
        import tests.test_ivr_a4  # noqa: F401


if __name__ == "__main__":
    unittest.main()
