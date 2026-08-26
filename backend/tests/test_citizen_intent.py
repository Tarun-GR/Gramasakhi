"""Stage 6A — citizen intent and assistance context tests."""

from __future__ import annotations

import unittest

from app.services.citizen_assistance import (
    AssistanceMode,
    CitizenIntent,
    build_assistance_context,
    classify_citizen_intent,
    extract_comparison_schemes,
    resolve_detected_scheme,
)
from app.services.language_service import resolve_response_language


class TestEnglishIntents(unittest.TestCase):
    def test_overview(self):
        self.assertEqual(classify_citizen_intent("What is PM-KISAN?"), CitizenIntent.OVERVIEW)

    def test_eligibility(self):
        self.assertEqual(
            classify_citizen_intent("Who is eligible for PM-KISAN?"),
            CitizenIntent.ELIGIBILITY,
        )

    def test_benefits(self):
        self.assertEqual(
            classify_citizen_intent("What are the benefits of PM-KISAN?"),
            CitizenIntent.BENEFITS,
        )

    def test_documents(self):
        self.assertEqual(
            classify_citizen_intent("What documents are required?"),
            CitizenIntent.DOCUMENTS,
        )

    def test_application(self):
        self.assertEqual(
            classify_citizen_intent("How do I apply for PM-KISAN?"),
            CitizenIntent.APPLICATION,
        )

    def test_deadline(self):
        self.assertEqual(
            classify_citizen_intent("When is the deadline for PM-KISAN?"),
            CitizenIntent.DEADLINE,
        )

    def test_application_portal(self):
        self.assertEqual(
            classify_citizen_intent("Where can I apply for PM-KISAN?"),
            CitizenIntent.APPLICATION_PORTAL,
        )

    def test_personal_eligibility(self):
        self.assertEqual(
            classify_citizen_intent("Am I eligible for PM-KISAN?"),
            CitizenIntent.PERSONAL_ELIGIBILITY,
        )

    def test_comparison(self):
        self.assertEqual(
            classify_citizen_intent("Compare PM-KISAN and PMFBY"),
            CitizenIntent.COMPARISON,
        )


class TestMultilingualIntents(unittest.TestCase):
    def test_kannada_overview(self):
        self.assertEqual(
            classify_citizen_intent("ಪಿಎಂ ಕಿಸಾನ್ ಯೋಜನೆ ಬಗ್ಗೆ ಹೇಳಿ"),
            CitizenIntent.OVERVIEW,
        )

    def test_kannada_eligibility(self):
        self.assertEqual(
            classify_citizen_intent("ಯಾರು ಅರ್ಹರು?"),
            CitizenIntent.ELIGIBILITY,
        )

    def test_hindi_eligibility(self):
        self.assertEqual(
            classify_citizen_intent("कौन पात्र है?"),
            CitizenIntent.ELIGIBILITY,
        )

    def test_kannada_transliterated_eligibility(self):
        self.assertEqual(
            classify_citizen_intent("yojaneke yaaru arhru"),
            CitizenIntent.ELIGIBILITY,
        )

    def test_hindi_transliterated_eligibility(self):
        self.assertEqual(
            classify_citizen_intent("kaun eligible hai"),
            CitizenIntent.ELIGIBILITY,
        )


class TestAssistanceContext(unittest.TestCase):
    def test_follow_up_eligibility_with_scheme_context(self):
        history = [{"role": "user", "content": "What is PM-KISAN?"}]
        ctx = build_assistance_context(
            original_query="Who is eligible?",
            conversation_history=history,
            conversation_active_scheme="PM-KISAN",
            rewrite_active_scheme="PM-KISAN",
        )
        self.assertEqual(ctx.intent, CitizenIntent.ELIGIBILITY)
        self.assertEqual(ctx.detected_scheme, "PM-KISAN")
        self.assertTrue(ctx.is_follow_up)

    def test_explicit_scheme_overrides_previous(self):
        history = [{"role": "user", "content": "Tell me about PM-KISAN"}]
        ctx = build_assistance_context(
            original_query="Tell me about Udyogini",
            conversation_history=history,
            conversation_active_scheme="PM-KISAN",
        )
        self.assertEqual(ctx.detected_scheme, "Udyogini")
        self.assertNotEqual(ctx.detected_scheme, "PM-KISAN")

    def test_follow_up_uses_new_scheme_after_topic_change(self):
        history = [
            {"role": "user", "content": "Tell me about PM-KISAN"},
            {"role": "assistant", "content": "PM-KISAN is..."},
            {"role": "user", "content": "Tell me about Udyogini"},
        ]
        ctx = build_assistance_context(
            original_query="Who is eligible?",
            conversation_history=history,
            conversation_active_scheme="Udyogini",
            rewrite_active_scheme="Udyogini",
        )
        self.assertEqual(ctx.detected_scheme, "Udyogini")
        self.assertEqual(ctx.intent, CitizenIntent.ELIGIBILITY)

    def test_new_topic_does_not_inherit_old_scheme_when_standalone(self):
        scheme = resolve_detected_scheme(
            "Tell me about farming subsidies in Karnataka",
            conversation_active_scheme="PM-KISAN",
            conversation_history=[{"role": "user", "content": "What is PM-KISAN?"}],
        )
        self.assertIsNone(scheme)

    def test_comparison_schemes_isolated(self):
        schemes = extract_comparison_schemes("Compare PM-KISAN and PMFBY")
        self.assertEqual(schemes, ["PM-KISAN", "PMFBY"])
        ctx = build_assistance_context(original_query="Compare PM-KISAN and PMFBY")
        self.assertEqual(ctx.intent, CitizenIntent.COMPARISON)
        self.assertEqual(ctx.assistance_mode, AssistanceMode.COMPARISON)
        self.assertEqual(len(ctx.comparison_schemes), 2)

    def test_personal_eligibility_framework_empty_in_6a(self):
        ctx = build_assistance_context(original_query="Am I eligible for PM-KISAN?")
        self.assertEqual(ctx.intent, CitizenIntent.PERSONAL_ELIGIBILITY)
        self.assertEqual(ctx.assistance_mode, AssistanceMode.COLLECT_INFORMATION)
        self.assertEqual(ctx.required_information, [])
        self.assertEqual(ctx.known_information, [])
        self.assertEqual(ctx.missing_information, [])

    def test_unknown_intent_safe(self):
        ctx = build_assistance_context(original_query="Hello there")
        self.assertEqual(ctx.intent, CitizenIntent.UNKNOWN)
        self.assertEqual(ctx.assistance_mode, AssistanceMode.GENERAL)

    def test_response_language_unchanged_by_intent(self):
        kn = resolve_response_language("ಯಾರು ಅರ್ಹರು?", conversation_language="EN")
        self.assertEqual(kn.response_language, "KN")
        intent = classify_citizen_intent("ಯಾರು ಅರ್ಹರು?")
        self.assertEqual(intent, CitizenIntent.ELIGIBILITY)

    def test_voice_stt_text_same_intent_path(self):
        from app.services.multilingual_retrieval_service import normalize_stt_artifacts

        stt = normalize_stt_artifacts("Who is eligible for PM-KISAN")
        self.assertEqual(classify_citizen_intent(stt), CitizenIntent.ELIGIBILITY)

    def test_conversation_isolation_independent_contexts(self):
        hist_a = [{"role": "user", "content": "What is PM-KISAN?"}]
        hist_b = [{"role": "user", "content": "What is Udyogini?"}]
        a = build_assistance_context(
            original_query="Who is eligible?",
            conversation_history=hist_a,
            rewrite_active_scheme="PM-KISAN",
        )
        b = build_assistance_context(
            original_query="Who is eligible?",
            conversation_history=hist_b,
            rewrite_active_scheme="Udyogini",
        )
        self.assertEqual(a.detected_scheme, "PM-KISAN")
        self.assertEqual(b.detected_scheme, "Udyogini")


if __name__ == "__main__":
    unittest.main()
