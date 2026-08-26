"""Translation-only quality + no-RAG contract tests."""

from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock, patch

from app.services import llm_service
from app.services.language_quality import validate_answer_quality
from app.services.language_service import (
    OP_TRANSLATION,
    detect_translation_intent,
    resolve_response_language,
)
from tests.fixtures.kannada_quality_corpus import (
    GOOD_KN_ANSWER_6000,
    translation_pair_templates,
)


class TestTranslationIntentCorpus(unittest.TestCase):
    def test_hundred_translation_templates(self):
        pairs = translation_pair_templates(100)
        self.assertGreaterEqual(len(pairs), 100)
        for p in pairs:
            self.assertEqual(p["target_language"], "KN")
            self.assertTrue(p["source_en"].strip())

    def test_translate_above_is_translation_only(self):
        is_tr, only, target = detect_translation_intent(
            "Translate the above information to Kannada."
        )
        self.assertTrue(is_tr)
        self.assertTrue(only)
        self.assertEqual(target, "KN")
        d = resolve_response_language("Translate the above information to Kannada.")
        self.assertEqual(d.operation, OP_TRANSLATION)
        self.assertTrue(d.is_translation_only)


class TestTranslationQualityGate(unittest.TestCase):
    def test_faithful_translation_passes(self):
        source = (
            "PM-KISAN provides financial assistance of Rs 6000 per year in 3 installments. "
            "Apply at https://pmkisan.gov.in/"
        )
        ans = GOOD_KN_ANSWER_6000 + " https://pmkisan.gov.in/"
        r = validate_answer_quality(
            ans,
            response_language="KN",
            source_text=source,
            mode="translation",
        )
        self.assertTrue(r.passed, r.failures)

    def test_translation_amount_drift_fails(self):
        source = "PM-KISAN provides Rs 6000 per year."
        ans = (
            "PM-KISAN \u0caf\u0ccb\u0c9c\u0ca8\u0cc6\u0caf\u0cb2\u0ccd\u0cb2\u0cbf "
            "Rs 12000 \u0cb8\u0cbf\u0c97\u0cc1\u0ca4\u0ccd\u0ca4\u0ca6\u0cc6."
        )
        r = validate_answer_quality(
            ans, response_language="KN", source_text=source, mode="translation"
        )
        self.assertFalse(r.passed)

    def test_translation_prompt_rules(self):
        from app.services.language_service import build_translation_prompt

        p = build_translation_prompt("Hello Rs 6000", target_language="KN")
        self.assertIn("Do not add facts", p)
        self.assertIn("Do not summarize", p)
        self.assertIn("Do not reinterpret", p)
        self.assertIn("natural Kannada", p)


class TestTranslationSkipsRagAndLive(unittest.TestCase):
    def test_no_rag_no_live_on_translate(self):
        from app.services import conversation_service

        db = MagicMock()
        citizen = MagicMock()
        citizen.id = "cit-a"
        conv = MagicMock()
        conv.id = "conv-a"
        conv.language = "EN"
        conv.active_scheme_context = None
        conv.title = "t"
        prev = MagicMock()
        prev.role = "assistant"
        prev.content = "PM-KISAN provides Rs 6000 per year. https://pmkisan.gov.in/"

        with patch.object(conversation_service, "get_owned_conversation", return_value=conv):
            with patch.object(
                conversation_service, "load_recent_messages", return_value=[prev]
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
                            "app.services.live_gov_retrieval_service.try_live_gov_fallback"
                        ) as live_mock:
                            with patch(
                                "app.services.llm_service.translate_answer",
                                return_value={
                                    "success": True,
                                    "answer": GOOD_KN_ANSWER_6000
                                    + " https://pmkisan.gov.in/",
                                    "model": "llama3.2:3b",
                                    "response_language": "KN",
                                    "latency_ms": 5,
                                },
                            ):
                                out = conversation_service.handle_citizen_chat(
                                    db,
                                    citizen,
                                    message="Translate the above information to Kannada.",
                                    conversation_id="conv-a",
                                )
        rag_mock.assert_not_called()
        live_mock.assert_not_called()
        self.assertEqual(out["knowledge_source"], "translation")
        self.assertEqual(out["response_language"], "KN")

    def test_second_user_cannot_translate_other_conversation(self):
        from fastapi import HTTPException
        from app.services import conversation_service

        db = MagicMock()
        citizen_b = MagicMock()
        citizen_b.id = "cit-b"

        with patch.object(
            conversation_service,
            "get_owned_conversation",
            side_effect=HTTPException(status_code=404, detail="not found"),
        ):
            with self.assertRaises(HTTPException) as ctx:
                conversation_service.handle_citizen_chat(
                    db,
                    citizen_b,
                    message="Translate the above information to Kannada.",
                    conversation_id="conv-owned-by-a",
                )
        self.assertEqual(ctx.exception.status_code, 404)


class TestTranslateAnswerGate(unittest.TestCase):
    def test_translate_answer_rejects_english_output(self):
        def fake(req, timeout=None):
            body = json.dumps(
                {"response": "PM-KISAN provides Rs 6000 per year."}
            ).encode("utf-8")

            class Resp:
                def read(self):
                    return body

                def __enter__(self):
                    return self

                def __exit__(self, *a):
                    return False

            return Resp()

        # Clear cache
        from app.services import language_quality

        language_quality._TRANSLATION_CACHE.clear()

        with patch.object(llm_service.urllib.request, "urlopen", side_effect=fake):
            with patch.object(llm_service.settings, "LANGUAGE_QUALITY_GATE_ENABLED", True):
                with patch.object(llm_service.settings, "MAX_LANGUAGE_REGEN_ATTEMPTS", 0):
                    result = llm_service.translate_answer(
                        "PM-KISAN provides Rs 6000 per year.",
                        target_language="KN",
                    )
        self.assertFalse(result["success"])
        self.assertEqual(result.get("error"), "translation_quality_failed")


if __name__ == "__main__":
    unittest.main()
