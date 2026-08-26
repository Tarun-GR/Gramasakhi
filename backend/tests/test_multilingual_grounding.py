"""Cross-language grounding: English PDF evidence -> Kannada answer path."""

from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock, patch

from app.services import llm_service
from app.services.language_quality import validate_answer_quality
from app.services.language_service import resolve_response_language
from app.services.prompt_builder import build_prompt
from tests.fixtures.kannada_quality_corpus import (
    EVIDENCE_PMKISAN,
    GOOD_KN_ANSWER_6000,
)


class TestEnglishPdfToKannada(unittest.TestCase):
    def test_prompt_keeps_english_evidence_asks_kannada(self):
        q = "\u0c88 \u0caf\u0ccb\u0c9c\u0ca8\u0cc6\u0caf\u0ca1\u0cbf \u0c8e\u0cb7\u0ccd\u0c9f\u0cc1 \u0cb9\u0ca3 \u0cb8\u0cbf\u0c97\u0cc1\u0ca4\u0ccd\u0ca4\u0ca6\u0cc6?"
        prompt = build_prompt(q, EVIDENCE_PMKISAN, response_language="KN")
        self.assertIn("Rs 6000", prompt)
        self.assertIn("TARGET_RESPONSE_LANGUAGE: KN", prompt)
        self.assertIn("Translate the factual content into Kannada", prompt)
        # Must not instruct storing a Kannada PDF
        self.assertNotIn("translate the PDF", prompt.lower())

    def test_grounded_kannada_preserves_6000(self):
        r = validate_answer_quality(
            GOOD_KN_ANSWER_6000 + " https://pmkisan.gov.in/",
            response_language="KN",
            evidence=EVIDENCE_PMKISAN,
            mode="generation",
        )
        self.assertTrue(r.passed, r.failures)
        self.assertEqual(r.scores.get("numeric_score"), 100.0)

    def test_generate_with_english_evidence_kannada_output(self):
        kn = GOOD_KN_ANSWER_6000 + " https://pmkisan.gov.in/"

        def fake(req, timeout=None):
            body = json.dumps({"response": kn}).encode("utf-8")

            class Resp:
                def read(self):
                    return body

                def __enter__(self):
                    return self

                def __exit__(self, *a):
                    return False

            return Resp()

        with patch.object(llm_service.urllib.request, "urlopen", side_effect=fake):
            result = llm_service.generate_answer(
                "\u0c8e\u0cb7\u0ccd\u0c9f\u0cc1 \u0cb9\u0ca3?",
                EVIDENCE_PMKISAN,
                response_language="KN",
            )
        self.assertTrue(result["success"])
        self.assertEqual(result["response_language"], "KN")
        self.assertIn("6000", result["answer"])


class TestLiveGovernmentKannadaPath(unittest.TestCase):
    def test_kannada_question_still_enables_live_fallback_flag(self):
        """Indexed FAIL should still call live; response_language stays KN."""
        from app.services import rag as rag_service
        from app.services.evidence_validator import ValidationResult

        db = MagicMock()
        q_rewrite = "PM-KISAN eligibility requirements"
        fail = ValidationResult(
            ok=False,
            confidence="low",
            reason="low_coverage",
            signals={"coverage": 0.1},
            evidence=[],
        )
        pass_result = ValidationResult(
            ok=True,
            confidence="high",
            reason="ok",
            signals={"coverage": 0.9},
            evidence=EVIDENCE_PMKISAN,
        )

        class FakeValidator:
            def __init__(self):
                self.calls = 0

            def validate(self, query, docs):
                self.calls += 1
                if self.calls == 1 and not docs:
                    return fail
                if self.calls <= 2 and (not docs or len(docs) < 1):
                    return fail
                return pass_result if docs else fail

        v = FakeValidator()
        kn_answer = GOOD_KN_ANSWER_6000 + " https://pmkisan.gov.in/"

        calls = {"n": 0}

        def fake_hybrid(db, query, **kwargs):
            calls["n"] += 1
            return [] if calls["n"] == 1 else EVIDENCE_PMKISAN

        with patch.object(rag_service.settings, "LIVE_GOV_FALLBACK_ENABLED", True):
            with patch.object(rag_service, "hybrid_retrieve", side_effect=fake_hybrid):
                with patch(
                    "app.services.live_gov_retrieval_service.try_live_gov_fallback",
                    return_value={
                        "ingested": [{"url": "https://pmkisan.gov.in/doc.pdf"}],
                        "latency_ms": 10,
                        "live_request_id": "t1",
                        "evidence_ready": True,
                        "accepted_url": "https://pmkisan.gov.in/doc.pdf",
                        "index_stats": {},
                        "failure_codes": [],
                        "candidates_tried": 1,
                    },
                ) as live_mock:
                    with patch.object(
                        rag_service,
                        "_call_llm_after_validation",
                        return_value={
                            "success": True,
                            "answer": kn_answer,
                            "model": "llama3.2:3b",
                            "response_language": "KN",
                            "latency_ms": 1,
                        },
                    ):
                        out = rag_service.answer_with_evidence_gate(
                            db,
                            q_rewrite,
                            validator=v,
                            enable_live_fallback=True,
                            response_language="KN",
                        )
        live_mock.assert_called_once()
        self.assertEqual(out.get("response_language") or "KN", "KN")
        self.assertEqual(out.get("knowledge_source"), "live_government")
        self.assertIn("6000", out.get("answer") or "")

    def test_translation_after_live_does_not_call_live_again(self):
        from app.services import conversation_service

        db = MagicMock()
        citizen = MagicMock()
        citizen.id = "c1"
        conv = MagicMock()
        conv.id = "conv1"
        conv.language = "EN"
        conv.active_scheme_context = "PM-KISAN"
        conv.title = "PM-KISAN"
        prev = MagicMock()
        prev.role = "assistant"
        prev.content = (
            "PM-KISAN provides Rs 6000 per year. Source: live government. "
            "https://pmkisan.gov.in/"
        )

        with patch.object(conversation_service, "get_owned_conversation", return_value=conv):
            with patch.object(
                conversation_service, "load_recent_messages", return_value=[prev]
            ):
                with patch.object(
                    conversation_service,
                    "store_message",
                    side_effect=lambda *a, **k: MagicMock(id="m"),
                ):
                    with patch(
                        "app.services.live_gov_retrieval_service.try_live_gov_fallback"
                    ) as live_mock:
                        with patch(
                            "app.services.rag.answer_with_evidence_gate"
                        ) as rag_mock:
                            with patch(
                                "app.services.llm_service.translate_answer",
                                return_value={
                                    "success": True,
                                    "answer": GOOD_KN_ANSWER_6000
                                    + " https://pmkisan.gov.in/",
                                    "response_language": "KN",
                                    "model": "m",
                                    "latency_ms": 1,
                                },
                            ):
                                out = conversation_service.handle_citizen_chat(
                                    db,
                                    citizen,
                                    message="Translate the above to Kannada.",
                                    conversation_id="conv1",
                                )
        live_mock.assert_not_called()
        rag_mock.assert_not_called()
        self.assertEqual(out["response_language"], "KN")


class TestCitizenFailureKannada(unittest.TestCase):
    def test_captcha_message_is_kannada(self):
        from app.services.citizen_failure_ux import citizen_messages, CAPTCHA_BLOCKED

        msgs = citizen_messages(CAPTCHA_BLOCKED, "KN")
        kn = sum(1 for ch in msgs["answer"] if "\u0c80" <= ch <= "\u0cff")
        self.assertGreater(kn, 20)
        self.assertIn("CAPTCHA", msgs["answer"])


class TestCrossLanguageDirections(unittest.TestCase):
    def test_en_question_en_answer_language(self):
        d = resolve_response_language("What is PM-KISAN eligibility?")
        self.assertEqual(d.response_language, "EN")

    def test_en_question_explicit_kn(self):
        d = resolve_response_language(
            "Who is eligible for PM-KISAN? Please answer in Kannada."
        )
        self.assertEqual(d.response_language, "KN")

    def test_kn_question_explicit_en(self):
        d = resolve_response_language(
            "PM-KISAN \u0caf\u0ccb\u0c9c\u0ca8\u0cc6? Now answer in English."
        )
        self.assertEqual(d.response_language, "EN")


if __name__ == "__main__":
    unittest.main()
