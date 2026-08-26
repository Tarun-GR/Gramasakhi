"""Stage 6C-2 — personalized action plan tests."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from app.services.action_plan import (
    ActionFocus,
    apply_action_plan,
    build_action_plan,
    build_deterministic_action_plan_answer,
    detect_action_focus,
    render_action_plan,
    should_action_plan_followup,
    should_build_action_plan,
)
from app.services.citizen_assistance import CitizenIntent
from app.services.eligibility_evaluation import EvaluationStatus
from app.services.myscheme_service import sections_as_evidence_text


def _doc(scheme: str, sections: dict, source_url: str = "https://www.myscheme.gov.in/schemes/us") -> dict:
    content = sections_as_evidence_text(
        sections,
        scheme_name=scheme,
        scheme_id="us",
        canonical_url=source_url,
    )
    return {
        "content": content,
        "scheme_name": scheme,
        "scheme_id": "us",
        "source": source_url,
        "metadata": {"scheme_name": scheme, "scheme_id": "us", "source": source_url},
    }


SECTIONS = {
    "documents": "- Identity proof (Aadhaar)\n- Bank account details\n- Income certificate",
    "application": (
        "1. Apply through the notified department portal with required documents.\n"
        "2. Submit the application for processing."
    ),
}


def _eval(status: str, *, fail=None, unknown=None):
    crits = []
    if fail:
        crits.append(
            {
                "criterion_type": "income",
                "statement": "Income <= 2 lakh",
                "operator": "<=",
                "expected_value": 200000,
                "outcome": "FAIL",
            }
        )
    if unknown:
        crits.append(
            {
                "criterion_type": "occupation",
                "statement": "Must be farmer",
                "outcome": "UNKNOWN",
            }
        )
    if status == EvaluationStatus.ELIGIBLE.value and not crits:
        crits.append(
            {
                "criterion_type": "age",
                "statement": "Age >= 18",
                "operator": ">=",
                "expected_value": 18,
                "outcome": "PASS",
            }
        )
    return {
        "status": status,
        "scheme_name": "Udyogini Scheme",
        "scheme_id": "us",
        "criteria_results": crits,
        "evaluation_complete": True,
    }


class TestActionPlanStates(unittest.TestCase):
    @patch("app.services.scheme_guidance._verified_url", return_value=True)
    def test_eligible_action_plan(self, _mock):
        ev = [_doc("Udyogini Scheme", SECTIONS)]
        plan = build_action_plan(
            sources=ev,
            query="What should I do next?",
            scheme_identity={"scheme_name": "Udyogini Scheme", "normalized_key": "udyogini"},
            eligibility_status=EvaluationStatus.ELIGIBLE.value,
            eligibility_evaluation=_eval(EvaluationStatus.ELIGIBLE.value),
            evidence_validated=True,
        )
        self.assertEqual(plan.extraction_status, "ok")
        self.assertTrue(plan.steps)
        self.assertIn("Aadhaar", " ".join(plan.documents))
        answer = build_deterministic_action_plan_answer(plan, response_language="EN")
        self.assertIn("next steps", answer.lower())
        self.assertNotIn("will be accepted", answer.lower())

    @patch("app.services.scheme_guidance._verified_url", return_value=True)
    def test_not_eligible_action_plan(self, _mock):
        ev = [_doc("Udyogini Scheme", SECTIONS)]
        plan = build_action_plan(
            sources=ev,
            query="What should I do now?",
            scheme_identity={"scheme_name": "Udyogini Scheme", "normalized_key": "udyogini"},
            eligibility_status=EvaluationStatus.NOT_ELIGIBLE.value,
            eligibility_evaluation=_eval(EvaluationStatus.NOT_ELIGIBLE.value, fail=True),
            evidence_validated=True,
        )
        answer = build_deterministic_action_plan_answer(plan, response_language="EN")
        self.assertIn("do not currently meet", answer.lower())
        self.assertNotIn("apply through the official portal", answer.lower())

    @patch("app.services.scheme_guidance._verified_url", return_value=True)
    def test_cannot_determine_action_plan(self, _mock):
        ev = [_doc("Udyogini Scheme", SECTIONS)]
        plan = build_action_plan(
            sources=ev,
            query="What should I do next?",
            scheme_identity={"scheme_name": "Udyogini Scheme", "normalized_key": "udyogini"},
            eligibility_status=EvaluationStatus.CANNOT_DETERMINE.value,
            eligibility_evaluation=_eval(EvaluationStatus.CANNOT_DETERMINE.value, unknown=True),
            eligibility_session_active=True,
            evidence_validated=True,
        )
        answer = build_deterministic_action_plan_answer(plan, response_language="EN")
        self.assertIn("could not be confirmed", answer.lower())
        self.assertIn("farmer", answer.lower())

    @patch("app.services.scheme_guidance._verified_url", return_value=True)
    def test_no_evaluation_application_question(self, _mock):
        ev = [_doc("Udyogini Scheme", SECTIONS)]
        plan = build_action_plan(
            sources=ev,
            query="What should I do to apply?",
            scheme_identity={"scheme_name": "Udyogini Scheme", "normalized_key": "udyogini"},
            evidence_validated=True,
        )
        self.assertIsNone(plan.status)
        answer = build_deterministic_action_plan_answer(plan, response_language="EN")
        self.assertIn("Apply through", answer)


class TestIntegration(unittest.TestCase):
    @patch("app.services.scheme_guidance._verified_url", return_value=True)
    def test_documents_from_6c1(self, _mock):
        ev = [_doc("Udyogini Scheme", SECTIONS)]
        plan = build_action_plan(
            sources=ev,
            query="What documents should I keep ready?",
            scheme_identity={"scheme_name": "Udyogini Scheme", "normalized_key": "udyogini"},
            eligibility_status=EvaluationStatus.ELIGIBLE.value,
            eligibility_evaluation=_eval(EvaluationStatus.ELIGIBLE.value),
            evidence_validated=True,
            focus=ActionFocus.DOCUMENTS,
        )
        self.assertIn("Income certificate", plan.documents)

    @patch("app.services.scheme_guidance._verified_url", return_value=True)
    def test_application_portal_preserved(self, _mock):
        portal = "https://sevasindhu.karnataka.gov.in/apply"
        ev = [
            _doc(
                "Udyogini Scheme",
                {"application": f"Apply online at {portal}. Login required."},
                source_url=portal,
            )
        ]
        plan = build_action_plan(
            sources=ev,
            query="Where do I apply?",
            scheme_identity={"scheme_name": "Udyogini Scheme", "normalized_key": "udyogini"},
            eligibility_status=EvaluationStatus.ELIGIBLE.value,
            evidence_validated=True,
            focus=ActionFocus.PORTAL,
        )
        self.assertEqual(plan.application_url, portal)
        rendered = render_action_plan(plan, use_llm=False, focus=ActionFocus.PORTAL)
        self.assertTrue(any(x.get("url") == portal for x in rendered["official_sources"]))

    @patch("app.services.scheme_guidance._verified_url", return_value=True)
    def test_pdf_url_preserved(self, _mock):
        pdf = "https://example.gov.in/schemes/rules.pdf"
        ev = [_doc("Udyogini Scheme", SECTIONS, source_url="https://www.myscheme.gov.in/schemes/us")]
        ev[0]["document_url"] = pdf
        ev[0]["metadata"]["document_url"] = pdf
        plan = build_action_plan(
            sources=ev,
            query="What should I do next?",
            scheme_identity={"scheme_name": "Udyogini Scheme", "normalized_key": "udyogini"},
            eligibility_status=EvaluationStatus.ELIGIBLE.value,
            evidence_validated=True,
        )
        self.assertIn(pdf, plan.pdf_urls)


class TestSafety(unittest.TestCase):
    @patch("app.services.scheme_guidance._verified_url", return_value=True)
    def test_no_invented_steps(self, _mock):
        ev = [_doc("Udyogini Scheme", {"application": "Apply through the official process."})]
        plan = build_action_plan(
            sources=ev,
            query="What next?",
            scheme_identity={"scheme_name": "Udyogini Scheme", "normalized_key": "udyogini"},
            eligibility_status=EvaluationStatus.ELIGIBLE.value,
            evidence_validated=True,
        )
        joined = " ".join(s.text.lower() for s in plan.steps)
        self.assertNotIn("create an account", joined)
        self.assertNotIn("pay the application fee", joined)

    @patch("app.services.scheme_guidance._verified_url", return_value=True)
    def test_scheme_mismatch(self, _mock):
        ev = [_doc("PM-KISAN", {"documents": "- Land records"}, source_url="https://example.gov/pm")]
        ev[0]["scheme_id"] = "pmkisan"
        plan = build_action_plan(
            sources=ev,
            query="What next?",
            scheme_identity={"scheme_name": "Udyogini Scheme", "scheme_id": "us", "normalized_key": "udyogini"},
            evidence_validated=True,
        )
        self.assertTrue(plan.rejected)

    @patch("app.services.scheme_guidance._verified_url", return_value=True)
    def test_conversation_isolation(self, _mock):
        ev = [_doc("Udyogini Scheme", SECTIONS)]
        plan = build_action_plan(
            sources=ev,
            query="What next?",
            conversation_id="conv-a",
            session_conversation_id="conv-b",
            evidence_validated=True,
        )
        self.assertEqual(plan.extraction_status, "conversation_mismatch")

    def test_evidence_validator_requirement(self):
        plan = build_action_plan(sources=[], query="What next?", evidence_validated=False)
        self.assertEqual(plan.extraction_status, "evidence_not_validated")

    @patch("app.services.llm_service.generate_from_fixed_prompt")
    @patch("app.services.scheme_guidance._verified_url", return_value=True)
    def test_ollama_cannot_change_eligibility(self, _mock, mock_gen):
        mock_gen.return_value = {
            "response": "Great news! You are eligible and your application will be accepted. Apply now!",
            "model": "test",
        }
        ev = [_doc("Udyogini Scheme", SECTIONS)]
        plan = build_action_plan(
            sources=ev,
            query="Can I apply now?",
            scheme_identity={"scheme_name": "Udyogini Scheme", "normalized_key": "udyogini"},
            eligibility_status=EvaluationStatus.NOT_ELIGIBLE.value,
            eligibility_evaluation=_eval(EvaluationStatus.NOT_ELIGIBLE.value, fail=True),
            evidence_validated=True,
        )
        rendered = render_action_plan(plan, use_llm=True)
        self.assertTrue(rendered["fallback"])
        self.assertNotIn("accepted", rendered["answer"].lower())

    @patch("app.services.llm_service.generate_from_fixed_prompt")
    @patch("app.services.scheme_guidance._verified_url", return_value=True)
    def test_ollama_failure_fallback(self, _mock, mock_gen):
        mock_gen.side_effect = RuntimeError("down")
        ev = [_doc("Udyogini Scheme", SECTIONS)]
        out = apply_action_plan(
            sources=ev,
            query="What should I do next?",
            response_language="EN",
            intent=CitizenIntent.NEXT_ACTION,
            scheme_identity={"scheme_name": "Udyogini Scheme", "normalized_key": "udyogini"},
            eligibility_status=EvaluationStatus.ELIGIBLE.value,
            eligibility_evaluation=_eval(EvaluationStatus.ELIGIBLE.value),
            evidence_validated=True,
            use_llm=True,
        )
        self.assertTrue(out.get("fallback"))
        self.assertTrue(out.get("applied"))


class TestFollowUps(unittest.TestCase):
    def test_detect_focus(self):
        self.assertEqual(detect_action_focus("What should I do next?"), ActionFocus.NEXT)
        self.assertEqual(detect_action_focus("Can I apply now?"), ActionFocus.CAN_APPLY)
        self.assertEqual(detect_action_focus("Where do I apply?"), ActionFocus.PORTAL)

    def test_should_action_plan_followup(self):
        self.assertTrue(should_action_plan_followup("What should I do next?"))
        self.assertFalse(should_action_plan_followup("Hello"))

    def test_should_build_action_plan(self):
        self.assertTrue(should_build_action_plan(CitizenIntent.NEXT_ACTION, "What next?"))


class TestMultilingual(unittest.TestCase):
    @patch("app.services.scheme_guidance._verified_url", return_value=True)
    def test_kannada(self, _mock):
        ev = [_doc("Udyogini Scheme", SECTIONS)]
        plan = build_action_plan(
            sources=ev,
            query="What next?",
            scheme_identity={"scheme_name": "Udyogini Scheme", "normalized_key": "udyogini"},
            eligibility_status=EvaluationStatus.ELIGIBLE.value,
            evidence_validated=True,
        )
        answer = build_deterministic_action_plan_answer(plan, response_language="KN")
        self.assertIn("ಮುಂದಿನ", answer)

    @patch("app.services.scheme_guidance._verified_url", return_value=True)
    def test_hindi(self, _mock):
        ev = [_doc("Udyogini Scheme", SECTIONS)]
        plan = build_action_plan(
            sources=ev,
            query="What next?",
            scheme_identity={"scheme_name": "Udyogini Scheme", "normalized_key": "udyogini"},
            eligibility_status=EvaluationStatus.ELIGIBLE.value,
            evidence_validated=True,
        )
        answer = build_deterministic_action_plan_answer(plan, response_language="HI")
        self.assertIn("कदम", answer)


class TestOfflineAndLogin(unittest.TestCase):
    @patch("app.services.scheme_guidance._verified_url", return_value=True)
    def test_offline_application(self, _mock):
        ev = [
            _doc(
                "Test Scheme",
                {"application": "Applications are submitted through the designated government office."},
            )
        ]
        plan = build_action_plan(
            sources=ev,
            query="What next?",
            scheme_identity={"scheme_name": "Test Scheme", "normalized_key": "test"},
            eligibility_status=EvaluationStatus.ELIGIBLE.value,
            evidence_validated=True,
            focus=ActionFocus.PORTAL,
        )
        answer = build_deterministic_action_plan_answer(plan, focus=ActionFocus.PORTAL, response_language="EN")
        self.assertIn("government office", answer.lower())

    @patch("app.services.scheme_guidance._verified_url", return_value=True)
    def test_login_required(self, _mock):
        portal = "https://sevasindhu.karnataka.gov.in/apply"
        ev = [_doc("Test", {"application": f"Login required at {portal}"}, source_url=portal)]
        plan = build_action_plan(
            sources=ev,
            query="What next?",
            scheme_identity={"scheme_name": "Test Scheme", "normalized_key": "test"},
            eligibility_status=EvaluationStatus.ELIGIBLE.value,
            evidence_validated=True,
        )
        self.assertIn("login_verification_required", plan.warnings)


class TestApiCompatibility(unittest.TestCase):
    def test_chat_response_optional_action_plan(self):
        from app.schemas.chat import ChatResponse

        payload = ChatResponse(
            conversation_id="c1",
            original_query="What should I do next?",
            answer="test",
            action_plan={"status": "ELIGIBLE", "steps": [], "extraction_status": "ok"},
        )
        self.assertEqual(payload.action_plan["status"], "ELIGIBLE")


class TestNoRetrieval(unittest.TestCase):
    @patch("app.services.scheme_guidance._verified_url", return_value=True)
    def test_no_web_retrieval(self, _mock):
        with patch("app.services.rag.answer_with_evidence_gate") as rag_mock:
            apply_action_plan(
                sources=[_doc("Udyogini Scheme", SECTIONS)],
                query="What next?",
                response_language="EN",
                intent=CitizenIntent.NEXT_ACTION,
                evidence_validated=True,
                use_llm=False,
            )
            rag_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
