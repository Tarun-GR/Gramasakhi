"""IVR-A2 — speech-to-text via existing GramSakhi STT service."""

from __future__ import annotations

import io
import json
import logging
import os
import threading
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.services.ivr.exotel_recording import (
    cleanup_recording_temp,
    fetch_exotel_recording_to_temp,
    set_recording_fetch_hook,
    validate_exotel_recording_url,
)
from app.services.ivr.language_session import (
    get_session_store,
    get_transcription,
    reset_session_store,
    set_language,
)
from app.services.ivr.call_state import IvrCallState, set_state
from app.services.ivr.stt_adapter import (
    IvrSttFailure,
    resolve_stt_language_hint,
    transcribe_ivr_audio,
    validate_stt_service_result,
)
from app.services.voice import stt_service
from app.services.voice.audio_utils import make_tone_wav

CALL_SID_A = "CA_A2_AAAAAAAAAAAAAAAAAAAAAAAAAAAA"
CALL_SID_B = "CA_A2_BBBBBBBBBBBBBBBBBBBBBBBBBBBB"
CALLER = "+919876543210"
EXOTEL_MP3_URL = "https://s3-ap-southeast-1.amazonaws.com/exotelrecordings/test.mp3"
SECRET = "EXOTEL_SECRET_TOKEN_DO_NOT_LEAK"


def _tone_bytes() -> bytes:
    return make_tone_wav(0.3)


class TestIvrA2(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def setUp(self):
        reset_session_store()
        stt_service.set_test_transcribe_hook(None)
        set_recording_fetch_hook(None)

    def _seed(self, sid: str, lang: str) -> None:
        set_language(sid, lang)
        set_state(sid, IvrCallState.READY_FOR_INPUT)

    def test_stt_requires_call_sid_get(self):
        resp = self.client.get("/api/ivr/transcribe", params={"RecordingUrl": EXOTEL_MP3_URL})
        self.assertEqual(resp.status_code, 400)

    def test_stt_requires_call_sid_post(self):
        data = {"audio": ("clip.wav", io.BytesIO(_tone_bytes()), "audio/wav")}
        resp = self.client.post("/api/ivr/transcribe", params={}, files=data)
        self.assertEqual(resp.status_code, 422)

    def test_unknown_call_sid_rejected(self):
        resp = self.client.get(
            "/api/ivr/transcribe",
            params={"CallSid": CALL_SID_A, "RecordingUrl": EXOTEL_MP3_URL},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("Unknown CallSid", resp.json()["detail"])

    def test_missing_language_rejected(self):
        store = get_session_store()
        store.get_session(CALL_SID_A)
        resp = self.client.get(
            "/api/ivr/transcribe",
            params={"CallSid": CALL_SID_A, "RecordingUrl": EXOTEL_MP3_URL},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("No language", resp.json()["detail"])

    def test_kn_session_produces_kn_hint(self):
        self._seed(CALL_SID_A, "kn")
        self.assertEqual(resolve_stt_language_hint(CALL_SID_A), "KN")

    def test_hi_session_produces_hi_hint(self):
        self._seed(CALL_SID_A, "hi")
        self.assertEqual(resolve_stt_language_hint(CALL_SID_A), "HI")

    def test_en_session_produces_en_hint(self):
        self._seed(CALL_SID_A, "en")
        self.assertEqual(resolve_stt_language_hint(CALL_SID_A), "EN")

    def test_caller_cannot_override_language_via_query(self):
        self._seed(CALL_SID_A, "kn")

        def hook(data, **kwargs):
            self.assertEqual(kwargs.get("language_hint"), "KN")
            return {
                "success": True,
                "text": "test",
                "detected_language": "KN",
                "confidence": 0.9,
                "low_confidence": False,
                "request_id": "r1",
            }

        stt_service.set_test_transcribe_hook(hook)
        resp = self.client.post(
            "/api/ivr/transcribe",
            params={"CallSid": CALL_SID_A, "language_hint": "EN"},
            files={"audio": ("x.wav", io.BytesIO(_tone_bytes()), "audio/wav")},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["success"])

    def test_missing_audio_handled(self):
        self._seed(CALL_SID_A, "en")
        resp = self.client.get("/api/ivr/transcribe", params={"CallSid": CALL_SID_A})
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json()["success"])

    def test_unsupported_format_rejected(self):
        self._seed(CALL_SID_A, "en")

        def fetch(_url, _timeout):
            return b"not-audio-bytes", "application/octet-stream"

        set_recording_fetch_hook(fetch)
        resp = self.client.get(
            "/api/ivr/transcribe",
            params={"CallSid": CALL_SID_A, "RecordingUrl": EXOTEL_MP3_URL},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json()["success"])

    def test_oversized_audio_rejected(self):
        self._seed(CALL_SID_A, "en")
        huge = _tone_bytes() + (b"\x00" * int(9 * 1024 * 1024))

        def fetch(_url, _timeout):
            return huge, "audio/wav"

        set_recording_fetch_hook(fetch)
        resp = self.client.get(
            "/api/ivr/transcribe",
            params={"CallSid": CALL_SID_A, "RecordingUrl": EXOTEL_MP3_URL},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json()["success"])

    def test_temp_file_deleted_after_success(self):
        self._seed(CALL_SID_A, "en")
        paths: list[str] = []
        import tempfile as tf

        original = tf.mkstemp

        def track(*args, **kwargs):
            fd, path = original(*args, **kwargs)
            paths.append(path)
            return fd, path

        stt_service.set_test_transcribe_hook(
            lambda data, **k: {
                "success": True,
                "text": "hello",
                "detected_language": "EN",
                "confidence": 0.9,
                "low_confidence": False,
                "request_id": "r1",
            }
        )
        with patch("app.services.ivr.exotel_recording.tempfile.mkstemp", side_effect=track):
            set_recording_fetch_hook(lambda u, t: (_tone_bytes(), "audio/wav"))
            transcribe_ivr_audio(CALL_SID_A, recording_url=EXOTEL_MP3_URL)
        self.assertTrue(paths)
        for path in paths:
            self.assertFalse(os.path.exists(path))

    def test_temp_file_deleted_after_failure(self):
        self._seed(CALL_SID_A, "en")
        paths: list[str] = []
        import tempfile as tf

        original = tf.mkstemp

        def track(*args, **kwargs):
            fd, path = original(*args, **kwargs)
            paths.append(path)
            return fd, path

        stt_service.set_test_transcribe_hook(
            lambda data, **k: {
                "success": False,
                "error": "stt_failed",
                "request_id": "r1",
            }
        )
        with patch("app.services.ivr.exotel_recording.tempfile.mkstemp", side_effect=track):
            set_recording_fetch_hook(lambda u, t: (_tone_bytes(), "audio/wav"))
            transcribe_ivr_audio(CALL_SID_A, recording_url=EXOTEL_MP3_URL)
        for path in paths:
            self.assertFalse(os.path.exists(path))

    def test_temp_file_deleted_after_timeout(self):
        self._seed(CALL_SID_A, "en")

        def boom(_url, _timeout):
            raise ValueError("recording_fetch_failed")

        set_recording_fetch_hook(boom)
        transcribe_ivr_audio(CALL_SID_A, recording_url=EXOTEL_MP3_URL)

    def test_valid_exotel_recording_url_accepted(self):
        validate_exotel_recording_url(EXOTEL_MP3_URL)

    def test_localhost_url_rejected(self):
        with self.assertRaises(ValueError):
            validate_exotel_recording_url("https://localhost/rec.mp3")

    def test_private_ip_url_rejected(self):
        with self.assertRaises(ValueError):
            validate_exotel_recording_url("https://192.168.1.10/rec.mp3")

    def test_file_scheme_rejected(self):
        with self.assertRaises(ValueError):
            validate_exotel_recording_url("file:///etc/passwd")

    def test_data_scheme_rejected(self):
        with self.assertRaises(ValueError):
            validate_exotel_recording_url("data:audio/wav;base64,abc")

    def test_arbitrary_external_domain_rejected(self):
        with self.assertRaises(ValueError):
            validate_exotel_recording_url("https://evil.example.com/rec.mp3")

    def test_stt_uses_existing_service_contract(self):
        self._seed(CALL_SID_A, "hi")
        seen: dict = {}

        def hook(data, **kwargs):
            seen["language_hint"] = kwargs.get("language_hint")
            seen["has_bytes"] = bool(data)
            return {
                "success": True,
                "text": "namaste",
                "detected_language": "HI",
                "confidence": 0.8,
                "low_confidence": False,
                "request_id": "r-hook",
            }

        stt_service.set_test_transcribe_hook(hook)
        self.client.post(
            "/api/ivr/transcribe",
            params={"CallSid": CALL_SID_A},
            files={"audio": ("clip.wav", io.BytesIO(_tone_bytes()), "audio/wav")},
        )
        self.assertEqual(seen["language_hint"], "HI")
        self.assertTrue(seen["has_bytes"])

    def test_correct_multipart_field(self):
        self._seed(CALL_SID_A, "en")
        stt_service.set_test_transcribe_hook(
            lambda data, **k: {
                "success": True,
                "text": "ok",
                "detected_language": "EN",
                "confidence": 0.9,
                "low_confidence": False,
                "request_id": "r1",
            }
        )
        resp = self.client.post(
            "/api/ivr/transcribe",
            params={"CallSid": CALL_SID_A},
            files={"audio": ("speech.wav", io.BytesIO(_tone_bytes()), "audio/wav")},
        )
        self.assertEqual(resp.status_code, 200)

    def test_successful_transcription_stored(self):
        self._seed(CALL_SID_A, "en")
        stt_service.set_test_transcribe_hook(
            lambda data, **k: {
                "success": True,
                "text": "What is PM-KISAN?",
                "detected_language": "EN",
                "confidence": 0.95,
                "low_confidence": False,
                "request_id": "r1",
            }
        )
        resp = self.client.post(
            "/api/ivr/transcribe",
            params={"CallSid": CALL_SID_A},
            files={"audio": ("x.wav", io.BytesIO(_tone_bytes()), "audio/wav")},
        )
        self.assertTrue(resp.json()["success"])
        self.assertEqual(get_transcription(CALL_SID_A), "What is PM-KISAN?")
        self.assertNotIn("PM-KISAN", resp.text)

    def test_malformed_200_rejected(self):
        self._seed(CALL_SID_A, "en")
        stt_service.set_test_transcribe_hook(lambda data, **k: {"oops": True})
        outcome = transcribe_ivr_audio(CALL_SID_A, audio_bytes=_tone_bytes())
        self.assertFalse(outcome.response.success)
        self.assertEqual(outcome.failure, IvrSttFailure.MALFORMED_STT_RESPONSE)

    def test_stt_timeout_handled(self):
        self._seed(CALL_SID_A, "en")
        stt_service.set_test_transcribe_hook(
            lambda data, **k: {
                "success": False,
                "error": "stt_busy",
                "request_id": "r1",
            }
        )
        outcome = transcribe_ivr_audio(CALL_SID_A, audio_bytes=_tone_bytes())
        self.assertFalse(outcome.response.success)
        self.assertEqual(outcome.failure, IvrSttFailure.STT_TIMEOUT)

    def test_stt_4xx_handled(self):
        self._seed(CALL_SID_A, "en")
        stt_service.set_test_transcribe_hook(
            lambda data, **k: {
                "success": False,
                "error": "unsupported_audio_format",
                "request_id": "r1",
            }
        )
        outcome = transcribe_ivr_audio(CALL_SID_A, audio_bytes=_tone_bytes())
        self.assertEqual(outcome.failure, IvrSttFailure.UNSUPPORTED_FORMAT)

    def test_stt_5xx_handled(self):
        self._seed(CALL_SID_A, "en")
        stt_service.set_test_transcribe_hook(
            lambda data, **k: {
                "success": False,
                "error": "stt_failed",
                "request_id": "r1",
            }
        )
        outcome = transcribe_ivr_audio(CALL_SID_A, audio_bytes=_tone_bytes())
        self.assertEqual(outcome.failure, IvrSttFailure.STT_SERVER_ERROR)

    def test_empty_transcription_handled(self):
        self._seed(CALL_SID_A, "en")
        stt_service.set_test_transcribe_hook(
            lambda data, **k: {
                "success": True,
                "text": "   ",
                "detected_language": "EN",
                "confidence": 0.5,
                "low_confidence": False,
                "request_id": "r1",
            }
        )
        outcome = transcribe_ivr_audio(CALL_SID_A, audio_bytes=_tone_bytes())
        self.assertEqual(outcome.failure, IvrSttFailure.EMPTY_TRANSCRIPTION)

    def test_low_confidence_preserved(self):
        self._seed(CALL_SID_A, "en")
        stt_service.set_test_transcribe_hook(
            lambda data, **k: {
                "success": True,
                "text": "maybe speech",
                "detected_language": "EN",
                "confidence": 0.1,
                "low_confidence": True,
                "request_id": "r1",
            }
        )
        outcome = transcribe_ivr_audio(CALL_SID_A, audio_bytes=_tone_bytes())
        self.assertTrue(outcome.response.low_confidence)
        self.assertEqual(outcome.failure, IvrSttFailure.LOW_CONFIDENCE)

    def test_transcript_not_logged(self):
        self._seed(CALL_SID_A, "en")
        stt_service.set_test_transcribe_hook(
            lambda data, **k: {
                "success": True,
                "text": "SECRET TRANSCRIPT XYZ",
                "detected_language": "EN",
                "confidence": 0.9,
                "low_confidence": False,
                "request_id": "r1",
            }
        )
        with self.assertLogs("gramsakhi.ivr.stt", level="INFO") as captured:
            transcribe_ivr_audio(CALL_SID_A, audio_bytes=_tone_bytes())
        joined = " ".join(captured.output)
        self.assertNotIn("SECRET TRANSCRIPT", joined)

    def test_audio_not_logged(self):
        self._seed(CALL_SID_A, "en")
        blob = _tone_bytes()
        stt_service.set_test_transcribe_hook(
            lambda data, **k: {
                "success": True,
                "text": "ok",
                "detected_language": "EN",
                "confidence": 0.9,
                "low_confidence": False,
                "request_id": "r1",
            }
        )
        with self.assertLogs("gramsakhi.ivr.stt", level="INFO") as captured:
            transcribe_ivr_audio(CALL_SID_A, audio_bytes=blob)
        joined = " ".join(captured.output)
        self.assertNotIn(blob[:16].hex(), joined)

    def test_credentials_not_returned(self):
        self._seed(CALL_SID_A, "en")
        stt_service.set_test_transcribe_hook(
            lambda data, **k: {
                "success": True,
                "text": "ok",
                "detected_language": "EN",
                "confidence": 0.9,
                "low_confidence": False,
                "request_id": "r1",
            }
        )
        with patch("app.core.config.settings.EXOTEL_API_TOKEN", SECRET):
            resp = self.client.post(
                "/api/ivr/transcribe",
                params={"CallSid": CALL_SID_A},
                files={"audio": ("x.wav", io.BytesIO(_tone_bytes()), "audio/wav")},
            )
        self.assertNotIn(SECRET, resp.text)

    def test_caller_phone_not_returned(self):
        self._seed(CALL_SID_A, "en")
        stt_service.set_test_transcribe_hook(
            lambda data, **k: {
                "success": True,
                "text": "ok",
                "detected_language": "EN",
                "confidence": 0.9,
                "low_confidence": False,
                "request_id": "r1",
            }
        )
        set_recording_fetch_hook(lambda u, t: (_tone_bytes(), "audio/wav"))
        resp = self.client.get(
            "/api/ivr/transcribe",
            params={
                "CallSid": CALL_SID_A,
                "RecordingUrl": EXOTEL_MP3_URL,
                "CallFrom": CALLER,
            },
        )
        self.assertNotIn(CALLER, resp.text)

    def test_call_sid_a_cannot_use_b_language(self):
        self._seed(CALL_SID_A, "kn")
        self._seed(CALL_SID_B, "en")
        seen: list[str] = []

        def hook(data, **kwargs):
            seen.append(kwargs.get("language_hint"))
            return {
                "success": True,
                "text": "ok",
                "detected_language": kwargs.get("language_hint"),
                "confidence": 0.9,
                "low_confidence": False,
                "request_id": "r1",
            }

        stt_service.set_test_transcribe_hook(hook)
        transcribe_ivr_audio(CALL_SID_A, audio_bytes=_tone_bytes())
        transcribe_ivr_audio(CALL_SID_B, audio_bytes=_tone_bytes())
        self.assertEqual(seen, ["KN", "EN"])

    def test_concurrent_sessions_isolated(self):
        self._seed(CALL_SID_A, "hi")
        self._seed(CALL_SID_B, "en")

        def hook(data, language_hint=None, **k):
            return {
                "success": True,
                "text": f"text-{language_hint}",
                "detected_language": language_hint,
                "confidence": 0.9,
                "low_confidence": False,
                "request_id": language_hint or "r",
            }

        stt_service.set_test_transcribe_hook(hook)
        errors: list[Exception] = []

        def run(sid: str) -> None:
            try:
                transcribe_ivr_audio(sid, audio_bytes=_tone_bytes())
            except Exception as exc:
                errors.append(exc)

        t1 = threading.Thread(target=run, args=(CALL_SID_A,))
        t2 = threading.Thread(target=run, args=(CALL_SID_B,))
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        self.assertEqual(errors, [])
        self.assertEqual(get_transcription(CALL_SID_A), "text-HI")
        self.assertEqual(get_transcription(CALL_SID_B), "text-EN")

    def test_validate_stt_service_result_unit(self):
        ok, err = validate_stt_service_result({"success": True, "text": "hi"})
        self.assertTrue(ok)
        self.assertIsNone(err)
        ok, err = validate_stt_service_result("bad")
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
