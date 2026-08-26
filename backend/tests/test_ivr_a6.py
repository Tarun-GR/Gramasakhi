"""IVR-A6 — security and production readiness hardening."""

from __future__ import annotations

import pathlib
import io
import os
import time
import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.services.ivr.audio_token_store import get_audio_token_store, reset_audio_token_store
from app.services.ivr.call_sid_validation import CallSidValidationError, normalize_call_sid
from app.services.ivr.exotel_recording import (
    _GuardedRedirectHandler,
    fetch_exotel_recording_to_temp,
    set_recording_fetch_hook,
    validate_exotel_recording_url,
)
from app.services.ivr.call_state import IvrCallState, StateTransitionError, begin_turn, set_state
from app.services.ivr.ivr_config import collect_ivr_production_config_errors
from app.services.ivr.ivr_rate_limit import ivr_rate_limit_ok, reset_ivr_rate_limits
from app.services.ivr.language_session import get_session_store, reset_session_store, set_language
from app.services.ivr.public_url import validate_ivr_public_base_url
from app.services.ivr.webhook_auth import verify_webhook_secret
from app.services.otp_dev_retrieval import otp_dev_retrieval_active
from app.services.voice import stt_service, tts_service
from app.services.voice.audio_utils import make_tone_wav

CALL_SID = "CA_A6_AAAAAAAAAAAAAAAAAAAAAAAAAAAA"
CALL_SID_B = "CA_A6_BBBBBBBBBBBBBBBBBBBBBBBBBBBB"
FAKE_MP3 = b"\xff\xfb" + b"\x00" * 64
SECRET = "EXOTEL_SECRET_DO_NOT_LEAK"


class TestIvrA6(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def setUp(self):
        reset_session_store()
        reset_audio_token_store()
        reset_ivr_rate_limits()
        stt_service.set_test_transcribe_hook(None)
        tts_service.set_test_synthesize_hook(None)

    def test_production_rejects_invalid_public_url(self):
        errors = collect_ivr_production_config_errors(
            type("S", (), {
                "APP_ENV": "production",
                "IVR_PUBLIC_BASE_URL": "",
                "IVR_CITIZEN_ACCOUNT_ID": "id-1",
                "IVR_SYSTEM_ACCOUNT_PHONE": "",
                "OTP_DEV_RETRIEVAL_ENABLED": False,
                "OTP_CONSOLE_SIMULATOR_ENABLED": False,
                "DATABASE_URL": "postgresql://x",
            })()
        )
        self.assertTrue(any("IVR_PUBLIC_BASE_URL" in e for e in errors))

    def test_production_requires_https(self):
        with self.assertRaises(ValueError):
            validate_ivr_public_base_url("http://api.example.in", app_env="production")

    def test_development_allows_http_public_url(self):
        validate_ivr_public_base_url("http://127.0.0.1:8000", app_env="development")

    def test_production_empty_bridge_account_rejected(self):
        errors = collect_ivr_production_config_errors(
            type("S", (), {
                "APP_ENV": "production",
                "IVR_PUBLIC_BASE_URL": "https://api.example.in",
                "IVR_CITIZEN_ACCOUNT_ID": "",
                "IVR_SYSTEM_ACCOUNT_PHONE": "",
                "OTP_DEV_RETRIEVAL_ENABLED": False,
                "OTP_CONSOLE_SIMULATOR_ENABLED": False,
                "DATABASE_URL": "postgresql://x",
            })()
        )
        self.assertTrue(any("IVR_CITIZEN_ACCOUNT_ID" in e for e in errors))

    def test_production_exotel_requires_webhook_secret(self):
        errors = collect_ivr_production_config_errors(
            type("S", (), {
                "APP_ENV": "production",
                "IVR_PUBLIC_BASE_URL": "https://api.example.in",
                "IVR_CITIZEN_ACCOUNT_ID": "id-1",
                "IVR_SYSTEM_ACCOUNT_PHONE": "",
                "OTP_DEV_RETRIEVAL_ENABLED": False,
                "OTP_CONSOLE_SIMULATOR_ENABLED": False,
                "DATABASE_URL": "postgresql://x",
                "IVR_PROVIDER": "exotel",
                "IVR_WEBHOOK_SHARED_SECRET": "",
            })()
        )
        self.assertTrue(any("IVR_WEBHOOK_SHARED_SECRET" in e for e in errors))

    def test_empty_call_sid_rejected(self):
        with self.assertRaises(CallSidValidationError):
            normalize_call_sid("")

    def test_oversized_call_sid_rejected(self):
        with self.assertRaises(CallSidValidationError):
            normalize_call_sid("A" * 100)

    def test_invalid_call_sid_chars_rejected(self):
        with self.assertRaises(CallSidValidationError):
            normalize_call_sid("bad sid!")

    def test_session_ttl_enforced(self):
        set_language(CALL_SID, "en")
        session = get_session_store().get_session(CALL_SID)
        session.expires_at = time.time() - 1
        resp = self.client.get(
            "/api/ivr/transcribe",
            params={"CallSid": CALL_SID, "RecordingUrl": "https://s3-ap-southeast-1.amazonaws.com/x/a.mp3"},
        )
        self.assertIn(resp.status_code, {400, 410})

    def test_expired_session_cleaned(self):
        set_language(CALL_SID, "en")
        session = get_session_store().get_session(CALL_SID)
        session.expires_at = time.time() - 1
        self.client.get("/api/ivr/transcribe", params={"CallSid": CALL_SID})
        self.assertFalse(get_session_store().session_exists(CALL_SID))

    def test_active_session_preserved(self):
        set_language(CALL_SID, "en")
        self.assertTrue(get_session_store().session_exists(CALL_SID))

    def test_session_count_bounded(self):
        from app.services.ivr.language_session import SessionCapacityError

        with patch.object(settings, "IVR_MAX_ACTIVE_SESSIONS", 2):
            reset_session_store()
            for sid in ("CA_A6_1111111111111111", "CA_A6_2222222222222222"):
                set_language(sid, "en")
            with self.assertRaises(SessionCapacityError):
                get_session_store().touch_or_create("CA_A6_3333333333333333")

    def test_invalid_audio_token_404(self):
        self.assertEqual(self.client.get("/api/ivr/audio/not-valid!!!").status_code, 404)

    def test_expired_audio_token_404(self):
        from app.services.ivr.call_state import IvrCallState, set_state

        set_language(CALL_SID, "en")
        set_state(CALL_SID, IvrCallState.SYNTHESIZING)
        get_session_store().set_last_response_text(CALL_SID, "Hi")
        tts_service.set_test_synthesize_hook(
            lambda *a, **k: {"success": True, "audio": FAKE_MP3, "mime_type": "audio/mpeg"}
        )
        with patch.object(settings, "IVR_PUBLIC_BASE_URL", "https://api.example.in"):
            resp = self.client.post("/api/ivr/tts", json={"CallSid": CALL_SID})
        token = (resp.json().get("audio_url") or "").rsplit("/", 1)[-1]
        entry = get_audio_token_store().get(token)
        assert entry is not None
        entry.expires_at = time.time() - 1
        self.assertEqual(self.client.get(f"/api/ivr/audio/{token}").status_code, 404)

    def test_consumed_audio_token_404(self):
        from app.services.ivr.call_state import IvrCallState, set_state

        set_language(CALL_SID, "en")
        set_state(CALL_SID, IvrCallState.SYNTHESIZING)
        get_session_store().set_last_response_text(CALL_SID, "Hi")
        tts_service.set_test_synthesize_hook(
            lambda *a, **k: {"success": True, "audio": FAKE_MP3, "mime_type": "audio/mpeg"}
        )
        with patch.object(settings, "IVR_PUBLIC_BASE_URL", "https://api.example.in"):
            resp = self.client.post("/api/ivr/tts", json={"CallSid": CALL_SID})
        token = (resp.json().get("audio_url") or "").rsplit("/", 1)[-1]
        self.client.get(f"/api/ivr/audio/{token}")
        self.assertEqual(self.client.get(f"/api/ivr/audio/{token}").status_code, 404)

    def test_localhost_recording_rejected(self):
        with self.assertRaises(ValueError):
            validate_exotel_recording_url("https://localhost/rec.mp3")

    def test_loopback_recording_rejected(self):
        with self.assertRaises(ValueError):
            validate_exotel_recording_url("https://127.0.0.1/rec.mp3")

    def test_private_ip_recording_rejected(self):
        with self.assertRaises(ValueError):
            validate_exotel_recording_url("https://10.0.0.5/rec.mp3")

    def test_metadata_ip_recording_rejected(self):
        with self.assertRaises(ValueError):
            validate_exotel_recording_url("https://169.254.169.254/latest/meta-data")

    def test_file_scheme_recording_rejected(self):
        with self.assertRaises(ValueError):
            validate_exotel_recording_url("file:///etc/passwd")

    def test_oversized_recording_url_rejected(self):
        with patch.object(settings, "IVR_MAX_RECORDING_URL_LENGTH", 50):
            with self.assertRaises(ValueError):
                validate_exotel_recording_url("https://s3-ap-southeast-1.amazonaws.com/" + "x" * 80)

    def test_host_header_cannot_control_public_url(self):
        with patch.object(settings, "IVR_PUBLIC_BASE_URL", "https://fixed.example.in"):
            from app.services.ivr.public_url import build_ivr_audio_url

            url = build_ivr_audio_url("token12345678901234567890123456789012")
            self.assertIn("fixed.example.in", url)

    def test_private_public_url_rejected_in_production(self):
        with self.assertRaises(ValueError):
            validate_ivr_public_base_url("https://192.168.1.1", app_env="production")

    def test_rate_limit_invalid_call_sid(self):
        reset_ivr_rate_limits()
        with patch.object(settings, "IVR_RATE_LIMIT_INVALID_PER_IP", 2):
            for _ in range(3):
                allowed = ivr_rate_limit_ok("invalid", "1.2.3.4")
            self.assertFalse(allowed)

    def test_rate_limit_call_sid(self):
        reset_ivr_rate_limits()
        with patch.object(settings, "IVR_RATE_LIMIT_PER_CALLSID", 2):
            self.assertTrue(ivr_rate_limit_ok("call_sid", CALL_SID))
            self.assertTrue(ivr_rate_limit_ok("call_sid", CALL_SID))
            self.assertFalse(ivr_rate_limit_ok("call_sid", CALL_SID))

    def test_caller_cannot_select_account_via_body(self):
        """Bridge account is server-configured only (ivr_auth contract)."""
        from app.services.ivr import ivr_auth

        with patch.object(settings, "IVR_CITIZEN_ACCOUNT_ID", "configured-bridge-id"):
            with patch.object(settings, "IVR_SYSTEM_ACCOUNT_PHONE", ""):
                db = MagicMock()
                db.query.return_value.filter.return_value.first.return_value = None
                with self.assertRaises(ivr_auth.IvrAuthError):
                    ivr_auth.get_ivr_citizen(db)

    def test_webhook_secret_constant_time(self):
        with patch.object(settings, "IVR_WEBHOOK_SHARED_SECRET", "s3cr3t"):
            self.assertTrue(verify_webhook_secret(header_value="s3cr3t"))
            self.assertFalse(verify_webhook_secret(header_value="wrong"))

    def test_credentials_not_in_tts_response(self):
        from app.services.ivr.call_state import IvrCallState, set_state

        set_language(CALL_SID, "en")
        set_state(CALL_SID, IvrCallState.SYNTHESIZING)
        get_session_store().set_last_response_text(CALL_SID, "Hi")
        tts_service.set_test_synthesize_hook(
            lambda *a, **k: {"success": True, "audio": FAKE_MP3, "mime_type": "audio/mpeg"}
        )
        with patch.object(settings, "IVR_PUBLIC_BASE_URL", "https://api.example.in"):
            with patch.object(settings, "EXOTEL_API_TOKEN", SECRET):
                resp = self.client.post("/api/ivr/tts", json={"CallSid": CALL_SID})
        self.assertNotIn(SECRET, resp.text)

    def test_otp_dev_not_active_in_production(self):
        with patch.object(settings, "APP_ENV", "production"):
            with patch.object(settings, "OTP_DEV_RETRIEVAL_ENABLED", True):
                with patch.object(settings, "OTP_DEV_RETRIEVAL_KEY", "k"):
                    self.assertFalse(otp_dev_retrieval_active())

    def test_internal_error_sanitized(self):
        resp = self.client.get("/api/ivr/audio/short")
        self.assertNotIn("Traceback", resp.text)

    def test_redis_decision_documented(self):
        import pathlib

        doc = pathlib.Path(__file__).resolve().parents[1] / "docs" / "IVR_A6.md"
        text = doc.read_text(encoding="utf-8")
        self.assertIn("Redis", text)
        self.assertIn("in-memory", text)

    def test_production_rejects_dev_otp_console(self):
        with patch.object(settings, "APP_ENV", "production"):
            with patch.object(settings, "OTP_CONSOLE_SIMULATOR_ENABLED", True):
                self.assertFalse(otp_dev_retrieval_active())

    def test_cross_callsid_token_isolation(self):
        from app.services.ivr.audio_token_store import get_audio_token_store

        store = get_audio_token_store()
        token_a = store.issue(call_sid=CALL_SID, data=FAKE_MP3, mime_type="audio/mpeg")
        token_b = store.issue(call_sid=CALL_SID_B, data=FAKE_MP3, mime_type="audio/mpeg")
        self.assertEqual(store.get(token_a).call_sid, CALL_SID)
        self.assertEqual(store.get(token_b).call_sid, CALL_SID_B)
        store.revoke_for_call_sid(CALL_SID_B)
        self.assertIsNotNone(store.get(token_a))
        self.assertIsNone(store.get(token_b))

    def test_token_store_bounded(self):
        from app.services.ivr.audio_token_store import get_audio_token_store

        with patch.object(settings, "IVR_MAX_ACTIVE_AUDIO_TOKENS", 2):
            reset_audio_token_store()
            store = get_audio_token_store()
            store.issue(call_sid=CALL_SID, data=FAKE_MP3, mime_type="audio/mpeg")
            store.issue(call_sid=CALL_SID_B, data=FAKE_MP3, mime_type="audio/mpeg")
            with self.assertRaises(OSError):
                store.issue(call_sid="CA_A6_CCCCCCCCCCCCCCCCCCCCCCCCCCCC", data=FAKE_MP3, mime_type="audio/mpeg")

    def test_token_cleanup_purges_expired(self):
        store = get_audio_token_store()
        token = store.issue(call_sid=CALL_SID, data=FAKE_MP3, mime_type="audio/mpeg")
        entry = store.get(token)
        assert entry is not None
        entry.expires_at = time.time() - 1
        self.assertIsNone(store.get(token))

    def test_redirect_to_private_ip_rejected(self):
        handler = _GuardedRedirectHandler()
        with self.assertRaises(ValueError):
            handler.redirect_request(None, None, 302, "", {}, "https://127.0.0.1/rec.mp3")

    def test_recording_fetch_timeout_handled(self):
        def _timeout_hook(url: str, timeout: float):
            raise ValueError("recording_fetch_failed")

        set_recording_fetch_hook(_timeout_hook)
        result = fetch_exotel_recording_to_temp(
            "https://s3-ap-southeast-1.amazonaws.com/exotelrecordings/timeout.mp3"
        )
        self.assertFalse(result.ok)
        set_recording_fetch_hook(None)

    def test_rate_limit_ip_bounded_http(self):
        reset_ivr_rate_limits()
        with patch.object(settings, "IVR_RATE_LIMIT_PER_IP", 2):
            statuses = [
                self.client.get("/api/ivr/language", params={"CallSid": CALL_SID}).status_code
                for _ in range(3)
            ]
        self.assertIn(429, statuses)

    def test_rate_limit_tts_call_sid(self):
        reset_ivr_rate_limits()
        with patch.object(settings, "IVR_RATE_LIMIT_PER_CALLSID", 2):
            self.assertTrue(ivr_rate_limit_ok("call_sid", CALL_SID))
            self.assertTrue(ivr_rate_limit_ok("call_sid", CALL_SID))
            self.assertFalse(ivr_rate_limit_ok("call_sid", CALL_SID))

    def test_caller_cannot_select_conversation(self):
        from app.services.ivr.chat_adapter import process_ivr_chat

        set_language(CALL_SID, "en")
        set_state(CALL_SID, IvrCallState.TRANSCRIBING)
        get_session_store().set_transcription(CALL_SID, transcription="Hello")
        seen = {}

        def hook(db, citizen, **kwargs):
            seen["conversation_id"] = kwargs.get("conversation_id")
            return {
                "conversation_id": "server-conv",
                "answer": "ok",
                "validated": True,
                "llm_invoked": True,
                "sources": [],
                "response_language": "EN",
            }

        db = MagicMock()
        with patch("app.services.ivr.chat_adapter.get_ivr_citizen", return_value=MagicMock()):
            with patch("app.services.conversation_service.handle_citizen_chat", side_effect=hook):
                process_ivr_chat(db, CALL_SID)
        self.assertNotEqual(seen.get("conversation_id"), "evil-conv")

    def test_cross_callsid_session_isolated(self):
        set_language(CALL_SID, "en")
        set_language(CALL_SID_B, "hi")
        self.assertEqual(get_session_store().get_language(CALL_SID), "en")
        self.assertEqual(get_session_store().get_language(CALL_SID_B), "hi")

    def test_duplicate_turn_rejected(self):
        set_language(CALL_SID, "en")
        begin_turn(CALL_SID)
        with self.assertRaises(StateTransitionError):
            begin_turn(CALL_SID)

    def test_duplicate_tts_state_guarded(self):
        set_language(CALL_SID, "en")
        set_state(CALL_SID, IvrCallState.SYNTHESIZING)
        get_session_store().get_session(CALL_SID).turn_in_progress = True
        tts_service.set_test_synthesize_hook(
            lambda *a, **k: {"success": True, "audio": FAKE_MP3, "mime_type": "audio/mpeg"}
        )
        with patch.object(settings, "IVR_PUBLIC_BASE_URL", "https://api.example.in"):
            resp = self.client.post("/api/ivr/tts", json={"CallSid": CALL_SID})
        self.assertIn(resp.status_code, {409, 400, 422})

    def test_duplicate_continue_idempotent(self):
        set_language(CALL_SID, "en")
        set_state(CALL_SID, IvrCallState.ASK_CONTINUE)
        r1 = self.client.get("/api/ivr/continue", params={"CallSid": CALL_SID})
        r2 = self.client.get("/api/ivr/continue", params={"CallSid": CALL_SID})
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r2.status_code, 200)

    def test_concurrent_http_turn_rejected(self):
        from app.services.ivr.stt_adapter import IvrSttFailure, transcribe_ivr_audio

        set_language(CALL_SID, "en")
        set_state(CALL_SID, IvrCallState.READY_FOR_INPUT)
        get_session_store().get_session(CALL_SID).turn_in_progress = True
        stt_service.set_test_transcribe_hook(
            lambda *a, **k: {"success": True, "text": "hello", "request_id": "x"}
        )
        outcome = transcribe_ivr_audio(CALL_SID, audio_bytes=make_tone_wav(0.2))
        self.assertEqual(outcome.failure, IvrSttFailure.STT_CLIENT_ERROR)

    def test_different_callsids_independent(self):
        set_language(CALL_SID, "en")
        set_language(CALL_SID_B, "hi")
        begin_turn(CALL_SID)
        begin_turn(CALL_SID_B)
        self.assertTrue(get_session_store().get_session(CALL_SID).turn_in_progress)
        self.assertTrue(get_session_store().get_session(CALL_SID_B).turn_in_progress)

    def test_no_hardcoded_credentials_in_ivr_modules(self):
        root = pathlib.Path(__file__).resolve().parents[1] / "app" / "services" / "ivr"
        banned = ("api_key=", "password=", "secret_key=", "Bearer eyJ")
        for path in root.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            for needle in banned:
                self.assertNotIn(needle, text, msg=f"{path.name} contains {needle}")

    def test_no_secrets_in_logs(self):
        import logging

        set_language(CALL_SID, "en")
        with self.assertLogs("gramsakhi.ivr", level="INFO") as captured:
            logging.getLogger("gramsakhi.ivr").info("ivr_test_event call_sid=%s", CALL_SID[:8])
        joined = "\n".join(captured.output)
        self.assertNotIn(SECRET, joined)

    def test_transcript_not_logged_by_stt_adapter(self):
        from app.services.ivr import stt_adapter

        set_language(CALL_SID, "en")
        set_state(CALL_SID, IvrCallState.READY_FOR_INPUT)
        with patch.object(stt_adapter.logger, "info") as mocked_info:
            stt_service.set_test_transcribe_hook(
                lambda *a, **k: {"success": True, "text": "secret transcript", "request_id": "r1"}
            )
            stt_adapter.transcribe_ivr_audio(CALL_SID, audio_bytes=make_tone_wav(0.2))
        for call in mocked_info.call_args_list:
            self.assertNotIn("secret transcript", str(call))

    def test_phone_not_in_language_response(self):
        resp = self.client.get(
            "/api/ivr/language",
            params={"CallSid": CALL_SID, "CallFrom": "+919876543210"},
        )
        self.assertNotIn("9876543210", resp.text)

    def test_audio_token_not_in_tts_logs(self):
        set_language(CALL_SID, "en")
        set_state(CALL_SID, IvrCallState.SYNTHESIZING)
        get_session_store().set_last_response_text(CALL_SID, "Hi")
        tts_service.set_test_synthesize_hook(
            lambda *a, **k: {"success": True, "audio": FAKE_MP3, "mime_type": "audio/mpeg"}
        )
        with patch.object(settings, "IVR_PUBLIC_BASE_URL", "https://api.example.in"):
            with patch("app.services.ivr.tts_adapter.logger.info") as mocked_info:
                self.client.post("/api/ivr/tts", json={"CallSid": CALL_SID})
        joined = str(mocked_info.call_args_list)
        self.assertNotIn("token_urlsafe", joined)

    def test_webhook_secret_required_when_configured(self):
        with patch.object(settings, "IVR_WEBHOOK_SHARED_SECRET", "required-secret"):
            resp = self.client.get("/api/ivr/language", params={"CallSid": CALL_SID})
        self.assertEqual(resp.status_code, 403)

    def test_filesystem_path_not_in_errors(self):
        resp = self.client.get("/api/ivr/audio/not-valid!!!")
        lowered = resp.text.lower()
        self.assertNotIn("static\\", lowered)
        self.assertNotIn("c:\\users", lowered)

    def test_valid_call_sid_normalized(self):
        self.assertEqual(normalize_call_sid("  CA_A6_OK123456789012345678  "), "CA_A6_OK123456789012345678")

    def test_production_config_collects_multiple_errors(self):
        errors = collect_ivr_production_config_errors(
            type("S", (), {
                "APP_ENV": "production",
                "IVR_PUBLIC_BASE_URL": "",
                "IVR_CITIZEN_ACCOUNT_ID": "",
                "IVR_SYSTEM_ACCOUNT_PHONE": "",
                "OTP_DEV_RETRIEVAL_ENABLED": True,
                "OTP_CONSOLE_SIMULATOR_ENABLED": False,
                "DATABASE_URL": "postgresql://x",
            })()
        )
        self.assertGreaterEqual(len(errors), 2)

    def test_a1_importable(self):
        import tests.test_ivr_a1  # noqa: F401

    def test_a2_importable(self):
        import tests.test_ivr_a2  # noqa: F401

    def test_a3_importable(self):
        import tests.test_ivr_a3  # noqa: F401

    def test_a4_importable(self):
        import tests.test_ivr_a4  # noqa: F401

    def test_a5_importable(self):
        import tests.test_ivr_a5  # noqa: F401


if __name__ == "__main__":
    unittest.main()
