"""Unified per-message language switching matrix (same conversation_id semantics)."""

from __future__ import annotations

import unittest

from app.services.language_service import (
    LANG_EN,
    LANG_HI,
    LANG_KN,
    controlled_language_failure_message,
    resolve_response_language,
)


class TestLanguageSwitchingMatrix(unittest.TestCase):
    def _turn(self, msg: str, *, prev: str | None = None, stt: str | None = None):
        return resolve_response_language(
            msg,
            conversation_language=prev,
            previous_response_language=prev,
            stt_language=stt,
        )

    def test_en_to_kn(self):
        d1 = self._turn("What are the benefits of PM-KISAN?")
        self.assertEqual(d1.response_language, LANG_EN)
        d2 = self._turn(
            "PM-KISAN \u0caf\u0ccb\u0c9c\u0ca8\u0cc6\u0caf \u0c85\u0cb0\u0ccd\u0cb9\u0ca4\u0cc6 \u0c8f\u0ca8\u0cc1?",
            prev=d1.response_language,
        )
        self.assertEqual(d2.response_language, LANG_KN)

    def test_kn_to_hi(self):
        d1 = self._turn(
            "PM-KISAN \u0caf\u0ccb\u0c9c\u0ca8\u0cc6 \u0c8f\u0ca8\u0cc1?",
        )
        self.assertEqual(d1.response_language, LANG_KN)
        d2 = self._turn(
            "\u0907\u0938\u0915\u0947 \u0932\u093f\u090f \u0915\u094c\u0928 \u092a\u093e\u0924\u094d\u0930 \u0939\u0948?",
            prev=d1.response_language,
        )
        self.assertEqual(d2.response_language, LANG_HI)

    def test_hi_to_en(self):
        d1 = self._turn("\u092a\u0940\u090f\u092e-\u0915\u093f\u0938\u093e\u0928 \u0915\u094d\u092f\u093e \u0939\u0948?")
        self.assertEqual(d1.response_language, LANG_HI)
        d2 = self._turn("What documents are required?", prev=d1.response_language)
        self.assertEqual(d2.response_language, LANG_EN)

    def test_en_to_hi(self):
        d1 = self._turn("Tell me about PM-KISAN.")
        d2 = self._turn(
            "\u0907\u0938\u0915\u0947 \u0932\u093e\u092d \u0915\u094d\u092f\u093e \u0939\u0948\u0902?",
            prev=d1.response_language,
        )
        self.assertEqual(d2.response_language, LANG_HI)

    def test_kn_to_en(self):
        d1 = self._turn("PM-KISAN \u0caf\u0ccb\u0c9c\u0ca8\u0cc6 \u0c8f\u0ca8\u0cc1?")
        d2 = self._turn("What are the benefits?", prev=d1.response_language)
        self.assertEqual(d2.response_language, LANG_EN)

    def test_full_cycle_same_conversation(self):
        prev = None
        sequence = [
            ("What are the benefits of PM-KISAN?", LANG_EN),
            ("PM-KISAN \u0caf\u0ccb\u0c9c\u0ca8\u0cc6\u0caf \u0c85\u0cb0\u0ccd\u0cb9\u0ca4\u0cc6 \u0c8f\u0ca8\u0cc1?", LANG_KN),
            ("\u0907\u0938\u0915\u0947 \u0932\u093f\u090f \u0915\u094c\u0928 \u092a\u093e\u0924\u094d\u0930 \u0939\u0948?", LANG_HI),
            ("What documents are required?", LANG_EN),
        ]
        for msg, expect in sequence:
            d = self._turn(msg, prev=prev)
            self.assertEqual(d.response_language, expect, msg)
            prev = d.response_language

    def test_voice_stt_does_not_override_kannada_script(self):
        d = self._turn(
            "PM-KISAN \u0caf\u0ccb\u0c9c\u0ca8\u0cc6 \u0c8f\u0ca8\u0cc1?",
            stt="EN",
            prev="EN",
        )
        self.assertEqual(d.response_language, LANG_KN)

    def test_voice_english_lexical_beats_wrong_stt_kn(self):
        d = self._turn(
            "What is PM-KISAN eligibility?",
            stt="KN",
            prev="KN",
        )
        self.assertEqual(d.response_language, LANG_EN)

    def test_mixed_kannada_primary(self):
        d = self._turn(
            "PM-KISAN \u0caf\u0ccb\u0c9c\u0ca8\u0cc6\u0c97\u0cc6 eligibility \u0c8f\u0ca8\u0cc1?",
            prev="EN",
        )
        self.assertEqual(d.response_language, LANG_KN)

    def test_explicit_overrides_script(self):
        d = self._turn(
            "PM-KISAN \u0caf\u0ccb\u0c9c\u0ca8\u0cc6. Answer in English.",
            prev="KN",
        )
        self.assertEqual(d.response_language, LANG_EN)


class TestFallbackLanguageSafety(unittest.TestCase):
    def test_kannada_fallback_is_kannada(self):
        msg = controlled_language_failure_message("KN", kind="generation")
        kn = sum(1 for ch in msg if "\u0c80" <= ch <= "\u0cff")
        self.assertGreater(kn, 10)
        self.assertNotIn("Kannada generation failed", msg)

    def test_hindi_fallback_is_hindi(self):
        msg = controlled_language_failure_message("HI", kind="generation")
        hi = sum(1 for ch in msg if "\u0900" <= ch <= "\u097f")
        self.assertGreater(hi, 10)

    def test_english_fallback(self):
        msg = controlled_language_failure_message("EN", kind="generation")
        self.assertIn("try again", msg.lower())


if __name__ == "__main__":
    unittest.main()
