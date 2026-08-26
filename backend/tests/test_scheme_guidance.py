"""Stage 6C-1 — scheme document and application guidance tests."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from app.services.citizen_assistance import CitizenIntent, classify_citizen_intent, resolve_detected_scheme
from app.services.myscheme_service import sections_as_evidence_text
from app.services.scheme_guidance import (
    GuidanceType,
    apply_scheme_guidance,
    build_deterministic_guidance_answer,
    extract_scheme_guidance,
    guidance_type_from_intent,
    is_guidance_intent,
    render_scheme_guidance,
)


def _doc(
    *,
    scheme: str,
    sections: dict,
    source_url: str = "https://www.myscheme.gov.in/schemes/us",
    scheme_id: str = "us",
    pdf_url: str | None = None,
) -> dict:
    content = sections_as_evidence_text(
        sections,
        scheme_name=scheme,
        scheme_id=scheme_id,
        canonical_url=source_url,
    )
    doc = {
        "content": content,
        "scheme_name": scheme,
        "scheme_id": scheme_id,
        "source": source_url,
        "metadata": {"scheme_name": scheme, "scheme_id": scheme_id, "source": source_url},
    }
    if pdf_url:
        doc["document_url"] = pdf_url
        doc["metadata"]["document_url"] = pdf_url
        doc["metadata"]["document_type"] = "PDF"
    return doc


UDYOGINI_SECTIONS = {
    "documents": (
        "- Identity proof (Aadhaar)\n"
        "- Address proof\n"
        "- Bank account details\n"
        "- Passport-size photograph"
    ),
    "application": (
        "1. Apply through the notified Karnataka department portal with required documents.\n"
        "2. Submit the application for processing at the facilitation centre."
    ),
}

PM_KISAN_SECTIONS = {
    "documents": "- Land records\n- Bank passbook",
    "application": "Register through the PM-KISAN portal with farmer details.",
}


class TestGuidanceIntents(unittest.TestCase):
    def test_documents_intent(self):
        self.assertEqual(classify_citizen_intent("What documents do I need?"), CitizenIntent.DOCUMENTS)

    def test_application_intent(self):
        self.assertEqual(classify_citizen_intent("How do I apply?"), CitizenIntent.APPLICATION)

    def test_application_portal_intent(self):
        self.assertEqual(classify_citizen_intent("Where can I apply?"), CitizenIntent.APPLICATION_PORTAL)

    def test_next_action_intent(self):
        self.assertEqual(classify_citizen_intent("What should I do next?"), CitizenIntent.NEXT_ACTION)

    def test_guidance_intent_mapping(self):
        self.assertTrue(is_guidance_intent(CitizenIntent.DOCUMENTS))
        self.assertEqual(guidance_type_from_intent(CitizenIntent.APPLICATION), GuidanceType.APPLICATION)


class TestDocumentExtraction(unittest.TestCase):
    @patch("app.services.scheme_guidance._verified_url", return_value=True)
    def test_documents_from_html_sections(self, _mock_verify):
        ev = [_doc(scheme="Udyogini Scheme", sections=UDYOGINI_SECTIONS)]
        result = extract_scheme_guidance(
            ev,
            guidance_type=GuidanceType.DOCUMENTS,
            scheme_identity={"scheme_name": "Udyogini Scheme", "scheme_id": "us", "normalized_key": "udyogini"},
            evidence_validated=True,
        )
        self.assertEqual(result.extraction_status, "ok")
        self.assertIn("Aadhaar", " ".join(result.documents))
        self.assertIn("Bank account", " ".join(result.documents))

    @patch("app.services.scheme_guidance._verified_url", return_value=True)
    def test_documents_from_pdf_evidence(self, _mock_verify):
        ev = [
            _doc(
                scheme="Udyogini Scheme",
                sections=UDYOGINI_SECTIONS,
                pdf_url="https://example.gov.in/schemes/udyogini-rules.pdf",
            )
        ]
        result = extract_scheme_guidance(
            ev,
            guidance_type=GuidanceType.DOCUMENTS,
            scheme_identity={"scheme_name": "Udyogini Scheme", "normalized_key": "udyogini"},
            evidence_validated=True,
        )
        self.assertTrue(any(s.get("is_pdf") for s in result.source_urls))

    @patch("app.services.scheme_guidance._verified_url", return_value=True)
    def test_no_invented_documents(self, _mock_verify):
        ev = [_doc(scheme="Test Scheme", sections={"documents": "Documents may vary as notified."})]
        result = extract_scheme_guidance(
            ev,
            guidance_type=GuidanceType.DOCUMENTS,
            scheme_identity={"scheme_name": "Test Scheme", "normalized_key": "test"},
            evidence_validated=True,
        )
        self.assertEqual(result.documents, [])
        answer = build_deterministic_guidance_answer(result, response_language="EN")
        self.assertIn("complete document list", answer.lower())

    @patch("app.services.scheme_guidance._verified_url", return_value=True)
    def test_direct_answer_not_url_only(self, _mock_verify):
        ev = [_doc(scheme="Udyogini Scheme", sections=UDYOGINI_SECTIONS)]
        rendered = render_scheme_guidance(
            extract_scheme_guidance(
                ev,
                guidance_type=GuidanceType.DOCUMENTS,
                scheme_identity={"scheme_name": "Udyogini Scheme", "normalized_key": "udyogini"},
                evidence_validated=True,
            ),
            use_llm=False,
        )
        self.assertIn("Aadhaar", rendered["answer"])
        self.assertNotEqual(rendered["answer"].strip().lower(), "open this website.")


class TestApplicationGuidance(unittest.TestCase):
    @patch("app.services.scheme_guidance._verified_url", return_value=True)
    def test_application_steps_extraction(self, _mock_verify):
        ev = [_doc(scheme="Udyogini Scheme", sections=UDYOGINI_SECTIONS)]
        result = extract_scheme_guidance(
            ev,
            guidance_type=GuidanceType.APPLICATION,
            scheme_identity={"scheme_name": "Udyogini Scheme", "normalized_key": "udyogini"},
            evidence_validated=True,
        )
        self.assertEqual(result.extraction_status, "ok")
        self.assertTrue(result.application_steps)
        answer = build_deterministic_guidance_answer(result, response_language="EN")
        self.assertIn("1.", answer)

    @patch("app.services.scheme_guidance._verified_url", return_value=True)
    def test_offline_application_guidance(self, _mock_verify):
        ev = [
            _doc(
                scheme="Test Scheme",
                sections={
                    "application": (
                        "Applications are submitted through the designated government office "
                        "rather than an online portal."
                    )
                },
            )
        ]
        result = extract_scheme_guidance(
            ev,
            guidance_type=GuidanceType.APPLICATION,
            scheme_identity={"scheme_name": "Test Scheme", "normalized_key": "test"},
            evidence_validated=True,
        )
        answer = build_deterministic_guidance_answer(result, response_language="EN")
        self.assertIn("government office", answer.lower())

    @patch("app.services.scheme_guidance._verified_url", return_value=True)
    def test_missing_application_url(self, _mock_verify):
        ev = [_doc(scheme="Udyogini Scheme", sections=UDYOGINI_SECTIONS)]
        result = extract_scheme_guidance(
            ev,
            guidance_type=GuidanceType.APPLICATION,
            scheme_identity={"scheme_name": "Udyogini Scheme", "normalized_key": "udyogini"},
            evidence_validated=True,
        )
        answer = build_deterministic_guidance_answer(result, response_language="EN")
        self.assertIn("online application link", answer.lower())


class TestPortalHandling(unittest.TestCase):
    @patch("app.services.scheme_guidance._verified_url", return_value=True)
    def test_application_url_preservation(self, _mock_verify):
        portal = "https://sevasindhu.karnataka.gov.in/apply"
        ev = [
            _doc(
                scheme="Shakti Scheme",
                sections={
                    "application": f"Apply online at {portal} with login verification required."
                },
                source_url=portal,
            )
        ]
        result = extract_scheme_guidance(
            ev,
            guidance_type=GuidanceType.APPLICATION_PORTAL,
            scheme_identity={"scheme_name": "Shakti Scheme", "normalized_key": "shakti"},
            evidence_validated=True,
        )
        self.assertEqual(result.application_url, portal)
        rendered = render_scheme_guidance(result, use_llm=False)
        self.assertIn("official application portal", rendered["answer"].lower())
        self.assertTrue(any(x.get("url") == portal for x in rendered["official_sources"]))

    @patch("app.services.scheme_guidance._verified_url", return_value=True)
    def test_login_required_guidance(self, _mock_verify):
        portal = "https://sevasindhu.karnataka.gov.in/apply"
        ev = [
            _doc(
                scheme="Shakti Scheme",
                sections={"application": "Login and OTP verification are required on the portal."},
                source_url=portal,
            )
        ]
        result = extract_scheme_guidance(
            ev,
            guidance_type=GuidanceType.APPLICATION_PORTAL,
            scheme_identity={"scheme_name": "Shakti Scheme", "normalized_key": "shakti"},
            evidence_validated=True,
        )
        answer = build_deterministic_guidance_answer(result, response_language="EN")
        self.assertIn("login", answer.lower())


class TestSchemeIdentity(unittest.TestCase):
    @patch("app.services.scheme_guidance._verified_url", return_value=True)
    def test_cross_scheme_rejection(self, _mock_verify):
        ev = [
            _doc(scheme="PM-KISAN", sections=PM_KISAN_SECTIONS, scheme_id="pmkisan"),
            _doc(scheme="Udyogini Scheme", sections=UDYOGINI_SECTIONS, scheme_id="us"),
        ]
        result = extract_scheme_guidance(
            ev,
            guidance_type=GuidanceType.DOCUMENTS,
            scheme_identity={"scheme_name": "Udyogini Scheme", "scheme_id": "us", "normalized_key": "udyogini"},
            evidence_validated=True,
        )
        self.assertFalse(result.rejected)
        self.assertIn("Aadhaar", " ".join(result.documents))
        self.assertNotIn("Land records", " ".join(result.documents))

    @patch("app.services.scheme_guidance._verified_url", return_value=True)
    def test_scheme_identity_mismatch(self, _mock_verify):
        ev = [_doc(scheme="PM-KISAN", sections=PM_KISAN_SECTIONS, scheme_id="pmkisan")]
        result = extract_scheme_guidance(
            ev,
            guidance_type=GuidanceType.DOCUMENTS,
            scheme_identity={"scheme_name": "Udyogini Scheme", "scheme_id": "us", "normalized_key": "udyogini"},
            evidence_validated=True,
        )
        self.assertTrue(result.rejected)
        answer = build_deterministic_guidance_answer(result, response_language="EN")
        self.assertIn("scheme context", answer.lower())

    def test_explicit_scheme_override(self):
        scheme = resolve_detected_scheme(
            "What documents do I need for PM-KISAN?",
            conversation_active_scheme="Udyogini Scheme",
        )
        self.assertIn("PM-KISAN", scheme or "")

    def test_follow_up_scheme_context(self):
        scheme = resolve_detected_scheme(
            "What documents do I need?",
            conversation_active_scheme="Udyogini Scheme",
            conversation_history=[{"role": "user", "content": "Tell me about Udyogini"}],
        )
        self.assertEqual(scheme, "Udyogini Scheme")


class TestSafetyAndFallback(unittest.TestCase):
    def test_evidence_validator_requirement(self):
        ev = [_doc(scheme="Test", sections=UDYOGINI_SECTIONS)]
        result = extract_scheme_guidance(
            ev,
            guidance_type=GuidanceType.DOCUMENTS,
            evidence_validated=False,
        )
        self.assertEqual(result.extraction_status, "evidence_not_validated")

    @patch("app.services.scheme_guidance._verified_url", return_value=True)
    def test_no_invented_urls(self, _mock_verify):
        ev = [_doc(scheme="Test Scheme", sections={"application": "Apply through the official process."})]
        result = extract_scheme_guidance(
            ev,
            guidance_type=GuidanceType.APPLICATION_PORTAL,
            scheme_identity={"scheme_name": "Test Scheme", "normalized_key": "test"},
            evidence_validated=True,
        )
        self.assertIsNone(result.application_url)

    @patch("app.services.llm_service.generate_from_fixed_prompt")
    @patch("app.services.scheme_guidance._verified_url", return_value=True)
    def test_ollama_cannot_invent_guidance(self, _mock_verify, mock_gen):
        mock_gen.return_value = {
            "response": "You need passport, visa, and must apply at https://evil.example/apply now.",
            "model": "test",
        }
        ev = [_doc(scheme="Udyogini Scheme", sections=UDYOGINI_SECTIONS)]
        extracted = extract_scheme_guidance(
            ev,
            guidance_type=GuidanceType.DOCUMENTS,
            scheme_identity={"scheme_name": "Udyogini Scheme", "normalized_key": "udyogini"},
            evidence_validated=True,
        )
        rendered = render_scheme_guidance(extracted, use_llm=True)
        self.assertTrue(rendered["fallback"])
        self.assertIn("Aadhaar", rendered["answer"])

    @patch("app.services.llm_service.generate_from_fixed_prompt")
    @patch("app.services.scheme_guidance._verified_url", return_value=True)
    def test_ollama_failure_fallback(self, _mock_verify, mock_gen):
        mock_gen.side_effect = RuntimeError("down")
        ev = [_doc(scheme="Udyogini Scheme", sections=UDYOGINI_SECTIONS)]
        rendered = apply_scheme_guidance(
            sources=ev,
            intent=CitizenIntent.DOCUMENTS,
            query="What documents do I need?",
            response_language="EN",
            scheme_identity={"scheme_name": "Udyogini Scheme", "normalized_key": "udyogini"},
            evidence_validated=True,
            use_llm=True,
        )
        self.assertTrue(rendered.get("fallback"))
        self.assertIn("Aadhaar", rendered["answer"])


class TestMultilingual(unittest.TestCase):
    @patch("app.services.scheme_guidance._verified_url", return_value=True)
    def test_english_guidance(self, _mock_verify):
        ev = [_doc(scheme="Udyogini Scheme", sections=UDYOGINI_SECTIONS)]
        result = extract_scheme_guidance(
            ev,
            guidance_type=GuidanceType.DOCUMENTS,
            scheme_identity={"scheme_name": "Udyogini Scheme", "normalized_key": "udyogini"},
            evidence_validated=True,
        )
        answer = build_deterministic_guidance_answer(result, response_language="EN")
        self.assertIn("verified", answer.lower())

    @patch("app.services.scheme_guidance._verified_url", return_value=True)
    def test_kannada_guidance(self, _mock_verify):
        ev = [_doc(scheme="Udyogini Scheme", sections=UDYOGINI_SECTIONS)]
        result = extract_scheme_guidance(
            ev,
            guidance_type=GuidanceType.DOCUMENTS,
            scheme_identity={"scheme_name": "Udyogini Scheme", "normalized_key": "udyogini"},
            evidence_validated=True,
        )
        answer = build_deterministic_guidance_answer(result, response_language="KN")
        self.assertIn("ದಾಖಲೆ", answer)

    @patch("app.services.scheme_guidance._verified_url", return_value=True)
    def test_hindi_guidance(self, _mock_verify):
        ev = [_doc(scheme="Udyogini Scheme", sections=UDYOGINI_SECTIONS)]
        result = extract_scheme_guidance(
            ev,
            guidance_type=GuidanceType.DOCUMENTS,
            scheme_identity={"scheme_name": "Udyogini Scheme", "normalized_key": "udyogini"},
            evidence_validated=True,
        )
        answer = build_deterministic_guidance_answer(result, response_language="HI")
        self.assertIn("दस्तावेज", answer)


class TestFollowUpBehavior(unittest.TestCase):
    @patch("app.services.scheme_guidance._verified_url", return_value=True)
    def test_followup_documents(self, _mock_verify):
        ev = [_doc(scheme="Udyogini Scheme", sections=UDYOGINI_SECTIONS)]
        out = apply_scheme_guidance(
            sources=ev,
            intent=CitizenIntent.DOCUMENTS,
            query="What documents do I need?",
            response_language="EN",
            scheme_identity={"scheme_name": "Udyogini Scheme", "normalized_key": "udyogini"},
            evidence_validated=True,
            use_llm=False,
        )
        self.assertTrue(out.get("applied"))
        self.assertIn("Address proof", out["answer"])

    @patch("app.services.scheme_guidance._verified_url", return_value=True)
    def test_followup_application(self, _mock_verify):
        ev = [_doc(scheme="Udyogini Scheme", sections=UDYOGINI_SECTIONS)]
        out = apply_scheme_guidance(
            sources=ev,
            intent=CitizenIntent.APPLICATION,
            query="How do I apply?",
            response_language="EN",
            scheme_identity={"scheme_name": "Udyogini Scheme", "normalized_key": "udyogini"},
            evidence_validated=True,
            use_llm=False,
        )
        self.assertIn("Apply through", out["answer"])

    @patch("app.services.scheme_guidance._verified_url", return_value=True)
    def test_followup_portal(self, _mock_verify):
        portal = "https://sevasindhu.karnataka.gov.in/apply"
        ev = [
            _doc(
                scheme="Udyogini Scheme",
                sections={"application": f"Apply at {portal}"},
                source_url=portal,
            )
        ]
        out = apply_scheme_guidance(
            sources=ev,
            intent=CitizenIntent.APPLICATION_PORTAL,
            query="Where do I apply?",
            response_language="EN",
            scheme_identity={"scheme_name": "Udyogini Scheme", "normalized_key": "udyogini"},
            evidence_validated=True,
            use_llm=False,
        )
        self.assertIn("portal", out["answer"].lower())


class TestApiCompatibility(unittest.TestCase):
    def test_chat_response_optional_guidance(self):
        from app.schemas.chat import ChatResponse

        payload = ChatResponse(
            conversation_id="c1",
            original_query="What documents do I need?",
            answer="test",
            scheme_guidance={
                "guidance_type": "DOCUMENTS",
                "documents": ["Aadhaar"],
                "extraction_status": "ok",
            },
        )
        self.assertEqual(payload.scheme_guidance["guidance_type"], "DOCUMENTS")


class TestNoRetrieval(unittest.TestCase):
    @patch("app.services.scheme_guidance._verified_url", return_value=True)
    def test_no_web_retrieval_in_guidance_layer(self, _mock_verify):
        with patch("app.services.rag.answer_with_evidence_gate") as rag_mock:
            ev = [_doc(scheme="Udyogini Scheme", sections=UDYOGINI_SECTIONS)]
            apply_scheme_guidance(
                sources=ev,
                intent=CitizenIntent.DOCUMENTS,
                query="What documents do I need?",
                response_language="EN",
                evidence_validated=True,
                use_llm=False,
            )
            rag_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
