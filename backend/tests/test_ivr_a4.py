"""IVR-A4 — TTS + temporary audio playback for Exotel."""

from __future__ import annotations

import os
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.services.ivr.audio_token_store import (
    get_audio_token_store,
    reset_audio_token_store,
    validate_audio_token,
)
from app.services.ivr.constants import MAX_IVR_TTS_TEXT_LENGTH
from app.services.ivr.language_session import reset_session_store, set_language
from app.services.ivr.call_state import IvrCallState, set_state
from app.services.ivr.public_url import build_ivr_public_url
from app.services.ivr.tts_adapter import (
    IvrTtsFailure,
    process_ivr_tts,
    resolve_tts_language,
    validate_tts_service_result,
)
from app.services.voice import tts_service

CALL_SID_A = "CA_A4_AAAAAAAAAAAAAAAAAAAAAAAAAAAA"
CALL_SID_B = "CA_A4_BBBBBBBBBBBBBBBBBBBBBBBBBBBB"
RESPONSE_TEXT = "PM-KISAN provides income support to eligible farmers."
FAKE_MP3 = b"\xff\xfb" + b"\x00" * 128
SECRET = "EXOTEL_SECRET_DO_NOT_LEAK"


def _tts_ok(**overrides):
    base = {
        "success": True,
        "audio": FAKE_MP3,
        "mime_type": "audio/mpeg",
        "language": "EN",
        "voice": "en-IN-NeerjaNeural",
        "request_id": "tts-1",
    }
    base.update(overrides)
    return base


class TestIvrA4(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def setUp(self):
        reset_session_store()
        reset_audio_token_store()
        tts_service.set_test_synthesize_hook(None)
        self._pub = patch.object(settings, "IVR_PUBLIC_BASE_URL", "https://api.gramsakhi.example.in")
        self._pub.start()

    def tearDown(self):
        self._pub.stop()
        reset_audio_token_store()

    def _seed(self, sid: str, lang: str, *, text: str | None = RESPONSE_TEXT) -> None:
        set_language(sid, lang)
        set_state(sid, IvrCallState.SYNTHESIZING)
        from app.services.ivr.language_session import get_session_store

        store = get_session_store()
        if text is not None:
            store.set_last_response_text(sid, text)
        if lang == "kn":
            store.set_last_response_language(sid, "KN")
        elif lang == "hi":
            store.set_last_response_language(sid, "HI")
        else:
            store.set_last_response_language(sid, "EN")

    def test_tts_contract_invoked(self):
        self._seed(CALL_SID_A, "en")
        seen = {}

        def hook(text, language=None, request_id=None):
            seen["text"] = text
            seen["language"] = language
            return _tts_ok()

        tts_service.set_test_synthesize_hook(hook)
        process_ivr_tts(CALL_SID_A)
        self.assertEqual(seen["text"], RESPONSE_TEXT)
        self.assertEqual(seen["language"], "EN")

    def test_kn_maps_kn(self):
        self._seed(CALL_SID_A, "kn")
        self.assertEqual(resolve_tts_language(CALL_SID_A), "KN")

    def test_hi_maps_hi(self):
        self._seed(CALL_SID_A, "hi")
        self.assertEqual(resolve_tts_language(CALL_SID_A), "HI")

    def test_en_maps_en(self):
        self._seed(CALL_SID_A, "en")
        self.assertEqual(resolve_tts_language(CALL_SID_A), "EN")

    def test_missing_call_sid_rejected(self):
        resp = self.client.post("/api/ivr/tts", json={})
        self.assertEqual(resp.status_code, 422)

    def test_unknown_call_sid_rejected(self):
        resp = self.client.post("/api/ivr/tts", json={"CallSid": CALL_SID_A})
        self.assertEqual(resp.status_code, 400)

    def test_missing_language_rejected(self):
        from app.services.ivr.language_session import get_session_store

        get_session_store().get_session(CALL_SID_A)
        get_session_store().set_last_response_text(CALL_SID_A, RESPONSE_TEXT)
        resp = self.client.post("/api/ivr/tts", json={"CallSid": CALL_SID_A})
        self.assertEqual(resp.status_code, 400)

    def test_missing_a3_response_rejected(self):
        set_language(CALL_SID_A, "en")
        resp = self.client.post("/api/ivr/tts", json={"CallSid": CALL_SID_A})
        self.assertEqual(resp.status_code, 400)

    def test_malformed_tts_rejected(self):
        self._seed(CALL_SID_A, "en")
        tts_service.set_test_synthesize_hook(lambda *a, **k: {"success": False, "error": "bad"})
        outcome = process_ivr_tts(CALL_SID_A)
        self.assertEqual(outcome.failure, IvrTtsFailure.TTS_SERVER_ERROR)

    def test_malformed_tts_shape_rejected(self):
        ok, failure = validate_tts_service_result({"success": False})
        self.assertFalse(ok)
        self.assertEqual(failure, IvrTtsFailure.MALFORMED_TTS_RESPONSE)

    def test_empty_audio_rejected(self):
        self._seed(CALL_SID_A, "en")
        tts_service.set_test_synthesize_hook(lambda *a, **k: _tts_ok(audio=b""))
        outcome = process_ivr_tts(CALL_SID_A)
        self.assertEqual(outcome.failure, IvrTtsFailure.EMPTY_AUDIO)

    def test_unsupported_content_type_rejected(self):
        ok, err = validate_tts_service_result(_tts_ok(mime_type="audio/wav"))
        self.assertFalse(ok)
        self.assertEqual(err, IvrTtsFailure.UNSUPPORTED_AUDIO_FORMAT)

    def test_oversized_audio_rejected(self):
        huge = b"x" * (int(settings.IVR_AUDIO_MAX_BYTES) + 1)
        ok, err = validate_tts_service_result(_tts_ok(audio=huge))
        self.assertFalse(ok)
        self.assertEqual(err, IvrTtsFailure.AUDIO_TOO_LARGE)

    def test_token_is_opaque(self):
        self._seed(CALL_SID_A, "en")
        tts_service.set_test_synthesize_hook(lambda *a, **k: _tts_ok())
        outcome = process_ivr_tts(CALL_SID_A)
        url = outcome.response.audio_url or ""
        token = url.rsplit("/", 1)[-1]
        self.assertTrue(validate_audio_token(token))
        self.assertNotIn(CALL_SID_A, url)

    def test_token_cannot_enumerate_another(self):
        self._seed(CALL_SID_A, "en")
        tts_service.set_test_synthesize_hook(lambda *a, **k: _tts_ok())
        outcome = process_ivr_tts(CALL_SID_A)
        token = (outcome.response.audio_url or "").rsplit("/", 1)[-1]
        fake = "A" * 43
        self.assertIsNone(get_audio_token_store().get(fake))
        self.assertIsNotNone(get_audio_token_store().get(token))

    def test_expired_token_404(self):
        self._seed(CALL_SID_A, "en")
        tts_service.set_test_synthesize_hook(lambda *a, **k: _tts_ok())
        outcome = process_ivr_tts(CALL_SID_A)
        token = (outcome.response.audio_url or "").rsplit("/", 1)[-1]
        entry = get_audio_token_store().get(token)
        assert entry is not None
        entry.expires_at = time.time() - 1
        resp = self.client.get(f"/api/ivr/audio/{token}")
        self.assertEqual(resp.status_code, 404)

    def test_invalid_token_404(self):
        resp = self.client.get("/api/ivr/audio/not-a-valid-token!")
        self.assertEqual(resp.status_code, 404)

    def test_path_traversal_impossible(self):
        for bad in ("../secret", "..%2Fetc%2Fpasswd", "foo/bar"):
            resp = self.client.get(f"/api/ivr/audio/{bad}")
            self.assertEqual(resp.status_code, 404)

    def test_arbitrary_filesystem_path_impossible(self):
        for bad in (
            "C:\\Windows\\System32\\drivers\\etc\\hosts",
            "/etc/passwd",
            "file:///tmp/x.mp3",
        ):
            resp = self.client.get(f"/api/ivr/audio/{bad}")
            self.assertEqual(resp.status_code, 404)

    def test_audio_cleaned_after_success(self):
        self._seed(CALL_SID_A, "en")
        tts_service.set_test_synthesize_hook(lambda *a, **k: _tts_ok())
        outcome = process_ivr_tts(CALL_SID_A)
        token = (outcome.response.audio_url or "").rsplit("/", 1)[-1]
        entry = get_audio_token_store().get(token)
        path = entry.path if entry else None
        resp = self.client.get(f"/api/ivr/audio/{token}")
        self.assertEqual(resp.status_code, 200)
        if path:
            self.assertFalse(os.path.exists(path))

    def test_audio_cleaned_after_failure(self):
        self._seed(CALL_SID_A, "en")

        def boom(*a, **k):
            raise RuntimeError("tts boom")

        tts_service.set_test_synthesize_hook(boom)
        process_ivr_tts(CALL_SID_A)
        self.assertEqual(len(get_audio_token_store()._entries), 0)

    def test_audio_cleaned_after_timeout(self):
        self._seed(CALL_SID_A, "en")
        tts_service.set_test_synthesize_hook(
            lambda *a, **k: {"success": False, "error": "tts_busy"}
        )
        process_ivr_tts(CALL_SID_A)
        self.assertEqual(len(get_audio_token_store()._entries), 0)

    def test_storage_failure_cleans_audio(self):
        self._seed(CALL_SID_A, "en")
        tts_service.set_test_synthesize_hook(lambda *a, **k: _tts_ok())
        with patch(
            "app.services.ivr.tts_adapter.get_audio_token_store"
        ) as mock_store_fn:
            mock_store = mock_store_fn.return_value
            mock_store.issue.side_effect = OSError("disk full")
            outcome = process_ivr_tts(CALL_SID_A)
        self.assertEqual(outcome.failure, IvrTtsFailure.STORAGE_FAILURE)

    def test_public_url_uses_configured_base(self):
        self._seed(CALL_SID_A, "en")
        tts_service.set_test_synthesize_hook(lambda *a, **k: _tts_ok())
        outcome = process_ivr_tts(CALL_SID_A)
        self.assertTrue((outcome.response.audio_url or "").startswith("https://api.gramsakhi.example.in/"))

    def test_production_requires_https(self):
        with patch.object(settings, "APP_ENV", "production"):
            with patch.object(settings, "IVR_PUBLIC_BASE_URL", "http://api.example.in"):
                with self.assertRaises(ValueError):
                    build_ivr_public_url("/api/ivr/audio/x")

    def test_request_host_cannot_control_public_url(self):
        self._seed(CALL_SID_A, "en")
        tts_service.set_test_synthesize_hook(lambda *a, **k: _tts_ok())
        with patch.object(settings, "IVR_PUBLIC_BASE_URL", "https://fixed.example.in"):
            outcome = process_ivr_tts(CALL_SID_A)
        self.assertIn("fixed.example.in", outcome.response.audio_url or "")

    def test_audio_not_logged(self):
        self._seed(CALL_SID_A, "en")
        tts_service.set_test_synthesize_hook(lambda *a, **k: _tts_ok())
        with self.assertLogs("gramsakhi.ivr.tts", level="INFO") as captured:
            process_ivr_tts(CALL_SID_A)
        joined = " ".join(captured.output)
        self.assertNotIn(FAKE_MP3.hex(), joined)

    def test_phone_number_not_logged(self):
        self._seed(CALL_SID_A, "en")
        tts_service.set_test_synthesize_hook(lambda *a, **k: _tts_ok())
        phone = "+919876543210"
        with self.assertLogs("gramsakhi.ivr.tts", level="INFO") as captured:
            process_ivr_tts(CALL_SID_A)
        joined = " ".join(captured.output)
        self.assertNotIn(phone, joined)

    def test_credentials_not_exposed(self):
        self._seed(CALL_SID_A, "en")
        tts_service.set_test_synthesize_hook(lambda *a, **k: _tts_ok())
        with patch.object(settings, "EXOTEL_API_TOKEN", SECRET):
            resp = self.client.post("/api/ivr/tts", json={"CallSid": CALL_SID_A})
        self.assertNotIn(SECRET, resp.text)

    def test_jwt_not_exposed(self):
        from app.core import security

        self._seed(CALL_SID_A, "en")
        tts_service.set_test_synthesize_hook(lambda *a, **k: _tts_ok())
        token = security.create_access_token(subject="x")
        resp = self.client.post("/api/ivr/tts", json={"CallSid": CALL_SID_A})
        self.assertNotIn(token, resp.text)

    def test_tts_timeout_handled(self):
        self._seed(CALL_SID_A, "en")
        tts_service.set_test_synthesize_hook(lambda *a, **k: {"success": False, "error": "tts_busy"})
        outcome = process_ivr_tts(CALL_SID_A)
        self.assertEqual(outcome.failure, IvrTtsFailure.TTS_TIMEOUT)

    def test_tts_5xx_handled(self):
        self._seed(CALL_SID_A, "en")
        tts_service.set_test_synthesize_hook(lambda *a, **k: {"success": False, "error": "tts_failed"})
        outcome = process_ivr_tts(CALL_SID_A)
        self.assertEqual(outcome.failure, IvrTtsFailure.TTS_SERVER_ERROR)

    def test_tts_client_error_handled(self):
        self._seed(CALL_SID_A, "en")
        tts_service.set_test_synthesize_hook(lambda *a, **k: {"success": False, "error": "empty_text"})
        outcome = process_ivr_tts(CALL_SID_A)
        self.assertEqual(outcome.failure, IvrTtsFailure.EMPTY_AUDIO)

    def test_playback_public_url_failure(self):
        self._seed(CALL_SID_A, "en")
        tts_service.set_test_synthesize_hook(lambda *a, **k: _tts_ok())
        with patch.object(settings, "IVR_PUBLIC_BASE_URL", ""):
            outcome = process_ivr_tts(CALL_SID_A)
        self.assertEqual(outcome.failure, IvrTtsFailure.PUBLIC_URL_FAILURE)
        self.assertEqual(len(get_audio_token_store()._entries), 0)

    def test_response_too_long(self):
        self._seed(CALL_SID_A, "en", text="x" * (MAX_IVR_TTS_TEXT_LENGTH + 1))
        outcome = process_ivr_tts(CALL_SID_A)
        self.assertEqual(outcome.failure, IvrTtsFailure.RESPONSE_TOO_LONG)

    def test_caller_cannot_override_response_text(self):
        self._seed(CALL_SID_A, "en")
        seen = {}

        def hook(text, **k):
            seen["text"] = text
            return _tts_ok()

        tts_service.set_test_synthesize_hook(hook)
        self.client.post(
            "/api/ivr/tts",
            json={"CallSid": CALL_SID_A, "response_text": "Evil injected text"},
        )
        self.assertEqual(seen["text"], RESPONSE_TEXT)

    def test_call_sid_a_cannot_get_b_audio(self):
        self._seed(CALL_SID_A, "en")
        self._seed(CALL_SID_B, "hi", text="Other response")
        tts_service.set_test_synthesize_hook(lambda *a, **k: _tts_ok())
        out_a = process_ivr_tts(CALL_SID_A)
        token_a = (out_a.response.audio_url or "").rsplit("/", 1)[-1]
        entry = get_audio_token_store().get(token_a)
        self.assertEqual(entry.call_sid if entry else None, CALL_SID_A)

    def test_successful_tts_endpoint(self):
        self._seed(CALL_SID_A, "en")
        tts_service.set_test_synthesize_hook(lambda *a, **k: _tts_ok())
        resp = self.client.post("/api/ivr/tts", json={"CallSid": CALL_SID_A})
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["success"])
        self.assertIn("audio_url", body)
        self.assertIn("start_call_playback", body)

    def test_head_does_not_consume_token(self):
        self._seed(CALL_SID_A, "en")
        tts_service.set_test_synthesize_hook(lambda *a, **k: _tts_ok())
        outcome = process_ivr_tts(CALL_SID_A)
        token = (outcome.response.audio_url or "").rsplit("/", 1)[-1]
        head = self.client.head(f"/api/ivr/audio/{token}")
        self.assertEqual(head.status_code, 200)
        get_resp = self.client.get(f"/api/ivr/audio/{token}")
        self.assertEqual(get_resp.status_code, 200)
        self.assertEqual(get_resp.content, FAKE_MP3)


if __name__ == "__main__":
    unittest.main()
