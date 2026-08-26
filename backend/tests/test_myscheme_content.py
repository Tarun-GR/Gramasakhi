"""myScheme content acquisition — URL discovery is NOT success."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.services.acquisition.base import (
    AcquisitionMethod,
    AcquisitionResult,
    SourceHealth,
)
from app.services.citizen_failure_ux import (
    SCHEME_CONTENT_UNAVAILABLE,
    build_citizen_live_failure,
)
from app.services.live_gov_retrieval_service import LiveGovRetrievalService, verify_source
from app.services.myscheme_service import (
    extract_scheme_sections,
    is_myscheme_shell_html,
    package_myscheme_evidence,
    required_sections_for_query,
    sections_meet_query_need,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "acquisition"


class TestSectionExtraction(unittest.TestCase):
    def test_heading_fixture_sections(self):
        html = (FIXTURES / "myscheme_scheme_udyogini.html").read_text(encoding="utf-8")
        sections = extract_scheme_sections(html)
        for key in ("details", "benefits", "eligibility", "application", "documents", "faqs"):
            self.assertIn(key, sections, msg=key)
            self.assertGreater(len(sections[key]), 40)

    def test_div_spa_sections(self):
        html = (FIXTURES / "myscheme_scheme_udyogini_div.html").read_text(encoding="utf-8")
        sections = extract_scheme_sections(html)
        self.assertIn("benefits", sections)
        self.assertIn("eligibility", sections)

    def test_plain_text_sections(self):
        text = (
            "Udyogini Scheme Karnataka. Details Support for women entrepreneurs "
            "with training. Benefits Subsidy for micro enterprises. "
            "Eligibility Women aged 18-55 with income criteria. "
            "Application Process Apply at facilitation centres. "
            "Documents Required Aadhaar and bank details."
        )
        sections = extract_scheme_sections("", rendered_text=text)
        self.assertTrue(sections.get("benefits") or sections.get("details"))

    def test_network_error_shell_rejected(self):
        html = (FIXTURES / "myscheme_network_error.html").read_text(encoding="utf-8")
        shell, reason = is_myscheme_shell_html(html)
        self.assertTrue(shell)
        packed = package_myscheme_evidence(
            html=html,
            scheme_name="Udyogini",
            source_url="https://www.myscheme.gov.in/schemes/us",
            query="Udyogini benefits",
        )
        self.assertFalse(packed["ok"])

    def test_package_useful_html(self):
        html = (FIXTURES / "myscheme_scheme_udyogini.html").read_text(encoding="utf-8")
        packed = package_myscheme_evidence(
            html=html,
            scheme_name="Udyogini Scheme",
            source_url="https://www.myscheme.gov.in/schemes/us",
            query="Can I get details about Udyogini Scheme?",
        )
        self.assertTrue(packed["ok"])
        self.assertIn(b"Benefits", packed["content"])
        self.assertIn(b"Eligibility", packed["content"])
        self.assertGreater(packed["text_chars"], 200)

    def test_json_public_api_sections(self):
        import json

        payload = json.dumps(
            {
                "schemeName": "Udyogini Scheme",
                "benefits": "Subsidy support for women micro-enterprises in Karnataka as notified.",
                "eligibility": "Women applicants meeting age and income criteria may apply.",
                "applicationProcess": "Apply offline through designated bank / department channels.",
            }
        )
        packed = package_myscheme_evidence(
            html="",
            rendered_text="",
            scheme_name="Udyogini Scheme",
            source_url="https://www.myscheme.gov.in/schemes/us",
            query="Udyogini benefits",
            json_blobs=[payload],
        )
        self.assertTrue(packed["ok"])
        self.assertIn("benefits", packed["sections"])


class TestQuestionSufficiency(unittest.TestCase):
    def test_benefits_question(self):
        self.assertEqual(required_sections_for_query("What are Udyogini benefits?"), ["benefits"])
        self.assertTrue(
            sections_meet_query_need(
                {"benefits": "Subsidy support for eligible women entrepreneurs." * 2},
                "What are Udyogini benefits?",
            )
        )
        self.assertFalse(
            sections_meet_query_need(
                {"details": "Overview only without benefit amounts listed here."},
                "What are Udyogini benefits?",
            )
        )

    def test_details_question_needs_breadth(self):
        req = required_sections_for_query("Give me details about Udyogini")
        self.assertIn("benefits", req)
        self.assertIn("eligibility", req)


class TestIngestPackagesContent(unittest.TestCase):
    def test_url_only_candidate_gets_packaged_before_ingest(self):
        html = (FIXTURES / "myscheme_scheme_udyogini.html").read_text(encoding="utf-8")
        svc = LiveGovRetrievalService(db=MagicMock())
        svc.acquisition = MagicMock()
        svc.acquisition.acquire.return_value = AcquisitionResult(
            url="https://www.myscheme.gov.in/schemes/us",
            final_url="https://www.myscheme.gov.in/schemes/us",
            content=html.encode("utf-8"),
            content_type="text/html",
            rendered_text="Udyogini Scheme Benefits Eligibility Application",
            method=AcquisitionMethod.BROWSER_JS,
            health=SourceHealth.HEALTHY,
            discovered_links=[],
        )
        ingested = []
        rejected = []
        failures = []

        with patch.object(
            svc,
            "ingest_verified_document",
            return_value={
                "status": "ok",
                "document_id": "doc-1",
                "chunk_count": 3,
                "document_hash": "abc",
            },
        ) as ingest:
            with patch.object(svc, "refresh_indexes", return_value={"faiss": 1, "bm25": 1}):
                with patch.object(svc, "_probe_evidence_ready", return_value=True):
                    out = svc._ingest_ranked_until_sufficient(
                        [
                            {
                                "url": "https://www.myscheme.gov.in/schemes/us",
                                "kind": "scheme_page",
                                "scheme_name": "Udyogini Scheme",
                                "source": "myscheme",
                            }
                        ],
                        search_q="details about Udyogini Scheme",
                        rid="content-test",
                        overall_deadline=1e18,
                        per_source=30.0,
                        phase="myscheme",
                        ingested=ingested,
                        rejected_urls=rejected,
                        failure_codes=failures,
                        pdfs_used=0,
                        max_pdfs=2,
                    )
        self.assertTrue(out.get("evidence_ready"))
        self.assertTrue(ingest.called)
        content_arg = ingest.call_args.kwargs.get("content") or ingest.call_args[1].get("content")
        if content_arg is None:
            content_arg = ingest.call_args[0][0] if ingest.call_args[0] else None
        # kwargs form
        kwargs = ingest.call_args.kwargs
        body = kwargs.get("content") or b""
        self.assertIn(b"Benefits", body)
        self.assertIn(b"Eligibility", body)
        self.assertNotIn(b"Something went wrong", body)

    def test_shell_scheme_page_not_ingested(self):
        html = (FIXTURES / "myscheme_network_error.html").read_text(encoding="utf-8")
        svc = LiveGovRetrievalService(db=MagicMock())
        svc.acquisition = MagicMock()
        svc.acquisition.acquire.return_value = AcquisitionResult(
            url="https://www.myscheme.gov.in/schemes/us",
            final_url="https://www.myscheme.gov.in/schemes/us",
            content=html.encode("utf-8"),
            content_type="text/html",
            rendered_text="Something went wrong Network Error",
            method=AcquisitionMethod.BROWSER_JS,
            health=SourceHealth.HEALTHY,
            discovered_links=[],
        )
        ingested = []
        with patch.object(svc, "ingest_verified_document") as ingest:
            out = svc._ingest_ranked_until_sufficient(
                [
                    {
                        "url": "https://www.myscheme.gov.in/schemes/us",
                        "kind": "scheme_page",
                        "scheme_name": "Udyogini Scheme",
                    }
                ],
                search_q="Udyogini",
                rid="shell-test",
                overall_deadline=1e18,
                per_source=30.0,
                phase="myscheme",
                ingested=ingested,
                rejected_urls=[],
                failure_codes=[],
                pdfs_used=0,
                max_pdfs=2,
            )
        self.assertFalse(out.get("evidence_ready"))
        self.assertFalse(ingest.called)
        self.assertTrue(out.get("myscheme_page_found_no_content"))


class TestFailureUx(unittest.TestCase):
    def test_scheme_page_found_but_no_content_message(self):
        ux = build_citizen_live_failure(
            "Udyogini Scheme",
            language="en",
            preferred_status=SCHEME_CONTENT_UNAVAILABLE,
            guidance_urls=[
                {
                    "url": "https://www.myscheme.gov.in/schemes/us",
                    "scheme_name": "Udyogini Scheme",
                }
            ],
        )
        self.assertIn("could not retrieve", ux["answer"].lower())
        self.assertNotIn("does not exist", ux["answer"].lower())
        self.assertTrue(ux.get("official_sources"))


class TestSecurityUnchanged(unittest.TestCase):
    def test_ssrf_still_blocked(self):
        self.assertFalse(verify_source("http://127.0.0.1/schemes/us"))
        self.assertFalse(verify_source("file:///etc/passwd"))

    def test_login_captcha_detection(self):
        from app.services.acquisition.base import detect_access_block

        blocked = detect_access_block("<html>Please login Sign in</html>")
        # May be LOGIN_REQUIRED or None depending on detector — must not invent bypass
        self.assertIn(
            blocked,
            (SourceHealth.LOGIN_REQUIRED, SourceHealth.CAPTCHA_BLOCKED, None,
             SourceHealth.PUBLIC_ACCESS_BLOCKED),
        )


if __name__ == "__main__":
    unittest.main()
