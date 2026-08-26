"""Stage 6B-2 — interactive eligibility questioning tests."""

from __future__ import annotations

import json
import unittest
from types import SimpleNamespace

from app.services.citizen_assistance import CitizenIntent, build_assistance_context, classify_citizen_intent
from app.services.eligibility_criteria import (
    CriterionType,
    EligibilityCriteriaResult,
    EligibilityCriterion,
    extract_eligibility_criteria,
)
from app.services.eligibility_questioning import (
    EligibilitySession,
    apply_known_to_session,
    capture_session_answer,
    completion_message,
    embed_session_in_sources,
    extract_known_information_from_text,
    load_session_from_messages,
    parse_answer_for_type,
    question_for_type,
    schemes_differ,
    sort_missing,
    start_session_from_criteria,
    strip_internal_sources,
    try_handle_active_session,
)
from app.services.myscheme_service import normalize_scheme_key, sections_as_evidence_text


def _criteria_result(**types: str) -> EligibilityCriteriaResult:
    mapping = {
        "age": CriterionType.AGE.value,
        "gender": CriterionType.GENDER.value,
        "state": CriterionType.STATE.value,
        "income": CriterionType.INCOME.value,
        "occupation": CriterionType.OCCUPATION.value,
    }
    crits = [
        EligibilityCriterion(
            criterion_type=mapping.get(key, CriterionType.OTHER.value),
            statement=statement,
            source_url="https://example.gov/test",
        )
        for key, statement in types.items()
    ]
    return EligibilityCriteriaResult(
        scheme_name="Test Scheme",
        scheme_id="test",
        criteria=crits,
        extraction_status="ok",
    )


def _evidence(scheme: str, eligibility: str, scheme_id: str = "test") -> dict:
    content = sections_as_evidence_text(
        {"eligibility": eligibility},
        scheme_name=scheme,
        scheme_id=scheme_id,
        canonical_url=f"https://example.gov/{scheme_id}",
    )
    return {
        "content": content,
        "scheme_name": scheme,
        "scheme_id": scheme_id,
        "source": f"https://example.gov/{scheme_id}",
    }


class TestSessionStart(unittest.TestCase):
    def test_personal_eligibility_starts_session(self):
        crit = _criteria_result(
            age="Applicant must be at least 18 years old.",
            state="Residents of Karnataka may apply.",
        )
        session = start_session_from_criteria(
            conversation_id="c1",
            active_scheme="Test Scheme",
            scheme_id="test",
            criteria=crit,
            response_language="EN",
        )
        self.assertIsNotNone(session)
        self.assertTrue(session.session_active)
        self.assertIn("age", session.missing_information)

    def test_eligibility_intent_does_not_start_personal_session(self):
        ctx = build_assistance_context(original_query="Who is eligible for PM-KISAN?")
        self.assertEqual(ctx.intent, CitizenIntent.ELIGIBILITY)
        self.assertNotEqual(ctx.intent, CitizenIntent.PERSONAL_ELIGIBILITY)

    def test_validated_criteria_required_to_start(self):
        empty = EligibilityCriteriaResult(extraction_status="no_eligibility_text")
        session = start_session_from_criteria(
            conversation_id="c1",
            active_scheme="Test",
            scheme_id="t",
            criteria=empty,
            response_language="EN",
        )
        self.assertIsNone(session)


class TestMissingDetection(unittest.TestCase):
    def setUp(self):
        self.crit = _criteria_result(
            age="Minimum age 18 years.",
            gender="Women applicants may apply.",
            state="Karnataka residents only.",
            income="Family income below 1.5 lakh.",
            occupation="Farmers may apply.",
        )
        self.session = start_session_from_criteria(
            conversation_id="c1",
            active_scheme="Test",
            scheme_id="test",
            criteria=self.crit,
            response_language="EN",
        )

    def test_missing_age_detected(self):
        self.assertIn("age", self.session.missing_information)

    def test_missing_state_detected(self):
        self.assertIn("state", self.session.missing_information)

    def test_missing_income_detected(self):
        self.assertIn("income", self.session.missing_information)

    def test_missing_gender_detected(self):
        self.assertIn("gender", self.session.missing_information)

    def test_missing_occupation_detected(self):
        self.assertIn("occupation", self.session.missing_information)


class TestQuestionGeneration(unittest.TestCase):
    def test_one_question_at_a_time(self):
        session = start_session_from_criteria(
            conversation_id="c1",
            active_scheme="Test",
            scheme_id="t",
            criteria=_criteria_result(age="Minimum age 18.", state="Karnataka only."),
            response_language="EN",
        )
        q = question_for_type(session.current_question_type or "age", language="EN")
        self.assertNotIn(",", q)
        self.assertLessEqual(len(q.split("?")), 2)

    def test_english_question_generation(self):
        q = question_for_type("age", language="EN")
        self.assertIn("age", q.lower())

    def test_kannada_question_generation(self):
        q = question_for_type("age", language="KN")
        self.assertTrue(any("\u0C80" <= ch <= "\u0CFF" for ch in q))

    def test_hindi_question_generation(self):
        q = question_for_type("age", language="HI")
        self.assertTrue(any("\u0900" <= ch <= "\u097F" for ch in q))


class TestKnownInformation(unittest.TestCase):
    def test_extract_age_gender_state(self):
        known = extract_known_information_from_text(
            "I am a 32 year old woman from Karnataka."
        )
        self.assertEqual(known.get("age"), 32)
        self.assertEqual(known.get("gender"), "female")
        self.assertEqual(known.get("state"), "Karnataka")

    def test_farmer_occupation_only_when_explicit(self):
        known = extract_known_information_from_text("I am a farmer.")
        self.assertEqual(known.get("occupation"), "farmer")
        self.assertNotIn("income", known)

    def test_no_over_inference(self):
        known = extract_known_information_from_text("I am a farmer.")
        self.assertNotIn("age", known)
        self.assertNotIn("state", known)
        self.assertNotIn("gender", known)


class TestAnswerCapture(unittest.TestCase):
    def _session(self, missing: list[str]) -> EligibilitySession:
        s = EligibilitySession(
            conversation_id="c1",
            active_scheme="Test",
            required_information=["age", "state", "income"],
            missing_information=list(missing),
            current_question_type=missing[0] if missing else None,
            response_language="EN",
        )
        return s

    def test_numeric_age_normalization(self):
        ok, val, unclear = parse_answer_for_type("age", "I am 32.")
        self.assertTrue(ok)
        self.assertEqual(val, 32)
        self.assertFalse(unclear)

    def test_income_normalization(self):
        ok, val, _ = parse_answer_for_type("income", "My income is 1.5 lakh")
        self.assertTrue(ok)
        self.assertEqual(val, 150_000)

    def test_state_normalization(self):
        ok, val, _ = parse_answer_for_type("state", "Karnataka")
        self.assertTrue(ok)
        self.assertEqual(val, "Karnataka")

    def test_user_answer_captured(self):
        session = self._session(["age", "state"])
        captured, unrelated, answer = capture_session_answer(session, "32")
        self.assertTrue(captured)
        self.assertFalse(unrelated)
        self.assertEqual(session.known_information.get("age"), 32)
        self.assertIn("state", session.missing_information)

    def test_multiple_facts_in_one_answer(self):
        session = self._session(["age", "state", "income"])
        captured, _, _ = capture_session_answer(session, "I'm 32 and I live in Karnataka.")
        self.assertTrue(captured)
        self.assertEqual(session.known_information.get("age"), 32)
        self.assertEqual(session.known_information.get("state"), "Karnataka")
        self.assertNotIn("age", session.missing_information)
        self.assertNotIn("state", session.missing_information)

    def test_duplicate_question_prevention(self):
        session = self._session(["age", "state"])
        capture_session_answer(session, "32")
        self.assertNotIn("age", session.missing_information)
        self.assertEqual(session.current_question_type, "state")

    def test_user_correction_replaces_previous(self):
        session = self._session(["age", "state"])
        capture_session_answer(session, "32")
        capture_session_answer(session, "Actually I'm 33")
        self.assertEqual(session.known_information.get("age"), 33)

    def test_unclear_answer_does_not_corrupt_state(self):
        session = self._session(["income"])
        before = dict(session.known_information)
        captured, unrelated, msg = capture_session_answer(session, "maybe something")
        self.assertFalse(captured)
        self.assertEqual(session.known_information, before)
        self.assertIn("understand", (msg or "").lower())

    def test_kannada_answer_handling(self):
        known = extract_known_information_from_text("ನನ್ನ ವಯಸ್ಸು 32")
        self.assertEqual(known.get("age"), 32)

    def test_hindi_answer_handling(self):
        known = extract_known_information_from_text("meri age 32 hai")
        self.assertEqual(known.get("age"), 32)

    def test_transliteration_handling(self):
        known = extract_known_information_from_text("nanna vayassu 32")
        self.assertEqual(known.get("age"), 32)


class TestSessionFlow(unittest.TestCase):
    def test_follow_up_unrelated_not_captured_as_answer(self):
        session = EligibilitySession(
            conversation_id="c1",
            active_scheme="Test",
            required_information=["age"],
            missing_information=["age"],
            current_question_type="age",
            response_language="EN",
        )
        captured, unrelated, _ = capture_session_answer(
            session, "What benefits does this scheme provide?"
        )
        self.assertFalse(captured)
        self.assertNotIn("age", session.known_information)

    def test_try_handle_active_session_skips_unrelated(self):
        session = EligibilitySession(
            conversation_id="c1",
            active_scheme="PM-KISAN",
            required_information=["age"],
            missing_information=["age"],
            current_question_type="age",
            session_active=True,
            response_language="EN",
        )
        outcome = try_handle_active_session(
            original_query="What benefits does this scheme provide?",
            prior_session=session,
            detected_scheme="PM-KISAN",
            response_language="EN",
        )
        self.assertFalse(outcome.handled)

    def test_completion_not_eligibility_decision(self):
        session = EligibilitySession(
            conversation_id="c1",
            active_scheme="Test",
            required_information=["age"],
            missing_information=["age"],
            current_question_type="age",
            response_language="EN",
        )
        _, _, answer = capture_session_answer(session, "32")
        self.assertTrue(session.completed)
        self.assertIn("information needed", (answer or "").lower())
        self.assertNotIn("eligible", (answer or "").lower())
        self.assertNotIn("qualify", (answer or "").lower())

    def test_no_eligibility_decision_in_completion_template(self):
        msg = completion_message("EN")
        self.assertNotIn("you are eligible", msg.lower())
        self.assertNotIn("you qualify", msg.lower())


class TestIsolationAndSwitching(unittest.TestCase):
    def test_scheme_switch_detected(self):
        self.assertTrue(schemes_differ("PM-KISAN", "Udyogini"))

    def test_explicit_scheme_switch_resets_context(self):
        session_a = EligibilitySession(
            conversation_id="a",
            active_scheme="PM-KISAN",
            required_information=["age"],
            missing_information=["age"],
            session_active=True,
        )
        outcome = try_handle_active_session(
            original_query="32",
            prior_session=session_a,
            detected_scheme="Udyogini",
            response_language="EN",
        )
        self.assertFalse(outcome.handled)

    def test_conversation_isolation(self):
        s1 = EligibilitySession(
            conversation_id="conv-a",
            active_scheme="PM-KISAN",
            known_information={"age": 32},
            required_information=["age", "state"],
            missing_information=["state"],
        )
        s2 = EligibilitySession(
            conversation_id="conv-b",
            active_scheme="Udyogini",
            known_information={},
            required_information=["gender"],
            missing_information=["gender"],
        )
        self.assertNotEqual(s1.known_information, s2.known_information)
        self.assertNotEqual(s1.conversation_id, s2.conversation_id)

    def test_session_persist_and_load(self):
        session = EligibilitySession(
            conversation_id="c1",
            active_scheme="Test",
            required_information=["age"],
            missing_information=["age"],
            current_question_type="age",
            criteria_snapshot={"scheme_name": "Test"},
        )
        sources = embed_session_in_sources([], session)
        msg = SimpleNamespace(role="assistant", sources_json=json.dumps(sources))
        loaded = load_session_from_messages([msg])
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.active_scheme, "Test")
        self.assertEqual(loaded.current_question_type, "age")

    def test_internal_sources_stripped_from_api(self):
        session = EligibilitySession(conversation_id="c1", active_scheme="Test")
        sources = embed_session_in_sources([{"source": "https://x.gov"}], session)
        public = strip_internal_sources(sources)
        self.assertEqual(len(public), 1)
        self.assertNotIn("_internal", public[0])


class TestCriteriaIntegration(unittest.TestCase):
    def test_pdf_derived_criteria_supported(self):
        ev = _evidence("PMJJBY", "Available to people in the age group of 18 to 50 years.")
        ev["document_type"] = "PDF"
        ev["is_pdf"] = True
        ev["source"] = "https://example.gov/pmjjby.pdf"
        result = extract_eligibility_criteria(ev)
        self.assertEqual(result.extraction_status, "ok")
        session = start_session_from_criteria(
            conversation_id="c1",
            active_scheme="PMJJBY",
            scheme_id="pmjjby",
            criteria=result,
            response_language="EN",
        )
        self.assertIsNotNone(session)
        self.assertIn("age", session.required_information)

    def test_html_derived_criteria_supported(self):
        ev = _evidence(
            "Udyogini",
            "Women entrepreneurs with family income below 1.5 lakh in Karnataka may apply.",
            scheme_id="us",
        )
        result = extract_eligibility_criteria(ev)
        session = start_session_from_criteria(
            conversation_id="c1",
            active_scheme="Udyogini",
            scheme_id="us",
            criteria=result,
            response_language="EN",
        )
        self.assertIsNotNone(session)
        self.assertTrue(result.criteria)
        self.assertTrue(result.criteria[0].source_url)

    def test_source_traceability_intact(self):
        ev = _evidence("Test", "Applicant must be at least 18 years old.")
        result = extract_eligibility_criteria(ev)
        self.assertTrue(all(c.source_url for c in result.criteria))

    def test_completion_when_all_collected(self):
        crit = _criteria_result(age="Minimum age 18.")
        session = start_session_from_criteria(
            conversation_id="c1",
            active_scheme="Test",
            scheme_id="t",
            criteria=crit,
            response_language="EN",
            seed_text="I am 32 years old",
        )
        self.assertTrue(session.completed)
        self.assertFalse(session.missing_information)

    def test_sort_missing_deterministic(self):
        ordered = sort_missing(
            ["income", "age", "state", "gender"],
            ["income", "age", "state", "gender"],
        )
        self.assertEqual(ordered[0], "age")
        self.assertEqual(ordered[-1], "income")


class TestVoiceAndIntent(unittest.TestCase):
    def test_voice_stt_same_intent_path(self):
        from app.services.multilingual_retrieval_service import normalize_stt_artifacts

        stt = normalize_stt_artifacts("Am I eligible for PM-KISAN")
        self.assertEqual(classify_citizen_intent(stt), CitizenIntent.PERSONAL_ELIGIBILITY)

    def test_personal_eligibility_uses_same_criteria_extraction(self):
        ev = _evidence("Test", "Women in Karnataka with income below 1.5 lakh may apply.")
        general = extract_eligibility_criteria(ev, query="Who is eligible?")
        personal = extract_eligibility_criteria(ev, query="Am I eligible?")
        self.assertEqual(
            general.required_information_types(),
            personal.required_information_types(),
        )


class TestNoExtraRetrieval(unittest.TestCase):
    def test_active_session_answer_skips_rag(self):
        session = EligibilitySession(
            conversation_id="c1",
            active_scheme="Test",
            required_information=["age", "state"],
            missing_information=["age", "state"],
            current_question_type="age",
            session_active=True,
            criteria_snapshot={"extraction_status": "ok"},
            response_language="EN",
        )
        outcome = try_handle_active_session(
            original_query="32",
            prior_session=session,
            detected_scheme="Test",
            response_language="EN",
        )
        self.assertTrue(outcome.skip_rag)
        self.assertTrue(outcome.handled)


if __name__ == "__main__":
    unittest.main()
