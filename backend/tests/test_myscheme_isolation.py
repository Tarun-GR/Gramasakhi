"""Scheme isolation + myScheme evidence path (screenshot failure repros)."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.services.evidence_validator import EvidenceValidator
from app.services.myscheme_service import (
    canonical_myscheme_page_url,
    evidence_matches_requested_scheme,
    extract_scheme_id_from_url,
    filter_evidence_by_scheme,
    is_myscheme_shell_html,
    package_myscheme_evidence,
    query_citizen_intent,
    request_accepts_candidate,
    requested_scheme_identity,
    select_question_aware_evidence,
)
from app.services.query_rewriter import (
    extract_scheme_mentions,
    is_standalone_query,
    rewrite_query,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "acquisition"


class TestSchemeIdentity(unittest.TestCase):
    def test_udyogini_details_identity(self):
        ident = requested_scheme_identity("Can I get details about Udyogini Scheme?")
        self.assertIsNotNone(ident)
        self.assertIn("udyogini", (ident or {}).get("normalized_key", ""))

    def test_reject_pm_kisan_for_udyogini(self):
        docs = [
            {
                "scheme_name": "PM-KISAN",
                "scheme_id": "pmkisan",
                "content": "PM-KISAN provides income support to farmer families.",
                "source": "https://www.myscheme.gov.in/schemes/pmkisan",
            },
            {
                "scheme_name": "Udyogini Scheme",
                "scheme_id": "us",
                "content": "Udyogini eligibility for women entrepreneurs in Karnataka.",
                "metadata": {"scheme_id": "us"},
                "source": "https://www.myscheme.gov.in/schemes/us",
            },
        ]
        kept = filter_evidence_by_scheme("Udyogini eligibility", docs)
        self.assertEqual(len(kept), 1)
        self.assertIn("Udyogini", kept[0]["scheme_name"])

    def test_ev_rejects_wrong_scheme_only(self):
        docs = [
            {
                "scheme_name": "PM-KISAN",
                "content": "PM-KISAN income support installment farmer family.",
                "similarity_score": 0.99,
                "source": "https://www.myscheme.gov.in/schemes/pmkisan",
            }
        ]
        result = EvidenceValidator().validate("Who is eligible for Udyogini?", docs)
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "wrong_scheme_evidence")


class TestTopicSwitch(unittest.TestCase):
    def test_udyogini_is_standalone(self):
        self.assertTrue(is_standalone_query("Can I get details about Udyogini Scheme?"))
        self.assertIn("Udyogini", extract_scheme_mentions("Udyogini Scheme details"))

    def test_switch_from_udyogini_to_pm_kisan(self):
        history = [
            {"role": "user", "content": "Tell me about Udyogini."},
            {"role": "assistant", "content": "Udyogini supports women entrepreneurs."},
        ]
        out = rewrite_query("Tell me about PM-KISAN.", history)
        rewritten = out.get("rewritten_query") or ""
        self.assertIn("PM-KISAN", rewritten.upper())
        self.assertNotIn("Udyogini", rewritten)

    def test_followup_inherits_udyogini(self):
        history = [
            {"role": "user", "content": "Tell me about Udyogini."},
            {"role": "assistant", "content": "Udyogini Scheme overview."},
        ]
        out = rewrite_query("Who is eligible?", history)
        rewritten = out.get("rewritten_query") or ""
        self.assertIn("Udyogini", rewritten)


class TestPackagedEvidence(unittest.TestCase):
    def test_package_has_sections_not_url_only(self):
        html = (FIXTURES / "myscheme_scheme_udyogini.html").read_text(encoding="utf-8")
        packed = package_myscheme_evidence(
            html=html,
            scheme_name="Udyogini Scheme",
            source_url="https://www.myscheme.gov.in/schemes/us",
            query="Can I get details about Udyogini Scheme?",
        )
        self.assertTrue(packed["ok"])
        body = packed["content"].decode("utf-8")
        self.assertIn("SCHEME:", body)
        self.assertIn("SECTION:", body)
        self.assertIn("Benefits", body)
        self.assertIn("Eligibility", body)
        self.assertNotEqual(body.strip(), "https://www.myscheme.gov.in/schemes/us")

    def test_network_error_toast_with_sections_succeeds(self):
        html = (FIXTURES / "myscheme_network_error_with_sections.html").read_text(
            encoding="utf-8"
        )
        shell, _ = is_myscheme_shell_html(html)
        self.assertFalse(shell)
        packed = package_myscheme_evidence(
            html=html,
            scheme_name="Udyogini Scheme",
            source_url="https://www.myscheme.gov.in/schemes/us",
            query="Udyogini details",
        )
        self.assertTrue(packed["ok"])
        self.assertIn("benefits", packed["sections"])
        self.assertIn("eligibility", packed["sections"])

    def test_discover_keeps_packed_candidate(self):
        from app.services.acquisition.base import (
            AcquisitionMethod,
            AcquisitionResult,
            SourceHealth,
        )
        from app.services.live_gov_retrieval_service import LiveGovRetrievalService

        html = (FIXTURES / "myscheme_scheme_udyogini.html").read_text(encoding="utf-8")
        # Simulate SPA toast noise in rendered_text that previously triggered skip_low
        rendered = "Something went wrong Network Error Please try again later\n" + (
            "Details Benefits Eligibility Application Process Documents Required "
            "Udyogini Scheme supports women entrepreneurs with subsidy support."
        )
        svc = LiveGovRetrievalService(db=MagicMock())
        svc.acquisition = MagicMock()
        svc.acquisition.acquire.return_value = AcquisitionResult(
            url="https://www.myscheme.gov.in/schemes/us",
            final_url="https://www.myscheme.gov.in/schemes/us",
            content=html.encode("utf-8"),
            content_type="text/html",
            rendered_text=rendered,
            method=AcquisitionMethod.BROWSER_JS,
            health=SourceHealth.HEALTHY,
            discovered_links=[],
        )
        with patch(
            "app.services.live_gov_retrieval_service.verify_source", return_value=True
        ):
            cands = svc.discover_candidate_pages(
                "details about Udyogini Scheme",
                seeds=[
                    {
                        "url": "https://www.myscheme.gov.in/schemes/us",
                        "scheme_name": "Udyogini Scheme",
                        "scheme_id": "us",
                        "kind": "scheme_page",
                        "source": "myscheme",
                    }
                ],
            )
        packed = [c for c in cands if c.get("content") and b"Benefits" in (c.get("content") or b"")]
        self.assertTrue(packed, msg=f"expected packed evidence candidate, got {cands}")


class TestMatchHelper(unittest.TestCase):
    def test_match_by_scheme_id(self):
        ok = evidence_matches_requested_scheme(
            {
                "scheme_id": "us",
                "scheme_name": "Udyogini Scheme",
                "content": "Benefits for women",
            },
            {"normalized_key": "udyogini", "scheme_id": "us", "scheme_name": "Udyogini"},
        )
        self.assertTrue(ok)

    def test_api_url_slug_not_version(self):
        api = "https://api.myscheme.gov.in/schemes/v6/public/schemes?slug=us&lang=en"
        self.assertEqual(extract_scheme_id_from_url(api), "us")
        self.assertEqual(
            canonical_myscheme_page_url(api),
            "https://www.myscheme.gov.in/schemes/us",
        )
        self.assertEqual(
            extract_scheme_id_from_url("https://www.myscheme.gov.in/schemes/us"),
            "us",
        )
        self.assertIsNone(
            extract_scheme_id_from_url(
                "https://api.myscheme.gov.in/schemes/v6/public/schemes"
            )
        )

    def test_udyogini_accepts_misparsed_v6_metadata(self):
        """API version 'v6' must not reject real Udyogini evidence."""
        doc = {
            "scheme_name": "Udyogini Scheme",
            "scheme_id": "v6",
            "content": "Udyogini eligibility for women entrepreneurs in Karnataka.",
            "source": "https://api.myscheme.gov.in/schemes/v6/public/schemes?slug=us",
            "url": "https://api.myscheme.gov.in/schemes/v6/public/schemes?slug=us",
        }
        self.assertTrue(
            request_accepts_candidate("Can I get details about Udyogini Scheme?", doc)
        )
        self.assertFalse(
            request_accepts_candidate("Can I get details about Udyogini Scheme?", PMSBY_DOC)
        )
        self.assertFalse(
            request_accepts_candidate(
                "Can I get details about Udyogini Scheme?", PMKISAN_DOC
            )
        )


PMSBY_DOC = {
    "scheme_name": "Pradhan Mantri Suraksha Bima Yojana",
    "scheme_id": "pmsby",
    "content": "PM-SBY provides accidental death and disability insurance cover.",
    "source": "https://www.myscheme.gov.in/schemes/pmsby",
    "url": "https://www.myscheme.gov.in/schemes/pmsby",
    "similarity_score": 0.99,
    "hybrid_score": 0.99,
    "kind": "scheme_page",
}

KSCSTE_DOC = {
    "scheme_name": "KSCSTE Emeritus Scientist Scheme",
    "scheme_id": "kscste-ess",
    "content": (
        "KSCSTE Emeritus Scientist Scheme supports retired scientists in Kerala "
        "with research fellowship and contingency grants."
    ),
    "source": "https://www.myscheme.gov.in/schemes/kscste-ess",
    "url": "https://www.myscheme.gov.in/schemes/kscste-ess",
    "kind": "scheme_page",
}

KSCSTE_Q = "details about KSCSTE Emeritus Scientist Scheme"
PMKISAN_DOC = {
    "scheme_name": "Pradhan Mantri Kisan Samman Nidhi",
    "scheme_id": "pm-kisan",
    "content": "PM-KISAN provides income support to landholding farmer families.",
    "source": "https://www.myscheme.gov.in/schemes/pm-kisan",
    "url": "https://www.myscheme.gov.in/schemes/pm-kisan",
    "kind": "scheme_page",
}
UDYOGINI_DOC = {
    "scheme_name": "Udyogini Scheme",
    "scheme_id": "us",
    "content": "Udyogini supports women entrepreneurs in Karnataka.",
    "source": "https://www.myscheme.gov.in/schemes/us",
    "url": "https://www.myscheme.gov.in/schemes/us",
    "kind": "scheme_page",
}


class TestKscsteIdentityRegression(unittest.TestCase):
    """Emergency wrong-scheme retrieval: KSCSTE must never keep PM-SBY evidence."""

    def test_1_kscste_rejects_pmsby(self):
        self.assertFalse(request_accepts_candidate(KSCSTE_Q, PMSBY_DOC))
        kept = filter_evidence_by_scheme(KSCSTE_Q, [PMSBY_DOC])
        self.assertEqual(kept, [])

    def test_2_kscste_accepts_kscste(self):
        self.assertTrue(request_accepts_candidate(KSCSTE_Q, KSCSTE_DOC))
        kept = filter_evidence_by_scheme(KSCSTE_Q, [KSCSTE_DOC, PMSBY_DOC])
        self.assertEqual(len(kept), 1)
        self.assertIn("KSCSTE", kept[0]["scheme_name"])

    def test_3_pm_kisan_accepts_pm_kisan(self):
        self.assertTrue(request_accepts_candidate("Tell me about PM-KISAN", PMKISAN_DOC))
        self.assertTrue(
            request_accepts_candidate(
                "Tell me about Pradhan Mantri Kisan Samman Nidhi", PMKISAN_DOC
            )
        )

    def test_4_pm_kisan_rejects_pmsby(self):
        self.assertFalse(request_accepts_candidate("Tell me about PM-KISAN", PMSBY_DOC))

    def test_5_udyogini_rejects_pmsby(self):
        self.assertFalse(request_accepts_candidate("Tell me about Udyogini", PMSBY_DOC))

    def test_6_udyogini_accepts_udyogini(self):
        self.assertTrue(request_accepts_candidate("Tell me about Udyogini", UDYOGINI_DOC))

    def test_7_pmsby_document_reused_for_pmsby_query(self):
        self.assertTrue(request_accepts_candidate("Tell me about PM-SBY", PMSBY_DOC))
        kept = filter_evidence_by_scheme("Tell me about PM-SBY", [PMSBY_DOC])
        self.assertEqual(len(kept), 1)

    def test_8_pmsby_document_not_reused_for_kscste(self):
        self.assertFalse(request_accepts_candidate(KSCSTE_Q, PMSBY_DOC))

    def test_9_indexed_pmsby_cannot_become_final_evidence(self):
        kept = filter_evidence_by_scheme(KSCSTE_Q, [PMSBY_DOC, PMSBY_DOC])
        self.assertEqual(kept, [])

    def test_10_highest_similarity_still_rejected(self):
        hot = {**PMSBY_DOC, "similarity_score": 0.999, "hybrid_score": 0.999}
        kept = filter_evidence_by_scheme(KSCSTE_Q, [hot, KSCSTE_DOC])
        self.assertEqual(len(kept), 1)
        self.assertIn("KSCSTE", kept[0]["scheme_name"])

    def test_11_conversation_switch_kscste_only(self):
        history = [
            {"role": "user", "content": "Tell me about PM-SBY."},
            {"role": "assistant", "content": "PM-SBY is an accident insurance scheme."},
        ]
        out = rewrite_query(KSCSTE_Q, history)
        rewritten = out.get("rewritten_query") or ""
        self.assertIn("KSCSTE", rewritten.upper())
        self.assertNotIn("PM-SBY", rewritten.upper())
        self.assertNotIn("PMSBY", rewritten.upper())
        self.assertNotIn("Suraksha", rewritten)

    def test_12_kannada_kscste_rejects_pmsby(self):
        q = "KSCSTE Emeritus Scientist Scheme ಬಗ್ಗೆ ವಿವರಗಳು"
        ident = requested_scheme_identity(q)
        self.assertIsNotNone(ident)
        self.assertFalse(request_accepts_candidate(q, PMSBY_DOC))

    def test_13_hindi_kscste_rejects_pmsby(self):
        q = "KSCSTE Emeritus Scientist Scheme के बारे में बताओ"
        ident = requested_scheme_identity(q)
        self.assertIsNotNone(ident)
        self.assertFalse(request_accepts_candidate(q, PMSBY_DOC))

    def test_14_voice_transcribed_kscste_rejects_pmsby(self):
        q = "details about kscste emeritus scientist scheme"
        self.assertFalse(request_accepts_candidate(q, PMSBY_DOC))
        self.assertTrue(request_accepts_candidate(q, KSCSTE_DOC))

    def test_15_wrong_scheme_never_reaches_ollama(self):
        from app.core.config import settings
        from app.services import rag as rag_service

        db = MagicMock()
        with patch.object(rag_service, "hybrid_retrieve", return_value=[PMSBY_DOC]):
            with patch.object(
                rag_service,
                "_call_llm_after_validation",
                return_value="SHOULD_NOT_RUN",
            ) as llm:
                prev = settings.LIVE_GOV_FALLBACK_ENABLED
                settings.LIVE_GOV_FALLBACK_ENABLED = False
                try:
                    out = rag_service.answer_with_evidence_gate(
                        db, KSCSTE_Q, top_k=3, enable_live_fallback=False
                    )
                finally:
                    settings.LIVE_GOV_FALLBACK_ENABLED = prev
        llm.assert_not_called()
        self.assertFalse(out.get("llm_invoked"))
        answer = (out.get("answer") or "").lower()
        self.assertNotIn("suraksha", answer)
        self.assertNotIn("pm-sby", answer)

    def test_generic_topic_does_not_force_identity(self):
        self.assertIsNone(requested_scheme_identity("financial help for farmers"))

    def test_ingest_rejects_pmsby_without_partial(self):
        from io import StringIO

        from app.services.live_gov_retrieval_service import LiveGovRetrievalService

        svc = LiveGovRetrievalService(db=MagicMock())
        ingested = []
        buf = StringIO()
        with patch(
            "app.services.live_gov_retrieval_service.verify_source", return_value=True
        ):
            with patch.object(svc, "ingest_verified_document") as ingest:
                with patch("sys.stdout", buf):
                    out = svc._ingest_ranked_until_sufficient(
                        [PMSBY_DOC],
                        search_q=KSCSTE_Q,
                        rid="kscste-identity",
                        overall_deadline=1e18,
                        per_source=30.0,
                        phase="myscheme",
                        ingested=ingested,
                        rejected_urls=[],
                        failure_codes=[],
                        pdfs_used=0,
                        max_pdfs=2,
                    )
        ingest.assert_not_called()
        self.assertFalse(out.get("evidence_ready"))
        logs = buf.getvalue()
        self.assertIn("MYSCHEME_IDENTITY_CHECK", logs)
        self.assertIn("REJECT", logs)
        self.assertIn("MYSCHEME_CANDIDATE_REJECTED", logs)
        self.assertIn("SCHEME_IDENTITY_MISMATCH", logs)
        self.assertNotIn("MYSCHEME_PARTIAL", logs)
        self.assertNotIn("MYSCHEME_DUPLICATE_REUSED", logs)

    def test_select_best_drops_wrong_scheme(self):
        from app.services.live_gov_retrieval_service import select_best_candidates

        with patch(
            "app.services.live_gov_retrieval_service.verify_source", return_value=True
        ):
            ranked = select_best_candidates(
                [PMSBY_DOC, KSCSTE_DOC],
                KSCSTE_Q,
                limit=5,
            )
        urls = [c.get("url") for c in ranked]
        self.assertTrue(any("kscste" in (u or "").lower() for u in urls))
        self.assertFalse(any("pmsby" in (u or "").lower() for u in urls))


class TestQuestionAwareEvidence(unittest.TestCase):
    def test_eligibility_prefers_eligibility_section(self):
        docs = [
            {
                "scheme_name": "Udyogini Scheme",
                "content": "SECTION:\nBenefits\n\nCONTENT:\n50% subsidy on the loan amount.",
                "source": "https://www.myscheme.gov.in/schemes/us",
            },
            {
                "scheme_name": "Udyogini Scheme",
                "content": "SECTION:\nEligibility\n\nCONTENT:\nWomen entrepreneurs with family income below 1.5 lakh.",
                "source": "https://www.myscheme.gov.in/schemes/us",
            },
            {
                "scheme_name": "Udyogini Scheme",
                "content": "SECTION:\nDocuments Required\n\nCONTENT:\nAadhaar and caste certificate.",
                "source": "https://www.myscheme.gov.in/schemes/us",
            },
        ]
        self.assertEqual(query_citizen_intent("Who is eligible for Udyogini?"), "eligibility")
        kept = select_question_aware_evidence("Who is eligible for Udyogini?", docs)
        blob = " ".join(d["content"] for d in kept).lower()
        self.assertIn("eligibility", blob)
        self.assertTrue(any("women entrepreneurs" in (d["content"] or "").lower() for d in kept))

    def test_overview_intent_for_what_is(self):
        self.assertEqual(query_citizen_intent("What is PM-KISAN?"), "overview")
        self.assertEqual(
            query_citizen_intent("Can I get details about Udyogini Scheme?"),
            "complete",
        )

    def test_kannada_and_hindi_intent(self):
        self.assertEqual(query_citizen_intent("ಶಕ್ತಿ ಯೋಜನೆಗೆ ಯಾರು ಅರ್ಹರು?"), "eligibility")
        self.assertEqual(query_citizen_intent("उद्योगिनी योजना के लाभ क्या हैं?"), "benefits")

    def test_pdf_chunk_kept_with_eligibility(self):
        docs = [
            {
                "scheme_name": "Udyogini Scheme",
                "content": "SECTION:\nEligibility\n\nCONTENT:\nWomen entrepreneurs.",
                "source": "https://www.myscheme.gov.in/schemes/us",
            },
            {
                "scheme_name": "Udyogini Scheme",
                "content": "Family income should not exceed Rs 1.5 lakh per annum.",
                "source": "https://www.myscheme.gov.in/files/udyogini.pdf",
                "document_type": "LIVE_PDF",
            },
        ]
        kept = select_question_aware_evidence("Who is eligible for Udyogini?", docs)
        sources = [d.get("source") for d in kept]
        self.assertIn("https://www.myscheme.gov.in/files/udyogini.pdf", sources)

    def test_pdf_candidate_inherits_scheme_not_pmsby(self):
        pdf = {
            "url": "https://www.myscheme.gov.in/files/udyogini-guidelines.pdf",
            "kind": "pdf_link",
            "scheme_id": "us",
            "scheme_name": "Udyogini Scheme",
            "content": "Udyogini eligibility guidelines for women entrepreneurs.",
        }
        self.assertTrue(request_accepts_candidate("Udyogini eligibility", pdf))
        self.assertFalse(request_accepts_candidate("Udyogini eligibility", PMSBY_DOC))


if __name__ == "__main__":
    unittest.main()
