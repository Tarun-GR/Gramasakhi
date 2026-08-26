"""Phase 6.5 — response language + translation intent tests."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from app.services.language_service import (
    LANG_EN,
    LANG_HI,
    LANG_KN,
    detect_script_language,
    detect_translation_intent,
    resolve_response_language,
)
from app.services.prompt_builder import build_prompt


PM_KISAN_EVIDENCE = [
    {
        "content": (
            "PM-KISAN Samman Nidhi provides financial assistance of Rs 6000 "
            "per year to eligible landholding farmer families."
        ),
        "scheme_name": "PM-KISAN",
        "source": "official government document",
        "page": 2,
    }
]


class TestLanguageDetection(unittest.TestCase):
    def test_kannada_script(self):
        # Screenshot bug query
        q = "PM-KISAN " + "\u0caf\u0ccb\u0c9c\u0ca8\u0cc6\u0caf " + "\u0c85\u0cb0\u0ccd\u0cb9\u0ca4\u0cc6 \u0c8f\u0ca8\u0cc1?"
        self.assertEqual(detect_script_language(q), LANG_KN)

    def test_hindi_script(self):
        q = "\u092a\u0940\u090f\u092e \u0915\u093f\u0938\u093e\u0928 \u092f\u094b\u091c\u0928\u093e \u0915\u094d\u092f\u093e \u0939\u0948?"
        self.assertEqual(detect_script_language(q), LANG_HI)

    def test_english_default(self):
        d = resolve_response_language("What is PM-KISAN eligibility?")
        self.assertEqual(d.response_language, LANG_EN)

    def test_explicit_answer_in_kannada(self):
        d = resolve_response_language("What is PM-KISAN? Answer in Kannada.")
        self.assertEqual(d.response_language, LANG_KN)

    def test_transliteration_kannada(self):
        d = resolve_response_language("PM-KISAN bagge Kannadadalli heli")
        self.assertEqual(d.response_language, LANG_KN)

    def test_mixed_kannada_english(self):
        # "PM-KISAN scheme bagge kannadadalli explain madi"
        kn_bit = "\u0cac\u0c97\u0ccd\u0c97\u0cc6 \u0c95\u0ca8\u0ccd\u0ca8\u0ca1\u0ca6\u0cb2\u0ccd\u0cb2\u0cbf "
        d = resolve_response_language(
            "PM-KISAN scheme " + kn_bit + "explain \u0cae\u0cbe\u0ca1\u0cbf."
        )
        self.assertEqual(d.response_language, LANG_KN)

    def test_stale_en_conversation_does_not_override_kannada_script(self):
        # Gruha Lakshmi eligibility in Kannada script
        q = (
            "\u0c97\u0cc3\u0cb9\u0cb2\u0c95\u0ccd\u0cb7\u0ccd\u0cae\u0cbf "
            "\u0caf\u0ccb\u0c9c\u0ca8\u0cc6\u0caf "
            "\u0c85\u0cb0\u0ccd\u0cb9\u0ca4\u0cc6 \u0c8f\u0ca8\u0cc1?"
        )
        d = resolve_response_language(
            q,
            request_language="en",
            conversation_language="EN",
        )
        self.assertEqual(d.response_language, LANG_KN)
        self.assertEqual(d.reason, "detected_script")

    def test_english_followup_overrides_sticky_kannada_conversation(self):
        """Per-message lexical EN must win over conversation.language=KN."""
        d = resolve_response_language(
            "What documents are needed?",
            conversation_language="KN",
        )
        self.assertEqual(d.response_language, LANG_EN)
        self.assertEqual(d.reason, "lexical_english")

    def test_scheme_name_alone_does_not_force_english(self):
        d = resolve_response_language(
            "PM-KISAN",
            conversation_language="KN",
        )
        self.assertEqual(d.response_language, LANG_KN)

    def test_hindi_explicit(self):
        d = resolve_response_language("What is PM-KISAN? Tell me in Hindi.")
        self.assertEqual(d.response_language, LANG_HI)

    def test_english_override_from_kannada_pref(self):
        d = resolve_response_language(
            "Answer the next one in English. What is PM-KISAN?",
            conversation_language="KN",
        )
        self.assertEqual(d.response_language, LANG_EN)


class TestTranslationIntent(unittest.TestCase):
    def test_translate_above_to_kannada(self):
        is_tr, only, target = detect_translation_intent(
            "Translate the above information to Kannada."
        )
        self.assertTrue(is_tr)
        self.assertTrue(only)
        self.assertEqual(target, LANG_KN)

    def test_translate_to_hindi(self):
        is_tr, only, target = detect_translation_intent("Translate this to Hindi.")
        self.assertTrue(is_tr)
        self.assertTrue(only)
        self.assertEqual(target, LANG_HI)

    def test_kannada_translate_phrase(self):
        # "melina mahitiyannu kannadakke anuvadisi"
        msg = (
            "\u0cae\u0cc7\u0cb2\u0cbf\u0ca8 \u0cae\u0cbe\u0cb9\u0cbf\u0ca4\u0cbf\u0caf\u0ca8\u0ccd\u0ca8\u0cc1 "
            "\u0c95\u0ca8\u0ccd\u0ca8\u0ca1\u0c95\u0ccd\u0c95\u0cc6 "
            "\u0c85\u0ca8\u0cc1\u0cb5\u0cbe\u0ca6\u0cbf\u0cb8\u0cbf."
        )
        is_tr, only, target = detect_translation_intent(msg)
        self.assertTrue(is_tr)
        self.assertTrue(only)
        self.assertEqual(target, LANG_KN)

    def test_scheme_question_in_kannada_is_not_translation_only(self):
        q = "PM-KISAN " + "\u0caf\u0ccb\u0c9c\u0ca8\u0cc6\u0caf " + "\u0c85\u0cb0\u0ccd\u0cb9\u0ca4\u0cc6 \u0c8f\u0ca8\u0cc1?"
        d = resolve_response_language(q)
        self.assertFalse(d.is_translation_only)
        self.assertEqual(d.response_language, LANG_KN)


class TestPromptLanguage(unittest.TestCase):
    def test_screenshot_bug_kannada_prompt(self):
        q = "PM-KISAN " + "\u0caf\u0ccb\u0c9c\u0ca8\u0cc6\u0caf " + "\u0c85\u0cb0\u0ccd\u0cb9\u0ca4\u0cc6 \u0c8f\u0ca8\u0cc1?"
        prompt = build_prompt(q, PM_KISAN_EVIDENCE, response_language="KN")
        self.assertIn("TARGET_RESPONSE_LANGUAGE: KN", prompt)
        self.assertIn("LANGUAGE:\nKannada", prompt)
        self.assertIn("Respond entirely in natural Kannada", prompt)
        self.assertIn("Rs 6000", prompt)

    def test_english_pdf_kannada_response_instruction(self):
        prompt = build_prompt(
            "What are the benefits?",
            PM_KISAN_EVIDENCE,
            response_language="KN",
        )
        self.assertIn("TARGET_RESPONSE_LANGUAGE: KN", prompt)
        self.assertIn("translate the factual content", prompt.lower())


class TestTranslationSkipsRag(unittest.TestCase):
    def test_translation_only_does_not_call_evidence_gate(self):
        from app.services import conversation_service

        db = MagicMock()
        citizen = MagicMock()
        citizen.id = "cit-1"
        conv = MagicMock()
        conv.id = "conv-1"
        conv.language = "EN"
        conv.active_scheme_context = None
        conv.title = "PM-KISAN"
        prev = MagicMock()
        prev.role = "assistant"
        prev.content = "PM-KISAN provides Rs 6000 per year."

        with patch.object(
            conversation_service, "get_owned_conversation", return_value=conv
        ):
            with patch.object(
                conversation_service,
                "load_recent_messages",
                return_value=[prev],
            ):
                with patch.object(
                    conversation_service,
                    "store_message",
                    side_effect=lambda *a, **k: MagicMock(id="m1"),
                ):
                    with patch(
                        "app.services.rag.answer_with_evidence_gate"
                    ) as rag_mock:
                        with patch(
                            "app.services.llm_service.translate_answer",
                            return_value={
                                "success": True,
                                "answer": "kannada answer marker",
                                "model": "llama3.2:3b",
                                "response_language": "KN",
                                "latency_ms": 10,
                            },
                        ) as tr_mock:
                            out = conversation_service.handle_citizen_chat(
                                db,
                                citizen,
                                message="Translate the above information to Kannada.",
                                conversation_id="conv-1",
                            )
        rag_mock.assert_not_called()
        tr_mock.assert_called_once()
        self.assertEqual(out["response_language"], "KN")
        self.assertEqual(out["knowledge_source"], "translation")
        self.assertEqual(out["answer"], "kannada answer marker")


if __name__ == "__main__":
    unittest.main()
