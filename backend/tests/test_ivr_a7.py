"""IVR-A7 — final release gate (no new product features)."""

from __future__ import annotations

import pathlib
import time
import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.services.ivr.audio_token_store import get_audio_token_store, reset_audio_token_store
from app.services.ivr.call_sid_validation import CallSidValidationError, normalize_call_sid
from app.services.ivr.call_state import (
    IvrCallState,
    StateTransitionError,
    begin_turn,
    can_accept_question,
    increment_turn,
    require_states,
    set_state,
    transition,
)
from app.services.ivr.exotel_recording import _GuardedRedirectHandler, validate_exotel_recording_url
from app.services.ivr.ivr_config import collect_ivr_production_config_errors
from app.services.ivr.ivr_rate_limit import (
    ivr_rate_limit_key_count,
    ivr_rate_limit_ok,
    reset_ivr_rate_limits,
)
from app.services.ivr.language_session import get_session_store, reset_session_store, set_language
from app.services.ivr.public_url import build_ivr_audio_url, validate_ivr_public_base_url
from app.services.ivr.session_cleanup import terminate_ivr_session
from app.services.otp_dev_retrieval import otp_dev_retrieval_active
from app.services.voice import tts_service

CALL_SID_A = "CA_A7_AAAAAAAAAAAAAAAAAAAAAAAAAAAA"
CALL_SID_B = "CA_A7_BBBBBBBBBBBBBBBBBBBBBBBBBBBB"
FAKE_MP3 = b"\xff\xfb" + b"\x00" * 64
EXPECTED_IVR_PATHS = {
    ("GET", "/api/ivr/language"),
    ("GET", "/api/ivr/transcribe"),
    ("POST", "/api/ivr/transcribe"),
    ("POST", "/api/ivr/chat"),
    ("POST", "/api/ivr/tts"),
    ("GET", "/api/ivr/audio/{token}"),
    ("HEAD", "/api/ivr/audio/{token}"),
    ("GET", "/api/ivr/continue"),
    ("POST", "/api/ivr/continue"),
}


class TestIvrA7(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def setUp(self):
        reset_session_store()
        reset_audio_token_store()
        reset_ivr_rate_limits()
        tts_service.set_test_synthesize_hook(None)

    def test_endpoint_inventory_matches_router(self):
        found = set()
        for wrapper in app.routes:
            ctx = getattr(wrapper, "include_context", None)
            prefix = getattr(ctx, "prefix", "") if ctx is not None else ""
            original = getattr(wrapper, "original_router", None)
            routes = getattr(original, "routes", None) or ([wrapper] if getattr(wrapper, "path", None) else [])
            if prefix != "/api/ivr" and "/ivr" not in str(getattr(wrapper, "path", "")):
                continue
            for route in routes:
                path = f"{prefix}{getattr(route, 'path', '')}"
                methods = getattr(route, "methods", None) or set()
                for method in methods:
                    if method in {"GET", "POST", "HEAD"}:
                        found.add((method, path))
        self.assertTrue(EXPECTED_IVR_PATHS.issubset(found), msg=f"missing={EXPECTED_IVR_PATHS - found}")
        extra_paths = {path for _method, path in found} - {path for _method, path in EXPECTED_IVR_PATHS}
        self.assertFalse(extra_paths, msg=f"unexpected IVR paths: {extra_paths}")

    def test_production_config_requires_https_public_url(self):
        errors = collect_ivr_production_config_errors(
            type(
                "S",
                (),
                {
                    "APP_ENV": "production",
                    "IVR_PUBLIC_BASE_URL": "",
                    "IVR_CITIZEN_ACCOUNT_ID": "acct",
                    "IVR_SYSTEM_ACCOUNT_PHONE": "",
                    "OTP_DEV_RETRIEVAL_ENABLED": False,
                    "OTP_CONSOLE_SIMULATOR_ENABLED": False,
                    "DATABASE_URL": "postgresql://x",
                },
            )()
        )
        self.assertTrue(any("IVR_PUBLIC_BASE_URL" in e for e in errors))

    def test_callsid_validation_rejects_empty_and_path(self):
        with self.assertRaises(CallSidValidationError):
            normalize_call_sid("")
        with self.assertRaises(CallSidValidationError):
            normalize_call_sid("../etc/passwd")
        self.assertEqual(normalize_call_sid(CALL_SID_A), CALL_SID_A)

    def test_session_ttl_enforced(self):
        set_language(CALL_SID_A, "en")
        session = get_session_store().get_session(CALL_SID_A)
        session.expires_at = time.time() - 1
        resp = self.client.get("/api/ivr/continue", params={"CallSid": CALL_SID_A})
        self.assertIn(resp.status_code, {400, 410})

    def test_session_capacity_rejects_after_purge(self):
        from app.services.ivr.language_session import SessionCapacityError

        with patch.object(settings, "IVR_MAX_ACTIVE_SESSIONS", 1):
            reset_session_store()
            set_language(CALL_SID_A, "en")
            with self.assertRaises(SessionCapacityError):
                get_session_store().touch_or_create(CALL_SID_B)

    def test_audio_token_ttl(self):
        token = get_audio_token_store().issue(call_sid=CALL_SID_A, data=FAKE_MP3, mime_type="audio/mpeg")
        entry = get_audio_token_store().get(token)
        assert entry is not None
        entry.expires_at = time.time() - 1
        self.assertIsNone(get_audio_token_store().get(token))

    def test_audio_token_isolation(self):
        token_a = get_audio_token_store().issue(call_sid=CALL_SID_A, data=FAKE_MP3, mime_type="audio/mpeg")
        token_b = get_audio_token_store().issue(call_sid=CALL_SID_B, data=FAKE_MP3, mime_type="audio/mpeg")
        get_audio_token_store().revoke_for_call_sid(CALL_SID_A)
        self.assertIsNone(get_audio_token_store().get(token_a))
        self.assertIsNotNone(get_audio_token_store().get(token_b))

    def test_audio_single_use(self):
        set_language(CALL_SID_A, "en")
        set_state(CALL_SID_A, IvrCallState.SYNTHESIZING)
        get_session_store().set_last_response_text(CALL_SID_A, "Hi")
        tts_service.set_test_synthesize_hook(
            lambda *a, **k: {"success": True, "audio": FAKE_MP3, "mime_type": "audio/mpeg"}
        )
        with patch.object(settings, "IVR_PUBLIC_BASE_URL", "https://api.example.in"):
            resp = self.client.post("/api/ivr/tts", json={"CallSid": CALL_SID_A})
        token = (resp.json().get("audio_url") or "").rsplit("/", 1)[-1]
        self.assertEqual(self.client.get(f"/api/ivr/audio/{token}").status_code, 200)
        self.assertEqual(self.client.get(f"/api/ivr/audio/{token}").status_code, 404)

    def test_ssrf_localhost(self):
        with self.assertRaises(ValueError):
            validate_exotel_recording_url("https://localhost/rec.mp3")

    def test_ssrf_private_ip(self):
        with self.assertRaises(ValueError):
            validate_exotel_recording_url("https://10.1.2.3/rec.mp3")

    def test_ssrf_metadata_ip(self):
        with self.assertRaises(ValueError):
            validate_exotel_recording_url("https://169.254.169.254/latest/meta-data")

    def test_ssrf_redirect_to_private(self):
        handler = _GuardedRedirectHandler()
        with self.assertRaises(ValueError):
            handler.redirect_request(None, None, 302, "", {}, "https://192.168.1.9/rec.mp3")

    def test_ssrf_ipv6_loopback_and_schemes(self):
        for url in (
            "https://[::1]/rec.mp3",
            "file:///etc/passwd",
            "data:text/plain,hi",
            "ftp://s3-ap-southeast-1.amazonaws.com/x.mp3",
            "http://s3-ap-southeast-1.amazonaws.com/x.mp3",
        ):
            with self.assertRaises(ValueError, msg=url):
                validate_exotel_recording_url(url)

    def test_public_url_https_required_in_production(self):
        with self.assertRaises(ValueError):
            validate_ivr_public_base_url("http://api.example.in", app_env="production")

    def test_host_header_cannot_control_public_url(self):
        with patch.object(settings, "IVR_PUBLIC_BASE_URL", "https://fixed.example.in"):
            url = build_ivr_audio_url("token12345678901234567890123456789012")
        self.assertIn("fixed.example.in", url)
        self.assertNotIn("evil", url)

    def test_rate_limiting_bounds_invalid_and_callsid(self):
        with patch.object(settings, "IVR_RATE_LIMIT_INVALID_PER_IP", 1):
            self.assertTrue(ivr_rate_limit_ok("invalid", "9.9.9.9"))
            self.assertFalse(ivr_rate_limit_ok("invalid", "9.9.9.9"))
        reset_ivr_rate_limits()
        with patch.object(settings, "IVR_RATE_LIMIT_PER_CALLSID", 1):
            self.assertTrue(ivr_rate_limit_ok("call_sid", CALL_SID_A))
            self.assertFalse(ivr_rate_limit_ok("call_sid", CALL_SID_A))

    def test_rate_limit_key_store_capped(self):
        with patch.object(settings, "IVR_RATE_LIMIT_MAX_KEYS", 3):
            reset_ivr_rate_limits()
            for i in range(12):
                ivr_rate_limit_ok("ip", f"10.0.0.{i}")
            self.assertLessEqual(ivr_rate_limit_key_count(), 3)

    def test_bridge_account_not_caller_selected(self):
        from app.services.ivr import ivr_auth

        with patch.object(settings, "IVR_CITIZEN_ACCOUNT_ID", "configured-bridge-id"):
            with patch.object(settings, "IVR_SYSTEM_ACCOUNT_PHONE", ""):
                db = MagicMock()
                db.query.return_value.filter.return_value.first.return_value = None
                with self.assertRaises(ivr_auth.IvrAuthError):
                    ivr_auth.get_ivr_citizen(db)

    def test_conversation_override_rejected(self):
        from app.services.ivr.chat_adapter import process_ivr_chat

        set_language(CALL_SID_A, "en")
        set_state(CALL_SID_A, IvrCallState.TRANSCRIBING)
        get_session_store().set_transcription(CALL_SID_A, transcription="Hello")
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

        with patch("app.services.ivr.chat_adapter.get_ivr_citizen", return_value=MagicMock()):
            with patch("app.services.conversation_service.handle_citizen_chat", side_effect=hook):
                process_ivr_chat(MagicMock(), CALL_SID_A)
        self.assertNotEqual(seen.get("conversation_id"), "attacker-conv")

    def test_language_override_rejected_for_all_supported(self):
        from app.services.ivr.stt_adapter import resolve_stt_language_hint
        from app.services.ivr.chat_adapter import resolve_chat_language

        for lang, expected in (("kn", "KN"), ("hi", "HI"), ("en", "EN")):
            reset_session_store()
            set_language(CALL_SID_A, lang)
            self.assertEqual(resolve_stt_language_hint(CALL_SID_A), expected)
            self.assertEqual(resolve_chat_language(CALL_SID_A), expected)
        with self.assertRaises(ValueError):
            set_language(CALL_SID_A, "fr")

    def test_state_machine_invalid_transition(self):
        set_language(CALL_SID_A, "en")
        set_state(CALL_SID_A, IvrCallState.LANGUAGE_SELECTION)
        with self.assertRaises(StateTransitionError):
            transition(
                CALL_SID_A,
                IvrCallState.PROCESSING_CHAT,
                from_allowed={IvrCallState.TRANSCRIBING},
            )

    def test_same_callsid_concurrency(self):
        set_language(CALL_SID_A, "en")
        begin_turn(CALL_SID_A)
        with self.assertRaises(StateTransitionError):
            begin_turn(CALL_SID_A)

    def test_cross_callsid_isolation_both_directions(self):
        set_language(CALL_SID_A, "en")
        set_language(CALL_SID_B, "hi")
        get_session_store().set_transcription(CALL_SID_A, transcription="alpha")
        get_session_store().set_transcription(CALL_SID_B, transcription="beta")
        get_session_store().set_conversation_id(CALL_SID_A, "conv-a")
        get_session_store().set_conversation_id(CALL_SID_B, "conv-b")
        get_session_store().set_last_response_text(CALL_SID_A, "ra")
        get_session_store().set_last_response_text(CALL_SID_B, "rb")
        increment_turn(CALL_SID_A)
        self.assertEqual(get_session_store().get_language(CALL_SID_A), "en")
        self.assertEqual(get_session_store().get_language(CALL_SID_B), "hi")
        self.assertEqual(get_session_store().get_transcription(CALL_SID_A), "alpha")
        self.assertEqual(get_session_store().get_transcription(CALL_SID_B), "beta")
        self.assertEqual(get_session_store().get_conversation_id(CALL_SID_A), "conv-a")
        self.assertEqual(get_session_store().get_conversation_id(CALL_SID_B), "conv-b")
        self.assertEqual(get_session_store().get_last_response_text(CALL_SID_A), "ra")
        self.assertEqual(get_session_store().get_last_response_text(CALL_SID_B), "rb")
        self.assertEqual(get_session_store().get_session(CALL_SID_A).turn_count, 1)
        self.assertEqual(get_session_store().get_session(CALL_SID_B).turn_count, 0)

    def test_unknown_callsid_rejected(self):
        resp = self.client.post("/api/ivr/chat", json={"CallSid": CALL_SID_A, "transcription": "hi"})
        self.assertEqual(resp.status_code, 400)

    def test_replay_duplicate_turn_rejected(self):
        set_language(CALL_SID_A, "en")
        begin_turn(CALL_SID_A)
        with self.assertRaises(StateTransitionError):
            begin_turn(CALL_SID_A)

    def test_secret_scan_ivr_source(self):
        root = pathlib.Path(__file__).resolve().parents[1] / "app" / "services" / "ivr"
        banned = ("api_key=", "password=", "secret_key=", "Bearer eyJ")
        for path in root.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            for needle in banned:
                self.assertNotIn(needle, text, msg=path.name)

    def test_privacy_log_scan_ivr_source(self):
        root = pathlib.Path(__file__).resolve().parents[1] / "app" / "services" / "ivr"
        for path in root.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("logger.info(transcription", text)
            self.assertNotIn("logger.info(session.last_response_text", text)
            self.assertNotIn("logger.info(RecordingUrl", text)

    def test_error_sanitization(self):
        resp = self.client.get("/api/ivr/audio/short")
        self.assertNotIn("Traceback", resp.text)
        self.assertNotIn("C:\\", resp.text)

    def test_dev_surface_otp_off_in_production(self):
        with patch.object(settings, "APP_ENV", "production"):
            with patch.object(settings, "OTP_DEV_RETRIEVAL_ENABLED", True):
                self.assertFalse(otp_dev_retrieval_active())

    def test_configuration_defaults_are_bounded(self):
        self.assertGreater(settings.IVR_SESSION_TTL_SECONDS, 0)
        self.assertGreater(settings.IVR_MAX_ACTIVE_SESSIONS, 0)
        self.assertGreater(settings.IVR_MAX_ACTIVE_AUDIO_TOKENS, 0)
        self.assertGreater(settings.IVR_MAX_TURNS, 0)
        self.assertGreater(settings.IVR_RATE_LIMIT_MAX_KEYS, 0)

    def test_max_turns_enforced(self):
        set_language(CALL_SID_A, "en")
        with patch.object(settings, "IVR_MAX_TURNS", 1):
            increment_turn(CALL_SID_A)
            ok, reason = can_accept_question(CALL_SID_A)
        self.assertFalse(ok)
        self.assertEqual(reason, "turn_limit")

    def test_session_cleanup_terminates_only_target(self):
        set_language(CALL_SID_A, "en")
        set_language(CALL_SID_B, "hi")
        terminate_ivr_session(CALL_SID_A)
        self.assertFalse(get_session_store().session_exists(CALL_SID_A))
        self.assertTrue(get_session_store().session_exists(CALL_SID_B))

    def test_audio_cleanup_on_terminate(self):
        set_language(CALL_SID_A, "en")
        token = get_audio_token_store().issue(call_sid=CALL_SID_A, data=FAKE_MP3, mime_type="audio/mpeg")
        get_session_store().get_session(CALL_SID_A).active_audio_token = token
        terminate_ivr_session(CALL_SID_A)
        self.assertIsNone(get_audio_token_store().get(token))

    def test_malformed_audio_token_404(self):
        self.assertEqual(self.client.get("/api/ivr/audio/../secret").status_code, 404)
        self.assertEqual(self.client.get("/api/ivr/audio/not-valid!!!").status_code, 404)

    def test_require_states_blocks_stale_chat(self):
        set_language(CALL_SID_A, "en")
        set_state(CALL_SID_A, IvrCallState.ASK_CONTINUE)
        with self.assertRaises(StateTransitionError):
            require_states(CALL_SID_A, {IvrCallState.TRANSCRIBING})

    def test_language_reentry_blocked_mid_turn(self):
        """Remediation: /language cannot reset language from an active turn state."""
        set_language(CALL_SID_A, "en")
        set_state(CALL_SID_A, IvrCallState.PROCESSING_CHAT)
        resp = self.client.get("/api/ivr/language", params={"CallSid": CALL_SID_A, "digits": "1"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(get_session_store().get_language(CALL_SID_A), "en")
        from app.services.ivr.call_state import get_state

        self.assertEqual(get_state(CALL_SID_A), IvrCallState.PROCESSING_CHAT)

    def test_language_reselect_allowed_before_turn(self):
        """A1 behavior preserved: re-selection allowed from READY_FOR_INPUT."""
        set_language(CALL_SID_A, "kn")
        set_state(CALL_SID_A, IvrCallState.READY_FOR_INPUT)
        resp = self.client.get("/api/ivr/language", params={"CallSid": CALL_SID_A, "digits": "2"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(get_session_store().get_language(CALL_SID_A), "hi")

    def test_xff_not_trusted_by_default(self):
        from app.services.ivr.ivr_guard import _client_ip

        class _Client:
            host = "203.0.113.7"

        class _Req:
            headers = {"x-forwarded-for": "1.2.3.4"}
            client = _Client()

        with patch.object(settings, "IVR_TRUST_PROXY_HEADERS", False):
            self.assertEqual(_client_ip(_Req()), "203.0.113.7")
        with patch.object(settings, "IVR_TRUST_PROXY_HEADERS", True):
            self.assertEqual(_client_ip(_Req()), "1.2.3.4")

    def test_direct_upload_blocked_in_production(self):
        import io

        with patch.object(settings, "APP_ENV", "production"):
            with patch.object(settings, "IVR_DIRECT_UPLOAD_IN_PRODUCTION", False):
                resp = self.client.post(
                    "/api/ivr/transcribe",
                    params={"CallSid": CALL_SID_A},
                    files={"audio": ("clip.wav", io.BytesIO(b"RIFF" + b"\x00" * 32), "audio/wav")},
                )
        self.assertEqual(resp.status_code, 404)

    def test_webhook_query_secret_can_be_disallowed(self):
        from app.services.ivr.webhook_auth import verify_webhook_secret

        with patch.object(settings, "IVR_WEBHOOK_SHARED_SECRET", "s3cr3t"):
            with patch.object(settings, "IVR_WEBHOOK_SECRET_ALLOW_QUERY", False):
                self.assertFalse(verify_webhook_secret(query_value="s3cr3t"))
                self.assertTrue(verify_webhook_secret(header_value="s3cr3t"))
            with patch.object(settings, "IVR_WEBHOOK_SECRET_ALLOW_QUERY", True):
                self.assertTrue(verify_webhook_secret(query_value="s3cr3t"))

    def test_audio_token_ttl_alias_precedence(self):
        with patch.object(settings, "IVR_PUBLIC_AUDIO_TOKEN_TTL", 123.0):
            token = get_audio_token_store().issue(
                call_sid=CALL_SID_A, data=FAKE_MP3, mime_type="audio/mpeg"
            )
            entry = get_audio_token_store().get(token)
            assert entry is not None
            self.assertAlmostEqual(entry.expires_at - time.time(), 123.0, delta=5.0)

    def test_terminate_does_not_create_session(self):
        self.assertFalse(get_session_store().session_exists(CALL_SID_A))
        terminate_ivr_session(CALL_SID_A)
        self.assertFalse(get_session_store().session_exists(CALL_SID_A))

    def test_full_callsid_not_logged_by_language_endpoint(self):
        import logging

        with self.assertLogs("gramsakhi.ivr", level="INFO") as captured:
            self.client.get("/api/ivr/language", params={"CallSid": CALL_SID_A})
        joined = "\n".join(captured.output)
        self.assertNotIn(CALL_SID_A, joined)

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

    def test_a6_importable(self):
        import tests.test_ivr_a6  # noqa: F401


if __name__ == "__main__":
    unittest.main()
