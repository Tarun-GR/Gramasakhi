"""Reliability hardening tests for live government acquisition."""

from __future__ import annotations

import time
import unittest
from unittest.mock import MagicMock, patch

from app.services.acquisition.base import AcquisitionMethod, AcquisitionResult, SourceHealth
from app.services.acquisition.orchestrator import SourceAcquisitionOrchestrator
from app.services.acquisition.reliability import (
    FailureCode,
    get_capability,
    get_health,
    record_acquire,
    reset_reliability_state_for_tests,
    set_health,
)
from app.services.live_gov_retrieval_service import (
    expand_search_query,
    is_freshness_sensitive,
    score_candidate,
    select_best_candidates,
    verify_source,
)


class TestHealthCooldown(unittest.TestCase):
    def setUp(self):
        reset_reliability_state_for_tests()

    def test_cooldown_blocks_then_expires(self):
        url = "https://nha.gov.in/blocked"
        set_health(
            url,
            SourceHealth.CAPTCHA_BLOCKED,
            failure_code=FailureCode.CAPTCHA_BLOCKED,
            cooldown_seconds=0.2,
        )
        self.assertEqual(get_health(url), SourceHealth.CAPTCHA_BLOCKED)
        time.sleep(0.25)
        self.assertIsNone(get_health(url))

    def test_orchestrator_respects_cooldown(self):
        url = "https://nha.gov.in/login-wall"
        set_health(url, SourceHealth.LOGIN_REQUIRED, cooldown_seconds=60)
        web = MagicMock()
        orch = SourceAcquisitionOrchestrator(web)
        out = orch.acquire(url, verify_fn=verify_source)
        self.assertFalse(out.ok)
        self.assertEqual(out.health, SourceHealth.LOGIN_REQUIRED)
        self.assertEqual(out.meta.get("failure_code"), FailureCode.COOLDOWN_ACTIVE.value)
        web.fetch_url.assert_not_called()


class TestCapabilityLearning(unittest.TestCase):
    def setUp(self):
        reset_reliability_state_for_tests()

    def test_nha_seed_prefers_browser(self):
        cap = get_capability("https://nha.gov.in/")
        self.assertEqual(cap.preferred_strategy, "browser_js")

    def test_pmkisan_seed_prefers_static(self):
        cap = get_capability("https://pmkisan.gov.in/")
        self.assertEqual(cap.preferred_strategy, "static_http")

    def test_learning_updates_preferred_strategy(self):
        url = "https://example-learn.gov.in/page"
        # seed unknown host as static
        for _ in range(4):
            record_acquire(
                url,
                method=AcquisitionMethod.BROWSER_JS,
                ok=True,
                latency_ms=100,
                health=SourceHealth.HEALTHY,
            )
        self.assertEqual(get_capability(url).preferred_strategy, "browser_js")


class TestStaticToBrowserEscalation(unittest.TestCase):
    def setUp(self):
        reset_reliability_state_for_tests()

    def test_static_fail_browser_success(self):
        web = MagicMock()
        web.fetch_url.side_effect = Exception("502 Bad Gateway")
        orch = SourceAcquisitionOrchestrator(web)
        browser_res = AcquisitionResult(
            url="https://nha.gov.in/",
            content=b"<html><body>" + (b"Ayushman Bharat scheme eligibility " * 20) + b"</body></html>",
            content_type="text/html",
            final_url="https://nha.gov.in/",
            method=AcquisitionMethod.BROWSER_JS,
            health=SourceHealth.HEALTHY,
            rendered_text="Ayushman Bharat scheme eligibility " * 20,
            discovered_links=[
                {
                    "url": "https://nha.gov.in/a.pdf",
                    "link_text": "guidelines",
                    "kind": "document_link",
                }
            ],
        )
        with patch.object(orch.browser, "fetch", return_value=browser_res):
            with patch(
                "app.services.acquisition.orchestrator.playwright_available",
                return_value=True,
            ):
                out = orch.acquire("https://nha.gov.in/", verify_fn=verify_source)
        self.assertTrue(out.ok)
        self.assertEqual(out.method, AcquisitionMethod.BROWSER_JS)


class TestFailureInjectionRanking(unittest.TestCase):
    def test_irrelevant_then_relevant_ordering(self):
        cands = [
            {
                "url": "https://pmkisan.gov.in/Documents/holidays-list.pdf",
                "kind": "pdf_link",
                "link_text": "holiday list",
            },
            {
                "url": "https://pmkisan.gov.in/Documents/RevisedFAQ.pdf",
                "kind": "pdf_link",
                "link_text": "PM-KISAN eligibility FAQ",
            },
        ]
        ranked = select_best_candidates(
            cands, "What are PM-KISAN eligibility criteria?", limit=5
        )
        self.assertTrue(ranked)
        self.assertIn("RevisedFAQ", ranked[0]["url"])

    def test_freshness_boosts_dated_pdf(self):
        self.assertTrue(is_freshness_sensitive("What is the latest 2026 PM-KISAN benefit?"))
        dated = score_candidate(
            "https://pmkisan.gov.in/Documents/guidelines-2026.pdf",
            "What is the latest 2026 PM-KISAN benefit?",
            link_text="latest revised guidelines 2026",
        )
        old = score_candidate(
            "https://pmkisan.gov.in/",
            "What is the latest 2026 PM-KISAN benefit?",
            link_text="home",
        )
        self.assertGreater(dated, old)


class TestMultilingualExpand(unittest.TestCase):
    def test_hindi_expands_ayushman(self):
        out = expand_search_query("आयुष्मान योजना के लाभ क्या हैं")
        self.assertIn("ayushman", out.lower())
        self.assertIn("scheme", out.lower())

    def test_kannada_expands_eligibility(self):
        out = expand_search_query("ಪಿಎಂಕಿಸಾನ್ ಅರ್ಹತೆ")
        self.assertIn("pm-kisan", out.lower())
        self.assertIn("eligibility", out.lower())


class TestHtmlShellRejection(unittest.TestCase):
    def setUp(self):
        reset_reliability_state_for_tests()

    def test_pdf_url_html_shell_escalates_to_browser(self):
        web = MagicMock()
        web.fetch_url.return_value = (b"<!DOCTYPE html><html></html>", "text/html")
        web.extract_text_from_html.return_value = ""
        orch = SourceAcquisitionOrchestrator(web)
        browser_res = AcquisitionResult(
            url="https://nha.gov.in/x.pdf",
            content=b"%PDF-1.4 fake",
            content_type="application/pdf",
            final_url="https://nha.gov.in/x.pdf",
            method=AcquisitionMethod.DYNAMIC_DOWNLOAD,
            health=SourceHealth.HEALTHY,
        )
        with patch.object(orch.browser, "fetch", return_value=browser_res):
            with patch(
                "app.services.acquisition.orchestrator.playwright_available",
                return_value=True,
            ):
                out = orch.acquire(
                    "https://nha.gov.in/x.pdf", verify_fn=verify_source
                )
        self.assertTrue(out.ok)
        self.assertEqual(out.content[:4], b"%PDF")


if __name__ == "__main__":
    unittest.main()
