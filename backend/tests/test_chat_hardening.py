"""Chat experience hardening — language, transliteration, rewrite, STT cues."""

from __future__ import annotations

import unittest

from app.core.config import settings
from app.services.language_service import (
    LANG_EN,
    LANG_HI,
    LANG_KN,
    detect_lexical_language,
    resolve_response_language,
)
from app.services.multilingual_retrieval_service import normalize_transcript
from app.services.query_rewriter import rewrite_query
from app.services.voice import stt_service


class TestPerMessageLanguage(unittest.TestCase):
    def test_matrix_pairs(self):
        cases = [
            ("What is PM-KISAN?", None, LANG_EN),
            ("ಪಿಎಂ ಕಿಸಾನ್ ಯೋಜನೆ ಎಂದರೇನು?", LANG_EN, LANG_KN),
            ("पीएम किसान योजना क्या है?", LANG_KN, LANG_HI),
            ("What is PM-KISAN?", LANG_HI, LANG_EN),
            ("Tell me that in English.", LANG_KN, LANG_EN),
            ("Explain PM-KISAN in Kannada.", LANG_EN, LANG_KN),
            ("अब इसे हिंदी में बताइए।", LANG_EN, LANG_HI),
        ]
        for msg, prev, expect in cases:
            d = resolve_response_language(
                msg,
                conversation_language=prev,
                previous_response_language=prev,
            )
            self.assertEqual(d.response_language, expect, msg)

    def test_full_switch_cycle(self):
        prev = None
        sequence = [
            ("What is PM-KISAN?", LANG_EN),
            ("ಶಕ್ತಿ ಯೋಜನೆಗೆ ಯಾರು ಅರ್ಹರು?", LANG_KN),
            ("पीएम किसान के लिए कौन पात्र है?", LANG_HI),
            ("Tell me that in English.", LANG_EN),
            ("ಈ ಯೋಜನೆಯ ಬಗ್ಗೆ ಇನ್ನಷ್ಟು ಹೇಳಿ", LANG_KN),
        ]
        for msg, expect in sequence:
            d = resolve_response_language(
                msg,
                conversation_language=prev,
                previous_response_language=prev,
            )
            self.assertEqual(d.response_language, expect, msg)
            prev = d.response_language


class TestTransliterationLanguage(unittest.TestCase):
    def test_kannada_latin_not_english(self):
        samples = [
            "Shakti yojaneke yaaru arhru?",
            "Shakti yojanage yaru arharu",
            "pm kisan yojane yenu?",
            "shakti yojane bagge heli",
            "Guruha Jyoti mahiti kodi",
        ]
        for s in samples:
            self.assertEqual(detect_lexical_language(s), LANG_KN, s)
            d = resolve_response_language(s, conversation_language=LANG_EN, stt_language="EN")
            self.assertEqual(d.response_language, LANG_KN, s)

    def test_hindi_latin_not_english(self):
        samples = [
            "pm kisan ke liye kaun patra hai",
            "shakti yojana ke bare mein batao",
            "iske liye kaun patra hai",
        ]
        for s in samples:
            self.assertEqual(detect_lexical_language(s), LANG_HI, s)
            d = resolve_response_language(s, conversation_language=LANG_EN, stt_language="EN")
            self.assertEqual(d.response_language, LANG_HI, s)

    def test_english_question_still_english(self):
        d = resolve_response_language(
            "What is the Shakti scheme eligibility?",
            conversation_language=LANG_KN,
            stt_language="KN",
        )
        self.assertEqual(d.response_language, LANG_EN)

    def test_mahiti_not_stripped_to_english_before_detect(self):
        orig, norm = normalize_transcript("Shakti mahiti kodi")
        self.assertIn("mahiti", orig.lower())
        self.assertIn("mahiti", norm.lower())
        self.assertNotIn("information", norm.lower())
        self.assertEqual(
            stt_service.resolve_transcript_language(orig, "en"),
            "KN",
        )


class TestQueryRewriteTopicShift(unittest.TestCase):
    def setUp(self):
        settings.QUERY_REWRITE_USE_OLLAMA = False

    def test_new_topic_without_scheme_does_not_inherit_pm_kisan(self):
        history = [{"role": "user", "content": "Tell me about PM-KISAN."}]
        out = rewrite_query("Tell me about farming subsidies in Karnataka", history)
        self.assertNotIn("PM-KISAN", out["rewritten_query"])
        self.assertFalse(out["was_rewritten"])

    def test_shakti_topic_shift_from_pm_kisan(self):
        history = [{"role": "user", "content": "What is PM-KISAN?"}]
        out = rewrite_query("ಶಕ್ತಿ ಯೋಜನೆ ಬಗ್ಗೆ ಹೇಳಿ", history)
        self.assertNotIn("PM-KISAN", out["rewritten_query"])

    def test_followup_still_inherits_scheme(self):
        history = [{"role": "user", "content": "Tell me about Shakti."}]
        out = rewrite_query("Who is eligible?", history)
        self.assertIn("Shakti", out["rewritten_query"])
        self.assertTrue(out["was_rewritten"])

    def test_kannada_followup_inherits_active_scheme(self):
        history = [
            {"role": "user", "content": "Tell me about Shakti."},
            {"role": "assistant", "content": "Shakti is a Karnataka scheme."},
        ]
        out = rewrite_query("ಅದಕ್ಕೆ ಯಾರು ಅರ್ಹರು?", history)
        self.assertIn("Shakti", out["rewritten_query"])


class TestSttLanguageHardening(unittest.TestCase):
    def test_whisper_en_latin_kannada(self):
        lang = stt_service.resolve_transcript_language(
            "Shakti yojaneke yaaru arhru",
            "en",
        )
        self.assertEqual(lang, "KN")

    def test_whisper_en_latin_hindi(self):
        lang = stt_service.resolve_transcript_language(
            "pm kisan ke liye kaun patra hai",
            "en",
        )
        self.assertEqual(lang, "HI")

    def test_script_still_overrides(self):
        lang = stt_service.resolve_transcript_language(
            "ಶಕ್ತಿ ಯೋಜನೆಗೆ ಯಾರು ಅರ್ಹರು?",
            "en",
        )
        self.assertEqual(lang, "KN")


if __name__ == "__main__":
    unittest.main()
