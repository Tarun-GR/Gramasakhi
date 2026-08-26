"""Language metadata contract for future STT/TTS — text layer only."""

from __future__ import annotations

import unittest

from app.services.language_service import (
    LANG_EN,
    LANG_HI,
    LANG_KN,
    OP_ANSWER_IN_LANGUAGE,
    OP_NEW_INFORMATION,
    OP_TRANSLATION,
    detect_strict_language_mode,
    language_metadata,
    resolve_response_language,
)
from app.services.prompt_builder import build_prompt


class TestLanguagePriority(unittest.TestCase):
    def test_rewritten_english_must_not_override_kn_script(self):
        original = "PM-KISAN \u0caf\u0ccb\u0c9c\u0ca8\u0cc6\u0caf \u0c85\u0cb0\u0ccd\u0cb9\u0ca4\u0cc6 \u0c8f\u0ca8\u0cc1?"
        # Simulate mistaken use of rewritten query — contract requires original
        d_orig = resolve_response_language(original, conversation_language="EN")
        d_rewritten = resolve_response_language(
            "PM-KISAN eligibility requirements", conversation_language="EN"
        )
        self.assertEqual(d_orig.response_language, LANG_KN)
        self.assertEqual(d_rewritten.response_language, LANG_EN)

    def test_explicit_beats_detected(self):
        d = resolve_response_language(
            "\u0caf\u0ccb\u0c9c\u0ca8\u0cc6 \u0c8f\u0ca8\u0cc1? Answer in English."
        )
        self.assertEqual(d.response_language, LANG_EN)
        self.assertEqual(d.operation, OP_ANSWER_IN_LANGUAGE)

    def test_detected_beats_api_en(self):
        d = resolve_response_language(
            "\u0c97\u0cc3\u0cb9\u0cb2\u0c95\u0ccd\u0cb7\u0ccd\u0cae\u0cbf \u0c85\u0cb0\u0ccd\u0cb9\u0ca4\u0cc6?",
            request_language="en",
        )
        self.assertEqual(d.response_language, LANG_KN)
        self.assertEqual(d.reason, "detected_script")

    def test_conversation_for_english_followup(self):
        d = resolve_response_language(
            "What documents are needed?", conversation_language="KN"
        )
        # Per-message English lexical evidence must not stay locked to KN
        self.assertEqual(d.response_language, LANG_EN)
        self.assertEqual(d.operation, OP_NEW_INFORMATION)

    def test_transliteration_variants(self):
        for msg in (
            "Kannadadalli heli",
            "Kannada dalli answer kodi",
            "Kannadakke translate madi",
            "kannadadalli answer kodi",
        ):
            d = resolve_response_language(msg)
            self.assertEqual(d.response_language, LANG_KN, msg)

    def test_mixed_language_stays_kn(self):
        d = resolve_response_language(
            "PM-KISAN beneficiary status \u0cb9\u0cc7\u0c97\u0cc6 check \u0cae\u0cbe\u0ca1\u0cc1\u0cb5\u0cc1\u0ca6\u0cc1?"
        )
        self.assertEqual(d.response_language, LANG_KN)

    def test_hindi_script(self):
        d = resolve_response_language(
            "\u092a\u0940\u090f\u092e \u0915\u093f\u0938\u093e\u0928 \u092f\u094b\u091c\u0928\u093e \u0915\u094d\u092f\u093e \u0939\u0948?"
        )
        self.assertEqual(d.response_language, LANG_HI)

    def test_strict_mode(self):
        self.assertTrue(detect_strict_language_mode("Answer only in Kannada"))
        d = resolve_response_language("Answer only in Kannada about PM-KISAN")
        self.assertTrue(d.strict_language_mode)


class TestMetadataContract(unittest.TestCase):
    def test_metadata_fields_for_future_tts(self):
        d = resolve_response_language(
            "PM-KISAN \u0caf\u0ccb\u0c9c\u0ca8\u0cc6 \u0c8f\u0ca8\u0cc1?"
        )
        meta = language_metadata(d)
        for key in (
            "detected_language",
            "response_language",
            "target_language",
            "is_translation_request",
            "is_translation_only",
            "strict_language_mode",
            "language_operation",
        ):
            self.assertIn(key, meta)
        self.assertEqual(meta["response_language"], LANG_KN)
        # No English-audio hardcoding keys
        self.assertNotIn("tts_language", meta)
        self.assertNotIn("force_english_audio", meta)

    def test_translation_operation(self):
        d = resolve_response_language("Translate this to Hindi.")
        self.assertEqual(d.operation, OP_TRANSLATION)
        self.assertEqual(d.target_language, LANG_HI)


class TestPromptContract(unittest.TestCase):
    def test_prompt_has_hard_kn_contract(self):
        prompt = build_prompt(
            "Who is eligible?",
            [{"content": "Rs 6000 per year", "scheme_name": "PM-KISAN"}],
            response_language="KN",
            strict_language_mode=True,
        )
        self.assertIn("TARGET_RESPONSE_LANGUAGE: KN", prompt)
        self.assertIn("TARGET_LANGUAGE_NAME: Kannada", prompt)
        self.assertIn("STRICT LANGUAGE MODE", prompt)
        self.assertIn("English technical or official terms may be retained", prompt)


if __name__ == "__main__":
    unittest.main()
