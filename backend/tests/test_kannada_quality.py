"""Kannada output quality gate — deterministic hard checks + regen wiring."""

from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from app.services import llm_service
from app.services.language_quality import validate_answer_quality
from app.services.language_service import resolve_response_language
from app.services.prompt_builder import build_prompt
from tests.fixtures.kannada_quality_corpus import (
    BAD_AMOUNT_KN,
    BAD_EN_ANSWER,
    EVIDENCE_PMKISAN,
    GOOD_KN_ANSWER_6000,
    real_style_kannada_questions,
)


def _fake_urlopen_factory(payloads):
    """payloads: list of response dicts, one per call."""
    state = {"i": 0}

    def fake(req, timeout=None):
        idx = min(state["i"], len(payloads) - 1)
        state["i"] += 1
        body = json.dumps(payloads[idx]).encode("utf-8")

        class Resp:
            def read(self):
                return body

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        return Resp()

    fake.state = state
    return fake


class TestScreenshotRegression(unittest.TestCase):
    def test_pm_kisan_kannada_question_resolves_kn(self):
        q = "PM-KISAN \u0caf\u0ccb\u0c9c\u0ca8\u0cc6\u0caf \u0c85\u0cb0\u0ccd\u0cb9\u0ca4\u0cc6 \u0c8f\u0ca8\u0cc1?"
        d = resolve_response_language(q, request_language="en", conversation_language="EN")
        self.assertEqual(d.response_language, "KN")
        prompt = build_prompt(q, EVIDENCE_PMKISAN, response_language="KN")
        self.assertIn("TARGET_RESPONSE_LANGUAGE: KN", prompt)
        self.assertIn("TARGET_LANGUAGE_NAME: Kannada", prompt)
        self.assertIn("Respond entirely in natural Kannada", prompt)
        self.assertIn("Do not switch to English merely because the evidence", prompt)


class TestKannadaQualityGate(unittest.TestCase):
    def test_good_kannada_passes(self):
        r = validate_answer_quality(
            GOOD_KN_ANSWER_6000,
            response_language="KN",
            evidence=EVIDENCE_PMKISAN,
            mode="generation",
        )
        self.assertTrue(r.passed, r.failures)

    def test_english_answer_fails_for_kn_target(self):
        r = validate_answer_quality(
            BAD_EN_ANSWER,
            response_language="KN",
            evidence=EVIDENCE_PMKISAN,
            mode="generation",
        )
        self.assertFalse(r.passed)
        self.assertTrue(any("wrong_language" in f or "english_contamination" in f for f in r.failures))

    def test_invented_amount_fails(self):
        r = validate_answer_quality(
            BAD_AMOUNT_KN,
            response_language="KN",
            evidence=EVIDENCE_PMKISAN,
            mode="generation",
        )
        self.assertFalse(r.passed)
        self.assertTrue(any("invented_amount" in f for f in r.failures))

    def test_url_must_be_preserved_when_present(self):
        source = (
            "PM-KISAN provides financial assistance of Rs 6000 per year. "
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

    def test_invented_url_fails(self):
        ans = GOOD_KN_ANSWER_6000 + " https://evil.example.com/phish"
        r = validate_answer_quality(
            ans,
            response_language="KN",
            evidence=EVIDENCE_PMKISAN,
            mode="generation",
        )
        self.assertFalse(r.passed)
        self.assertTrue(any("invented_url" in f for f in r.failures))

    def test_negation_loss_fails(self):
        ans = (
            "PM-KISAN "
            + "\u0caf\u0ccb\u0c9c\u0ca8\u0cc6\u0caf\u0cb2\u0ccd\u0cb2\u0cbf "
            + "tenant farmers are eligible. Rs 6000."
        )
        r = validate_answer_quality(
            ans,
            response_language="KN",
            evidence=EVIDENCE_PMKISAN,
            mode="generation",
        )
        self.assertFalse(r.passed)
        self.assertTrue(
            any("negation" in f or "wrong_language" in f or "english_contamination" in f for f in r.failures)
        )

    def test_and_or_flip_fails(self):
        source = "Farmers are eligible if they satisfy landholding and aadhaar seeding."
        ans = (
            "\u0cb0\u0cc8\u0ca4\u0cb0\u0cc1 eligible if they satisfy landholding or aadhaar seeding. "
            "Rs 6000."
        )
        r = validate_answer_quality(
            ans,
            response_language="KN",
            source_text=source + " Rs 6000 per year.",
            mode="generation",
        )
        self.assertFalse(r.passed)

    def test_changed_year_fails(self):
        source = "Apply before 31 March 2026. Benefit Rs 6000."
        ans = GOOD_KN_ANSWER_6000 + " 2027"
        r = validate_answer_quality(
            ans, response_language="KN", source_text=source, mode="generation"
        )
        self.assertFalse(r.passed)
        self.assertTrue(any("changed_year" in f for f in r.failures))

    def test_kannada_pmkisan_alias_satisfies_entity_gate(self):
        from app.services.language_quality import check_entity_preservation

        src = "PM-KISAN and PMKISAN provide Rs 6000 per year."
        q = "PM-KISAN \u0caf\u0ccb\u0c9c\u0ca8\u0cc6\u0caf \u0c85\u0cb0\u0ccd\u0cb9\u0ca4\u0cc6?"
        kn_form = (
            "\u0caa\u0cbf\u0c8e\u0c82 \u0c95\u0cbf\u0cb8\u0cbe\u0ca8\u0ccd "
            "\u0caf\u0ccb\u0c9c\u0ca8\u0cc6\u0caf\u0cb2\u0ccd\u0cb2\u0cbf \u0cb0\u0cc2. 6000 "
            "\u0ca8\u0cc0\u0ca1\u0cb2\u0cbe\u0c97\u0cc1\u0ca4\u0ccd\u0ca4\u0ca6\u0cc6."
        )
        ok, fails, _ = check_entity_preservation(src, kn_form, query=q)
        self.assertTrue(ok, fails)
        # Must not emit both PM-KISAN and PMKISAN failures for one omission
        ok2, fails2, _ = check_entity_preservation(
            src, "\u0cb0\u0cc2. 6000 \u0ca8\u0cc0\u0ca1\u0cb2\u0cbe\u0c97\u0cc1\u0ca4\u0ccd\u0ca4\u0ca6\u0cc6.", query=q
        )
        self.assertFalse(ok2)
        self.assertEqual(sum(1 for f in fails2 if f.startswith("missing_entity:")), 1)


class TestCorpusLanguageExpectation(unittest.TestCase):
    def test_fifty_real_style_questions_expect_kn(self):
        corpus = real_style_kannada_questions(50)
        self.assertGreaterEqual(len(corpus), 50)
        for item in corpus:
            d = resolve_response_language(item["question"])
            self.assertEqual(
                d.response_language,
                "KN",
                msg=f"{item['id']}: {item['question']!r} -> {d}",
            )


class TestRegenerationBounded(unittest.TestCase):
    def test_english_then_kannada_regenerates_once(self):
        kn = GOOD_KN_ANSWER_6000 + " https://pmkisan.gov.in/"
        fake = _fake_urlopen_factory(
            [
                {"response": BAD_EN_ANSWER},
                {"response": kn},
            ]
        )
        with patch.object(llm_service.urllib.request, "urlopen", side_effect=fake):
            with patch.object(llm_service.settings, "LANGUAGE_QUALITY_GATE_ENABLED", True):
                with patch.object(llm_service.settings, "MAX_LANGUAGE_REGEN_ATTEMPTS", 2):
                    result = llm_service.generate_answer(
                        "PM-KISAN \u0c85\u0cb0\u0ccd\u0cb9\u0ca4\u0cc6?",
                        EVIDENCE_PMKISAN,
                        response_language="KN",
                    )
        self.assertTrue(result["success"], result)
        self.assertIn("6000", result["answer"])
        self.assertGreaterEqual(result.get("generation_attempt", 1), 2)
        self.assertEqual(fake.state["i"], 2)

    def test_quality_fail_returns_controlled_kannada_message(self):
        fake = _fake_urlopen_factory([{"response": BAD_EN_ANSWER}])
        with patch.object(llm_service.urllib.request, "urlopen", side_effect=fake):
            with patch.object(llm_service.settings, "LANGUAGE_QUALITY_GATE_ENABLED", True):
                with patch.object(llm_service.settings, "MAX_LANGUAGE_REGEN_ATTEMPTS", 0):
                    # max_attempts = 0+1 = 1 single try
                    result = llm_service.generate_answer(
                        "PM-KISAN eligibility",
                        EVIDENCE_PMKISAN,
                        response_language="KN",
                    )
        self.assertFalse(result["success"])
        self.assertTrue(result.get("controlled_failure"))
        # Controlled message should be Kannada script heavy
        kn_chars = sum(1 for ch in result["answer"] if "\u0c80" <= ch <= "\u0cff")
        self.assertGreater(kn_chars, 10)


if __name__ == "__main__":
    unittest.main()
