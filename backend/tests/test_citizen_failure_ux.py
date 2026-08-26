"""Citizen-facing live failure UX tests."""

from __future__ import annotations

import unittest

from app.services.acquisition.reliability import FailureCode
from app.services.citizen_failure_ux import (
    CAPTCHA_BLOCKED,
    DOCUMENT_NOT_FOUND,
    INFORMATION_NOT_FOUND,
    LOGIN_REQUIRED,
    SOURCE_UNAVAILABLE,
    TIMEOUT,
    TRUSTED_SOURCES_EXHAUSTED,
    build_citizen_live_failure,
    build_official_sources,
    choose_citizen_status,
    citizen_messages,
    map_failure_code,
)


class TestStatusMapping(unittest.TestCase):
    def test_all_requested_statuses_have_english_messages(self):
        statuses = [
            INFORMATION_NOT_FOUND,
            SOURCE_UNAVAILABLE,
            TIMEOUT,
            CAPTCHA_BLOCKED,
            LOGIN_REQUIRED,
            "authorization_required",
            "javascript_unavailable",
            DOCUMENT_NOT_FOUND,
            "document_unreadable",
            "ocr_failed",
            "api_unavailable",
            "source_conflict",
            TRUSTED_SOURCES_EXHAUSTED,
            "temporary_failure",
        ]
        for status in statuses:
            msg = citizen_messages(status, "en")
            self.assertTrue(msg["answer"])
            self.assertTrue(msg["live_reason"])
            self.assertNotIn("does not exist", msg["answer"].lower())

    def test_captcha_and_login_mapping(self):
        self.assertEqual(map_failure_code(FailureCode.CAPTCHA_BLOCKED), CAPTCHA_BLOCKED)
        self.assertEqual(map_failure_code(FailureCode.LOGIN_REQUIRED), LOGIN_REQUIRED)
        self.assertEqual(map_failure_code(FailureCode.TIMEOUT), TIMEOUT)

    def test_priority_prefers_captcha_over_timeout(self):
        status = choose_citizen_status(
            [FailureCode.TIMEOUT, FailureCode.CAPTCHA_BLOCKED]
        )
        self.assertEqual(status, CAPTCHA_BLOCKED)

    def test_hindi_and_kannada_messages(self):
        hi = citizen_messages(CAPTCHA_BLOCKED, "hi")
        kn = citizen_messages(CAPTCHA_BLOCKED, "kn")
        self.assertIn("CAPTCHA", hi["answer"])
        self.assertIn("CAPTCHA", kn["answer"])
        self.assertNotEqual(hi["answer"], citizen_messages(CAPTCHA_BLOCKED, "en")["answer"])


class TestOfficialSources(unittest.TestCase):
    def test_rejects_untrusted_and_localhost(self):
        sources = build_official_sources(
            "PM-KISAN eligibility",
            extra_urls=[
                {
                    "url": "https://evil.example.com/scheme",
                    "name": "Evil",
                    "scheme_name": "Evil",
                },
                {
                    "url": "http://127.0.0.1/secret",
                    "name": "Local",
                    "scheme_name": "Local",
                },
                {
                    "url": "https://pmkisan.gov.in/",
                    "name": "PM-KISAN",
                    "scheme_name": "PM-KISAN",
                },
            ],
            limit=3,
        )
        urls = [s["url"] for s in sources]
        self.assertTrue(all(u.startswith("https://") for u in urls))
        self.assertFalse(any("evil.example.com" in u for u in urls))
        self.assertFalse(any("127.0.0.1" in u for u in urls))
        self.assertLessEqual(len(sources), 3)

    def test_never_invents_urls_when_no_seeds(self):
        sources = build_official_sources(
            "zzzz-nonexistent-scheme-xyz",
            extra_urls=[],
            limit=3,
        )
        # May be empty or only trusted registry/portal seeds — never invented hosts
        for s in sources:
            self.assertTrue(s["url"].startswith("https://"))
            self.assertIn(".", s["url"])


class TestCitizenPayload(unittest.TestCase):
    def test_captcha_payload(self):
        ux = build_citizen_live_failure(
            "Gruha Lakshmi benefits Karnataka",
            language="en",
            failure_codes=[FailureCode.CAPTCHA_BLOCKED],
        )
        self.assertEqual(ux["live_status"], CAPTCHA_BLOCKED)
        self.assertIn("CAPTCHA", ux["answer"])
        self.assertIn("live_reason", ux)
        self.assertEqual(ux["knowledge_source"], "none")
        self.assertFalse(ux["validated"])
        self.assertLessEqual(len(ux["official_sources"]), 3)

    def test_login_payload_hindi(self):
        ux = build_citizen_live_failure(
            "आयुष्मान योजना",
            language="hi",
            failure_codes=[FailureCode.LOGIN_REQUIRED],
        )
        self.assertEqual(ux["live_status"], LOGIN_REQUIRED)
        self.assertIn("लॉगिन", ux["answer"])

    def test_exhausted_sources(self):
        ux = build_citizen_live_failure(
            "PM-KISAN eligibility",
            failure_codes=[],
            candidates_tried=4,
            ingested_count=0,
        )
        self.assertIn(
            ux["live_status"],
            {DOCUMENT_NOT_FOUND, TRUSTED_SOURCES_EXHAUSTED, INFORMATION_NOT_FOUND},
        )


if __name__ == "__main__":
    unittest.main()
