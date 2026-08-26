"""Stage 6B-1 — eligibility criteria extraction tests."""

from __future__ import annotations

import unittest

from app.services.citizen_assistance import (
    AssistanceMode,
    CitizenIntent,
    build_assistance_context,
    classify_citizen_intent,
)
from app.services.eligibility_criteria import (
    CriterionType,
    extract_eligibility_criteria,
)
from app.services.language_service import resolve_response_language
from app.services.myscheme_service import normalize_scheme_key, sections_as_evidence_text


def _evidence(
    *,
    scheme_name: str,
    eligibility_text: str,
    source_url: str = "https://www.myscheme.gov.in/schemes/test",
    scheme_id: str = "test",
    document_type: str = "HTML",
) -> dict:
    sections = {"eligibility": eligibility_text}
    content = sections_as_evidence_text(
        sections,
        scheme_name=scheme_name,
        scheme_id=scheme_id,
        canonical_url=source_url,
    )
    return {
        "content": content,
        "scheme_name": scheme_name,
        "scheme_id": scheme_id,
        "source": source_url,
        "document_type": document_type,
        "metadata": {"scheme_name": scheme_name, "scheme_id": scheme_id, "source": source_url},
    }


def _pdf_evidence(scheme_name: str, eligibility_text: str, pdf_url: str) -> dict:
    doc = _evidence(
        scheme_name=scheme_name,
        eligibility_text=eligibility_text,
        source_url=pdf_url,
        scheme_id="pmjjby",
        document_type="PDF",
    )
    doc["is_pdf"] = True
    return doc


class TestAgeCriteria(unittest.TestCase):
    def test_simple_age_minimum(self):
        ev = _evidence(
            scheme_name="Test Scheme",
            eligibility_text="Applicant must be at least 18 years old.",
        )
        result = extract_eligibility_criteria(ev)
        self.assertEqual(result.extraction_status, "ok")
        age = [c for c in result.criteria if c.criterion_type == CriterionType.AGE.value]
        self.assertEqual(len(age), 1)
        self.assertEqual(age[0].operator, ">=")
        self.assertEqual(age[0].value, 18)

    def test_minimum_age(self):
        ev = _evidence(
            scheme_name="Test Scheme",
            eligibility_text="Minimum age 21 years is required for applicants.",
        )
        result = extract_eligibility_criteria(ev)
        age = [c for c in result.criteria if c.criterion_type == CriterionType.AGE.value][0]
        self.assertEqual(age.operator, ">=")
        self.assertEqual(age.value, 21)

    def test_maximum_age(self):
        ev = _evidence(
            scheme_name="Test Scheme",
            eligibility_text="Maximum age 40 years applies to all applicants.",
        )
        result = extract_eligibility_criteria(ev)
        age = [c for c in result.criteria if c.criterion_type == CriterionType.AGE.value][0]
        self.assertEqual(age.operator, "<=")
        self.assertEqual(age.value, 40)

    def test_age_range(self):
        ev = _evidence(
            scheme_name="PMJJBY",
            eligibility_text=(
                "Available to people in the age group of 18 to 50 years having a bank account."
            ),
            source_url="https://www.myscheme.gov.in/schemes/pmjjby",
            scheme_id="pmjjby",
        )
        result = extract_eligibility_criteria(
            ev,
            scheme_identity={
                "scheme_name": "PMJJBY",
                "scheme_id": "pmjjby",
                "normalized_key": normalize_scheme_key("PMJJBY"),
            },
        )
        age = [c for c in result.criteria if c.criterion_type == CriterionType.AGE.value]
        self.assertTrue(age)
        self.assertEqual(age[0].operator, "between")
        self.assertEqual(age[0].value, 18)
        self.assertEqual(age[0].value_max, 50)


class TestOtherStructuredCriteria(unittest.TestCase):
    def test_income_maximum(self):
        ev = _evidence(
            scheme_name="Udyogini",
            eligibility_text="Women entrepreneurs with family income below 1.5 lakh may apply.",
            scheme_id="us",
        )
        result = extract_eligibility_criteria(ev)
        income = [c for c in result.criteria if c.criterion_type == CriterionType.INCOME.value]
        self.assertEqual(len(income), 1)
        self.assertEqual(income[0].operator, "<=")
        self.assertEqual(income[0].value, 150_000)
        self.assertEqual(income[0].currency, "INR")

    def test_gender_requirement(self):
        ev = _evidence(
            scheme_name="Udyogini",
            eligibility_text="Women applicants meeting notified criteria may apply.",
            scheme_id="us",
        )
        result = extract_eligibility_criteria(ev)
        gender = [c for c in result.criteria if c.criterion_type == CriterionType.GENDER.value]
        self.assertEqual(len(gender), 1)
        self.assertEqual(gender[0].value, "female")

    def test_state_requirement(self):
        ev = _evidence(
            scheme_name="Udyogini",
            eligibility_text="Implemented for Karnataka beneficiaries who meet notified criteria.",
            scheme_id="us",
        )
        result = extract_eligibility_criteria(ev)
        state = [c for c in result.criteria if c.criterion_type in (
            CriterionType.STATE.value,
            CriterionType.RESIDENCE.value,
        )]
        self.assertTrue(state)
        self.assertIn("karnataka", str(state[0].value).lower())

    def test_occupation_requirement(self):
        ev = _evidence(
            scheme_name="PM-KISAN",
            eligibility_text="All landholding farmer families with cultivable land may apply.",
            scheme_id="pm-kisan",
        )
        result = extract_eligibility_criteria(ev)
        occ = [c for c in result.criteria if c.criterion_type == CriterionType.OCCUPATION.value]
        self.assertTrue(occ)
        self.assertEqual(occ[0].value, "farmer")


class TestLogicalConditions(unittest.TestCase):
    def test_multiple_and_conditions(self):
        ev = _evidence(
            scheme_name="Test Scheme",
            eligibility_text="Applicant must be a woman and belong to Karnataka.",
        )
        result = extract_eligibility_criteria(ev)
        types = {c.criterion_type for c in result.criteria}
        self.assertIn(CriterionType.GENDER.value, types)
        self.assertTrue(
            CriterionType.STATE.value in types or CriterionType.RESIDENCE.value in types
        )
        connectors = [c.logical_connector for c in result.criteria if c.logical_connector]
        self.assertIn("AND", connectors)

    def test_or_conditions(self):
        ev = _evidence(
            scheme_name="Test Scheme",
            eligibility_text="Applicant must be either a student or an unemployed youth.",
        )
        result = extract_eligibility_criteria(ev)
        occ = [c for c in result.criteria if c.criterion_type == CriterionType.OCCUPATION.value]
        self.assertGreaterEqual(len(occ), 2)
        self.assertIn("OR", [c.logical_connector for c in occ])

    def test_conditional_criterion_unstructured(self):
        ev = _evidence(
            scheme_name="Test Scheme",
            eligibility_text=(
                "Applicants must belong to the specified beneficiary group as notified by the department."
            ),
        )
        result = extract_eligibility_criteria(ev)
        self.assertTrue(result.criteria or result.unstructured_statements)
        if result.criteria:
            self.assertEqual(result.criteria[0].confidence, "unstructured")


class TestSafety(unittest.TestCase):
    def test_missing_criterion_not_invented(self):
        ev = _evidence(
            scheme_name="Test Scheme",
            eligibility_text="Eligible beneficiaries may apply through the official portal.",
        )
        result = extract_eligibility_criteria(ev)
        age = [c for c in result.criteria if c.criterion_type == CriterionType.AGE.value]
        income = [c for c in result.criteria if c.criterion_type == CriterionType.INCOME.value]
        self.assertEqual(age, [])
        self.assertEqual(income, [])

    def test_ambiguous_wording_unstructured(self):
        ev = _evidence(
            scheme_name="Test Scheme",
            eligibility_text="Young applicants from low income families may apply.",
        )
        result = extract_eligibility_criteria(ev)
        age = [c for c in result.criteria if c.criterion_type == CriterionType.AGE.value]
        income = [c for c in result.criteria if c.criterion_type == CriterionType.INCOME.value]
        self.assertEqual(age, [])
        self.assertEqual(income, [])

    def test_wrong_scheme_evidence_rejected(self):
        ev = _evidence(
            scheme_name="Udyogini",
            eligibility_text="Women entrepreneurs in Karnataka may apply.",
            scheme_id="us",
        )
        result = extract_eligibility_criteria(
            ev,
            scheme_identity={
                "scheme_name": "Chhattisgarh Saraswati Cycle Yojana",
                "scheme_id": "cg-saraswati-cycle",
                "normalized_key": normalize_scheme_key("Chhattisgarh Saraswati Cycle Yojana"),
            },
        )
        self.assertTrue(result.rejected)
        self.assertEqual(result.extraction_status, "scheme_mismatch")
        self.assertEqual(result.criteria, [])

    def test_scheme_identity_preserved(self):
        ev = _evidence(
            scheme_name="Udyogini Scheme",
            eligibility_text="Women applicants in Karnataka may apply.",
            scheme_id="us",
        )
        result = extract_eligibility_criteria(
            ev,
            scheme_identity={
                "scheme_name": "Udyogini",
                "scheme_id": "us",
                "normalized_key": normalize_scheme_key("Udyogini"),
            },
        )
        self.assertFalse(result.rejected)
        self.assertTrue(all(c.scheme_name == "Udyogini Scheme" for c in result.criteria))

    def test_no_eligibility_decision(self):
        ev = _evidence(
            scheme_name="Test Scheme",
            eligibility_text="Applicant must be at least 18 years old.",
        )
        result = extract_eligibility_criteria(ev)
        self.assertFalse(result.makes_eligibility_decision)
        payload = result.to_dict()
        self.assertFalse(payload["makes_eligibility_decision"])


class TestEvidenceFormats(unittest.TestCase):
    def test_pdf_derived_evidence(self):
        ev = _pdf_evidence(
            "PMJJBY",
            "Available to people in the age group of 18 to 50 years.",
            "https://www.myscheme.gov.in/docs/pmjjby-guidelines.pdf",
        )
        result = extract_eligibility_criteria(ev)
        self.assertEqual(result.extraction_status, "ok")
        self.assertTrue(any(c.document_url.endswith(".pdf") for c in result.criteria))

    def test_html_derived_evidence(self):
        ev = _evidence(
            scheme_name="Udyogini",
            eligibility_text="Women applicants in Karnataka may apply.",
            source_url="https://www.myscheme.gov.in/schemes/us",
        )
        result = extract_eligibility_criteria(ev)
        self.assertEqual(result.extraction_status, "ok")
        self.assertTrue(all("myscheme.gov.in" in (c.source_url or "") for c in result.criteria))

    def test_source_url_preserved(self):
        url = "https://www.india.gov.in/scheme/example"
        ev = _evidence(
            scheme_name="Example",
            eligibility_text="Applicant must be at least 18 years old.",
            source_url=url,
        )
        result = extract_eligibility_criteria(ev)
        self.assertEqual(result.criteria[0].source_url, url)

    def test_document_url_preserved_for_pdf(self):
        pdf = "https://data.gov.in/files/pm-kisan-eligibility.pdf"
        ev = _pdf_evidence("PM-KISAN", "Applicant must be at least 18 years old.", pdf)
        result = extract_eligibility_criteria(ev)
        self.assertEqual(result.criteria[0].document_url, pdf)

    def test_evidence_reference_preserved(self):
        ev = _evidence(
            scheme_name="Test",
            eligibility_text="Applicant must be at least 18 years old.",
        )
        result = extract_eligibility_criteria(ev)
        self.assertTrue(all(c.evidence_ref for c in result.criteria))


class TestMultilingual(unittest.TestCase):
    def test_english_evidence(self):
        ev = _evidence(
            scheme_name="Test",
            eligibility_text="Applicant must be at least 18 years old.",
        )
        result = extract_eligibility_criteria(ev, language="EN")
        self.assertEqual(result.criteria[0].unit, "years")

    def test_kannada_evidence(self):
        ev = _evidence(
            scheme_name="Test",
            eligibility_text="ಅರ್ಜಿದಾರರ ವಯಸ್ಸು ಕನಿಷ್ಠ 18 ವರ್ಷವಾಗಿರಬೇಕು.",
        )
        result = extract_eligibility_criteria(ev, language="KN")
        self.assertEqual(result.extraction_status, "ok")

    def test_hindi_evidence(self):
        ev = _evidence(
            scheme_name="Test",
            eligibility_text="आवेदक की उम्र कम से कम 18 वर्ष होनी चाहिए।",
        )
        result = extract_eligibility_criteria(ev, language="HI")
        self.assertEqual(result.extraction_status, "ok")

    def test_transliteration_uses_same_intent(self):
        self.assertEqual(classify_citizen_intent("yaaru arhru?"), CitizenIntent.ELIGIBILITY)
        self.assertEqual(classify_citizen_intent("kaun eligible hai"), CitizenIntent.ELIGIBILITY)

    def test_response_language_unchanged(self):
        dec = resolve_response_language("ಯಾರು ಅರ್ಹರು?", conversation_language="EN")
        self.assertEqual(dec.response_language, "KN")


class TestAssistanceIntegration(unittest.TestCase):
    def test_personal_eligibility_same_extraction(self):
        ev = _evidence(
            scheme_name="PM-KISAN",
            eligibility_text="All landholding farmer families may apply.",
            scheme_id="pm-kisan",
        )
        general = extract_eligibility_criteria(
            ev,
            query="Who is eligible for PM-KISAN?",
        )
        personal = extract_eligibility_criteria(
            ev,
            query="Am I eligible for PM-KISAN?",
        )
        self.assertEqual(
            {c.criterion_type for c in general.criteria},
            {c.criterion_type for c in personal.criteria},
        )

    def test_assistance_context_compatible(self):
        ctx = build_assistance_context(original_query="Who is eligible for Udyogini?")
        self.assertEqual(ctx.intent, CitizenIntent.ELIGIBILITY)
        self.assertEqual(ctx.assistance_mode, AssistanceMode.ELIGIBILITY)

    def test_personal_eligibility_required_fields_from_criteria(self):
        ev = _evidence(
            scheme_name="Udyogini",
            eligibility_text="Women entrepreneurs with family income below 1.5 lakh in Karnataka may apply.",
            scheme_id="us",
        )
        result = extract_eligibility_criteria(ev)
        required = result.required_information_types()
        self.assertIn("gender", required)
        self.assertIn("income", required)

    def test_unstructured_eligibility_text(self):
        ev = _evidence(
            scheme_name="Test",
            eligibility_text="Applicants must satisfy all conditions published in the official notification.",
        )
        result = extract_eligibility_criteria(ev)
        self.assertTrue(result.criteria or result.extraction_status == "no_eligibility_text")


if __name__ == "__main__":
    unittest.main()
