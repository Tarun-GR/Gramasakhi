"""IVR-A1 — inbound call language selection (Exotel Gather)."""

from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.schemas.ivr import IvrGatherResponse
from app.services.ivr.constants import MAX_RETRY_ATTEMPTS, MENU_PROMPT
from app.services.ivr.language_flow import mask_caller_phone, normalize_digits
from app.services.ivr.language_session import (
    clear_session,
    get_language,
    get_session_store,
    reset_session_store,
    set_language,
)

CALL_SID_A = "CA11111111111111111111111111111111"
CALL_SID_B = "CA22222222222222222222222222222222"
CALLER = "+919876543210"
SECRET_MARKER = "gramsakhi_very_secret_key_change_me_in_production"


class TestIvrA1(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def setUp(self):
        reset_session_store()

    def _get(self, **params):
        return self.client.get("/api/ivr/language", params=params)

    def test_missing_call_sid_rejected(self):
        resp = self._get(digits="1")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("CallSid", resp.json()["detail"])

    def test_blank_call_sid_rejected(self):
        resp = self._get(CallSid="   ", digits="1")
        self.assertEqual(resp.status_code, 400)

    def test_valid_kannada_digit(self):
        resp = self._get(CallSid=CALL_SID_A, digits="1")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIn("Kannada selected", body["gather_prompt"]["text"])
        self.assertEqual(get_language(CALL_SID_A), "kn")

    def test_valid_hindi_digit(self):
        resp = self._get(CallSid=CALL_SID_A, digits="2")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Hindi selected", resp.json()["gather_prompt"]["text"])
        self.assertEqual(get_language(CALL_SID_A), "hi")

    def test_valid_english_digit(self):
        resp = self._get(CallSid=CALL_SID_A, digits="3")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("English selected", resp.json()["gather_prompt"]["text"])
        self.assertEqual(get_language(CALL_SID_A), "en")

    def test_invalid_digit_handled(self):
        resp = self._get(CallSid=CALL_SID_A, digits="4")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Invalid choice", resp.json()["gather_prompt"]["text"])
        self.assertIsNone(get_language(CALL_SID_A))

    def test_empty_digit_returns_menu(self):
        resp = self._get(CallSid=CALL_SID_A, digits="")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["gather_prompt"]["text"], MENU_PROMPT)

    def test_quoted_digits_normalized(self):
        resp = self._get(CallSid=CALL_SID_A, digits='"2"')
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Hindi selected", resp.json()["gather_prompt"]["text"])
        self.assertEqual(get_language(CALL_SID_A), "hi")

    def test_language_stored_by_call_sid(self):
        self._get(CallSid=CALL_SID_A, digits="1")
        self.assertEqual(get_language(CALL_SID_A), "kn")

    def test_different_call_sids_isolated(self):
        self._get(CallSid=CALL_SID_A, digits="1")
        self._get(CallSid=CALL_SID_B, digits="3")
        self.assertEqual(get_language(CALL_SID_A), "kn")
        self.assertEqual(get_language(CALL_SID_B), "en")

    def test_same_call_sid_can_be_updated(self):
        self._get(CallSid=CALL_SID_A, digits="1")
        self.assertEqual(get_language(CALL_SID_A), "kn")
        self._get(CallSid=CALL_SID_A, digits="2")
        self.assertEqual(get_language(CALL_SID_A), "hi")

    def test_session_can_be_cleared(self):
        self._get(CallSid=CALL_SID_A, digits="3")
        self.assertEqual(get_language(CALL_SID_A), "en")
        clear_session(CALL_SID_A)
        self.assertIsNone(get_language(CALL_SID_A))

    def test_caller_phone_not_in_response(self):
        resp = self._get(CallSid=CALL_SID_A, CallFrom=CALLER, digits="1")
        self.assertEqual(resp.status_code, 200)
        payload = json.dumps(resp.json())
        self.assertNotIn(CALLER, payload)
        self.assertNotIn("9876543210", payload)

    def test_secrets_not_in_response(self):
        with patch("app.core.config.settings.EXOTEL_API_TOKEN", SECRET_MARKER):
            resp = self._get(CallSid=CALL_SID_A, digits="1")
        self.assertEqual(resp.status_code, 200)
        payload = json.dumps(resp.json())
        self.assertNotIn(SECRET_MARKER, payload)

    def test_gather_response_schema_valid(self):
        resp = self._get(CallSid=CALL_SID_A)
        self.assertEqual(resp.status_code, 200)
        parsed = IvrGatherResponse.model_validate(resp.json())
        self.assertEqual(parsed.gather_prompt.text, MENU_PROMPT)
        self.assertEqual(parsed.max_input_digits, 1)

    def test_retry_count_bounded_invalid_digit(self):
        sid = CALL_SID_A
        for _ in range(MAX_RETRY_ATTEMPTS):
            resp = self._get(CallSid=sid, digits="9")
            self.assertIn("Invalid choice", resp.json()["gather_prompt"]["text"])
        final = self._get(CallSid=sid, digits="0")
        self.assertIn("Goodbye", final.json()["gather_prompt"]["text"])

    def test_missing_digits_returns_menu(self):
        resp = self._get(CallSid=CALL_SID_A)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["gather_prompt"]["text"], MENU_PROMPT)
        self.assertIn("repeat_gather_prompt", resp.json())

    def test_no_input_retry_bounded(self):
        sid = CALL_SID_A
        first = self._get(CallSid=sid)
        self.assertEqual(first.json()["gather_prompt"]["text"], MENU_PROMPT)
        for _ in range(MAX_RETRY_ATTEMPTS):
            resp = self._get(CallSid=sid, digits="")
            self.assertEqual(resp.status_code, 200)
        final = self._get(CallSid=sid, digits="")
        self.assertIn("Goodbye", final.json()["gather_prompt"]["text"])

    def test_unsupported_language_cannot_enter_session(self):
        with self.assertRaises(ValueError):
            set_language(CALL_SID_A, "fr")
        self.assertIsNone(get_language(CALL_SID_A))

    def test_normalize_digits_unit(self):
        self.assertIsNone(normalize_digits(None))
        self.assertIsNone(normalize_digits(""))
        self.assertIsNone(normalize_digits('  ""  '))
        self.assertEqual(normalize_digits('"1"'), "1")
        self.assertEqual(normalize_digits("'3'"), "3")

    def test_mask_caller_phone_unit(self):
        masked = mask_caller_phone(CALLER)
        self.assertNotIn("9876543210", masked)
        self.assertTrue(masked.endswith("210") or masked.endswith("051") or masked.endswith("210"))


if __name__ == "__main__":
    unittest.main()
