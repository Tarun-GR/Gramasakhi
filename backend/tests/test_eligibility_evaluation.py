"""Stage 6B-3 — deterministic eligibility evaluation tests."""

from __future__ import annotations

import unittest

from app.services.eligibility_criteria import (
    CriterionConfidence,
    CriterionType,
    EligibilityCriteriaResult,
    EligibilityCriterion,
    extract_eligibility_criteria,
)
from app.services.eligibility_evaluation import (
    CriterionOutcome,
    DecisionReasonCode,
    EvaluationStatus,
    evaluate_eligibility,
    evaluate_session_if_ready,
)
from app.services.eligibility_questioning import (
    EligibilitySession,
    capture_session_answer,
    start_session_from_criteria,
)
from app.services.myscheme_service import normalize_scheme_key, sections_as_evidence_text


def _crit(
    ctype: str,
    *,
    operator: str | None = "=",
    value=None,
    value_max=None,
    statement: str = "test",
    connector: str | None = None,
    confidence: str = CriterionConfidence.EXPLICIT.value,
) -> EligibilityCriterion:
    return EligibilityCriterion(
        criterion_type=ctype,
        statement=statement,
        operator=operator,
        value=value,
        value_max=value_max,
        logical_connector=connector,
        confidence=confidence,
        source_url="https://example.gov/scheme",
        document_url="https://example.gov/scheme.pdf",
        scheme_name="Test Scheme",
        scheme_id="test",
    )


def _criteria(*items: EligibilityCriterion) -> EligibilityCriteriaResult:
    return EligibilityCriteriaResult(
        scheme_name="Test Scheme",
        scheme_id="test",
        criteria=list(items),
        extraction_status="ok",
    )


class TestOverallStatus(unittest.TestCase):
    def test_eligible_result(self):
        c = _criteria(
            _crit(CriterionType.AGE.value, operator=">=", value=18),
            _crit(CriterionType.AGE.value, operator="<=", value=45),
            _crit(CriterionType.STATE.value, operator="=", value="Karnataka"),
            _crit(CriterionType.INCOME.value, operator="<=", value=200000),
        )
        r = evaluate_eligibility(
            criteria=c,
            citizen_answers={"age": 32, "state": "Karnataka", "income": 150000},
            scheme_name="Test Scheme",
            scheme_id="test",
            conversation_id="c1",
            session_conversation_id="c1",
        )
        self.assertEqual(r.status, EvaluationStatus.ELIGIBLE.value)

    def test_not_eligible_result(self):
        c = _criteria(
            _crit(CriterionType.AGE.value, operator=">=", value=18),
            _crit(CriterionType.STATE.value, operator="=", value="Karnataka"),
        )
        r = evaluate_eligibility(
            criteria=c,
            citizen_answers={"age": 17, "state": "Karnataka"},
            scheme_name="Test Scheme",
            scheme_id="test",
        )
        self.assertEqual(r.status, EvaluationStatus.NOT_ELIGIBLE.value)

    def test_cannot_determine_missing_info(self):
        c = _criteria(
            _crit(CriterionType.AGE.value, operator=">=", value=18),
            _crit(CriterionType.STATE.value, operator="=", value="Karnataka"),
            _crit(CriterionType.INCOME.value, operator="<=", value=200000),
        )
        r = evaluate_eligibility(
            criteria=c,
            citizen_answers={"age": 32, "state": "Karnataka"},
            scheme_name="Test Scheme",
            required_information=["age", "state", "income"],
        )
        self.assertEqual(r.status, EvaluationStatus.CANNOT_DETERMINE.value)

    def test_not_eligible_beats_unknown(self):
        c = _criteria(
            _crit(CriterionType.AGE.value, operator=">=", value=18),
            _crit(CriterionType.INCOME.value, operator="<=", value=200000),
        )
        r = evaluate_eligibility(
            criteria=c,
            citizen_answers={"age": 17},
            scheme_name="Test Scheme",
            required_information=["age", "income"],
        )
        self.assertEqual(r.status, EvaluationStatus.NOT_ELIGIBLE.value)


class TestNumericEvaluation(unittest.TestCase):
    def test_age_gte(self):
        c = _criteria(_crit(CriterionType.AGE.value, operator=">=", value=18))
        r = evaluate_eligibility(criteria=c, citizen_answers={"age": 32}, scheme_name="Test Scheme")
        self.assertEqual(r.criteria_results[0].outcome, CriterionOutcome.PASS.value)

    def test_age_lte_fail(self):
        c = _criteria(_crit(CriterionType.AGE.value, operator="<=", value=45))
        r = evaluate_eligibility(criteria=c, citizen_answers={"age": 52}, scheme_name="Test Scheme")
        self.assertEqual(r.criteria_results[0].outcome, CriterionOutcome.FAIL.value)

    def test_age_between(self):
        c = _criteria(_crit(CriterionType.AGE.value, operator="between", value=18, value_max=45))
        r = evaluate_eligibility(criteria=c, citizen_answers={"age": 32}, scheme_name="Test Scheme")
        self.assertEqual(r.criteria_results[0].outcome, CriterionOutcome.PASS.value)
        r2 = evaluate_eligibility(criteria=c, citizen_answers={"age": 17}, scheme_name="Test Scheme")
        self.assertEqual(r2.criteria_results[0].outcome, CriterionOutcome.FAIL.value)

    def test_income_lakh_normalization(self):
        c = _criteria(_crit(CriterionType.INCOME.value, operator="<=", value=200000))
        r = evaluate_eligibility(criteria=c, citizen_answers={"income": 150000}, scheme_name="Test Scheme")
        self.assertEqual(r.criteria_results[0].outcome, CriterionOutcome.PASS.value)
        r2 = evaluate_eligibility(criteria=c, citizen_answers={"income": 300000}, scheme_name="Test Scheme")
        self.assertEqual(r2.criteria_results[0].outcome, CriterionOutcome.FAIL.value)


class TestEnumEvaluation(unittest.TestCase):
    def test_state_equality(self):
        c = _criteria(_crit(CriterionType.STATE.value, operator="=", value="Karnataka"))
        r = evaluate_eligibility(criteria=c, citizen_answers={"state": "Karnataka"}, scheme_name="Test Scheme")
        self.assertEqual(r.criteria_results[0].outcome, CriterionOutcome.PASS.value)
        r2 = evaluate_eligibility(criteria=c, citizen_answers={"state": "Kerala"}, scheme_name="Test Scheme")
        self.assertEqual(r2.criteria_results[0].outcome, CriterionOutcome.FAIL.value)

    def test_gender_equality(self):
        c = _criteria(_crit(CriterionType.GENDER.value, operator="=", value="female"))
        r = evaluate_eligibility(criteria=c, citizen_answers={"gender": "female"}, scheme_name="Test Scheme")
        self.assertEqual(r.criteria_results[0].outcome, CriterionOutcome.PASS.value)
        r2 = evaluate_eligibility(criteria=c, citizen_answers={"gender": "male"}, scheme_name="Test Scheme")
        self.assertEqual(r2.criteria_results[0].outcome, CriterionOutcome.FAIL.value)

    def test_occupation_evaluation(self):
        c = _criteria(_crit(CriterionType.OCCUPATION.value, operator="=", value="farmer"))
        r = evaluate_eligibility(criteria=c, citizen_answers={"occupation": "farmer"}, scheme_name="Test Scheme")
        self.assertEqual(r.criteria_results[0].outcome, CriterionOutcome.PASS.value)


class TestLogicGroups(unittest.TestCase):
    def test_and_logic(self):
        c = _criteria(
            _crit(CriterionType.AGE.value, operator=">=", value=18, connector="AND"),
            _crit(CriterionType.STATE.value, operator="=", value="Karnataka"),
        )
        r = evaluate_eligibility(
            criteria=c,
            citizen_answers={"age": 32, "state": "Kerala"},
            scheme_name="Test Scheme",
        )
        self.assertEqual(r.status, EvaluationStatus.NOT_ELIGIBLE.value)

    def test_or_logic_pass(self):
        c = _criteria(
            _crit(CriterionType.OCCUPATION.value, operator="=", value="farmer", connector="OR"),
            _crit(CriterionType.OCCUPATION.value, operator="=", value="agricultural worker"),
        )
        r = evaluate_eligibility(
            criteria=c,
            citizen_answers={"occupation": "farmer"},
            scheme_name="Test Scheme",
        )
        self.assertEqual(r.status, EvaluationStatus.ELIGIBLE.value)

    def test_or_logic_fail(self):
        c = _criteria(
            _crit(CriterionType.OCCUPATION.value, operator="=", value="farmer", connector="OR"),
            _crit(CriterionType.OCCUPATION.value, operator="=", value="agricultural worker"),
        )
        r = evaluate_eligibility(
            criteria=c,
            citizen_answers={"occupation": "teacher"},
            scheme_name="Test Scheme",
        )
        self.assertEqual(r.status, EvaluationStatus.NOT_ELIGIBLE.value)


class TestSafety(unittest.TestCase):
    def test_unknown_unstructured_criterion(self):
        c = _criteria(
            _crit(
                CriterionType.OTHER.value,
                operator=None,
                value=None,
                confidence=CriterionConfidence.UNSTRUCTURED.value,
                statement="Applicants must belong to the specified beneficiary group.",
            )
        )
        r = evaluate_eligibility(
            criteria=c,
            citizen_answers={"other": "something"},
            scheme_name="Test Scheme",
        )
        self.assertEqual(r.status, EvaluationStatus.CANNOT_DETERMINE.value)

    def test_scheme_identity_mismatch(self):
        c = _criteria(_crit(CriterionType.AGE.value, operator=">=", value=18))
        c.scheme_name = "PM-KISAN"
        c.scheme_id = "pm-kisan"
        r = evaluate_eligibility(
            criteria=c,
            citizen_answers={"age": 32},
            scheme_name="Udyogini",
            scheme_id="us",
        )
        self.assertEqual(r.decision_reason_code, DecisionReasonCode.SCHEME_IDENTITY_MISMATCH.value)

    def test_conversation_isolation(self):
        c = _criteria(_crit(CriterionType.AGE.value, operator=">=", value=18))
        r = evaluate_eligibility(
            criteria=c,
            citizen_answers={"age": 32},
            scheme_name="Test Scheme",
            conversation_id="a",
            session_conversation_id="b",
        )
        self.assertEqual(r.decision_reason_code, DecisionReasonCode.CONVERSATION_MISMATCH.value)

    def test_evidence_not_validated(self):
        c = _criteria(_crit(CriterionType.AGE.value, operator=">=", value=18))
        r = evaluate_eligibility(
            criteria=c,
            citizen_answers={"age": 32},
            scheme_name="Test Scheme",
            evidence_validated=False,
        )
        self.assertEqual(r.decision_reason_code, DecisionReasonCode.EVIDENCE_NOT_VALIDATED.value)

    def test_source_traceability(self):
        c = _criteria(_crit(CriterionType.AGE.value, operator=">=", value=18))
        r = evaluate_eligibility(criteria=c, citizen_answers={"age": 32}, scheme_name="Test Scheme")
        self.assertTrue(r.criteria_results[0].source_url)
        self.assertTrue(r.criteria_results[0].document_url)

    def test_no_eligible_from_unknown_only(self):
        c = _criteria(
            _crit(CriterionType.SOCIAL_CATEGORY.value, operator="=", value="specific group"),
        )
        r = evaluate_eligibility(
            criteria=c,
            citizen_answers={"age": 32},
            scheme_name="Test Scheme",
            required_information=["social_category"],
        )
        self.assertEqual(r.status, EvaluationStatus.CANNOT_DETERMINE.value)
        self.assertNotEqual(r.status, EvaluationStatus.ELIGIBLE.value)


class TestIntegration(unittest.TestCase):
    def _snapshot_from_text(self, text: str) -> dict:
        content = sections_as_evidence_text(
            {"eligibility": text},
            scheme_name="Test Scheme",
            scheme_id="test",
            canonical_url="https://example.gov/test",
        )
        result = extract_eligibility_criteria(
            {
                "content": content,
                "scheme_name": "Test Scheme",
                "scheme_id": "test",
                "source": "https://example.gov/test",
            }
        )
        return result.to_dict()

    def test_stage_6b2_session_integration(self):
        crit = EligibilityCriteriaResult(
            scheme_name="Test Scheme",
            scheme_id="test",
            criteria=[
                _crit(CriterionType.AGE.value, operator=">=", value=18),
                _crit(CriterionType.STATE.value, operator="=", value="Karnataka"),
            ],
            extraction_status="ok",
        )
        session = start_session_from_criteria(
            conversation_id="c1",
            active_scheme="Test Scheme",
            scheme_id="test",
            criteria=crit,
            response_language="EN",
            seed_text="",
        )
        self.assertIsNotNone(session)
        capture_session_answer(session, "32")
        capture_session_answer(session, "Karnataka")
        self.assertTrue(session.completed)
        result = evaluate_session_if_ready(session, evidence_validated=True)
        self.assertIsNotNone(result)
        self.assertEqual(result.status, EvaluationStatus.ELIGIBLE.value)

    def test_pdf_derived_criteria(self):
        snap = self._snapshot_from_text(
            "Available to people in the age group of 18 to 50 years."
        )
        session = EligibilitySession(
            conversation_id="c1",
            active_scheme="Test Scheme",
            scheme_id="test",
            criteria_snapshot=snap,
            required_information=["age"],
            known_information={"age": 32},
            collected_answers={"age": 32},
            completed=True,
            session_active=False,
        )
        result = evaluate_session_if_ready(session)
        self.assertEqual(result.status, EvaluationStatus.ELIGIBLE.value)

    def test_kannada_state_value(self):
        c = _criteria(_crit(CriterionType.STATE.value, operator="=", value="Karnataka"))
        r = evaluate_eligibility(
            criteria=c,
            citizen_answers={"state": "ಕರ್ನಾಟಕ"},
            scheme_name="Test Scheme",
        )
        self.assertEqual(r.criteria_results[0].outcome, CriterionOutcome.PASS.value)

    def test_hindi_age_value(self):
        c = _criteria(_crit(CriterionType.AGE.value, operator=">=", value=18))
        r = evaluate_eligibility(criteria=c, citizen_answers={"age": 32}, scheme_name="Test Scheme")
        self.assertEqual(r.criteria_results[0].outcome, CriterionOutcome.PASS.value)

    def test_evaluation_complete_flag(self):
        c = _criteria(_crit(CriterionType.AGE.value, operator=">=", value=18))
        r = evaluate_eligibility(criteria=c, citizen_answers={"age": 32}, scheme_name="Test Scheme")
        self.assertTrue(r.evaluation_complete)


class TestMultilingualValues(unittest.TestCase):
    def test_transliteration_state(self):
        c = _criteria(_crit(CriterionType.STATE.value, operator="=", value="Karnataka"))
        r = evaluate_eligibility(
            criteria=c,
            citizen_answers={"state": "Karnataka"},
            scheme_name="Test Scheme",
        )
        self.assertEqual(r.status, EvaluationStatus.ELIGIBLE.value)


if __name__ == "__main__":
    unittest.main()
