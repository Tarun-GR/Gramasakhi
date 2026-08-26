"""Acquisition orchestrator unit tests — local fixtures, no live gov sites."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch  # noqa: F401

from app.services.acquisition.base import SourceHealth, detect_access_block
from app.services.acquisition.orchestrator import SourceAcquisitionOrchestrator
from app.services.acquisition.static_http import (
    StaticHttpAcquisition,
    discover_document_links,
    discover_pagination_links,
    discover_public_api_hints,
    public_api_bytes_to_text,
)
from app.services.live_gov_retrieval_service import verify_source

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "acquisition"


def _read(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


class TestAccessDetection(unittest.TestCase):
    def test_login_detected(self):
        html = _read("login_page.html").decode("utf-8")
        self.assertEqual(detect_access_block(html), SourceHealth.LOGIN_REQUIRED)

    def test_captcha_detected(self):
        html = _read("captcha_page.html").decode("utf-8")
        self.assertEqual(detect_access_block(html), SourceHealth.CAPTCHA_BLOCKED)

    def test_static_portal_not_blocked(self):
        html = _read("static_portal.html").decode("utf-8")
        self.assertIsNone(detect_access_block(html))


class TestDocumentLinkDiscovery(unittest.TestCase):
    def test_finds_pdf_links_and_rejects_untrusted(self):
        html = _read("static_portal.html").decode("utf-8")
        links = discover_document_links(
            "https://nha.gov.in/portal",
            html,
            verify_fn=verify_source,
        )
        urls = [l["url"] for l in links]
        self.assertTrue(any(u.endswith("scheme-guidelines.pdf") for u in urls))
        self.assertFalse(any("evil.example.com" in u for u in urls))


class TestStaticAcquisition(unittest.TestCase):
    def test_static_html_with_links(self):
        web = MagicMock()
        web.fetch_url.return_value = (_read("static_portal.html"), "text/html")
        web.extract_text_from_html.return_value = (
            "Government Scheme Guidelines. This is a static HTML portal with enough "
            "text for extraction and a direct PDF link about eligibility and benefits."
        )
        acq = StaticHttpAcquisition(web)
        res = acq.fetch("https://nha.gov.in/portal", verify_fn=verify_source)
        self.assertTrue(res.ok)
        self.assertGreaterEqual(len(res.discovered_links), 1)
        self.assertGreater(len(res.rendered_text or ""), 50)

    def test_login_page_blocked(self):
        web = MagicMock()
        web.fetch_url.return_value = (_read("login_page.html"), "text/html")
        acq = StaticHttpAcquisition(web)
        res = acq.fetch("https://nha.gov.in/login", verify_fn=verify_source)
        self.assertFalse(res.ok)
        self.assertEqual(res.health, SourceHealth.LOGIN_REQUIRED)

    def test_direct_pdf(self):
        web = MagicMock()
        web.fetch_url.return_value = (b"%PDF-1.4 fake", "application/pdf")
        acq = StaticHttpAcquisition(web)
        res = acq.fetch(
            "https://nha.gov.in/img/resources/x.pdf", verify_fn=verify_source
        )
        self.assertTrue(res.ok)
        self.assertEqual(res.method.value, "direct_document")


class TestOrchestratorEscalation(unittest.TestCase):
    def test_spa_bootstrap_pdf_accepted_via_static_level2(self):
        """Bare PDF URLs in SPA bootstrap scripts are Level-2 discovery — no browser."""
        web = MagicMock()
        web.fetch_url.return_value = (_read("spa_shell.html"), "text/html")
        web.extract_text_from_html.return_value = "app"
        orch = SourceAcquisitionOrchestrator(web)
        out = orch.acquire("https://nha.gov.in/", verify_fn=verify_source)
        self.assertTrue(out.ok)
        self.assertEqual(out.method.value, "static_http")
        self.assertTrue(any(l["url"].endswith(".pdf") for l in out.discovered_links))

    def test_low_content_triggers_browser_when_available(self):
        web = MagicMock()
        web.fetch_url.return_value = (_read("spa_shell_empty.html"), "text/html")
        web.extract_text_from_html.return_value = "app"  # too short

        orch = SourceAcquisitionOrchestrator(web)
        browser_res = MagicMock()
        browser_res.ok = True
        browser_res.content = b"<html><body>Rendered Ayushman Bharat PM-JAY scheme details " + (
            b"eligibility benefits coverage " * 20
        ) + b"</body></html>"
        browser_res.content_type = "text/html"
        browser_res.final_url = "https://nha.gov.in/"
        browser_res.health = SourceHealth.HEALTHY
        browser_res.method.value = "browser_js"
        browser_res.discovered_links = [
            {
                "url": "https://nha.gov.in/img/resources/sample.pdf",
                "link_text": "sample",
                "kind": "document_link",
            }
        ]
        browser_res.rendered_text = "Rendered Ayushman Bharat PM-JAY " + ("coverage " * 40)
        browser_res.error = None

        with patch.object(orch.browser, "fetch", return_value=browser_res):
            with patch(
                "app.services.acquisition.orchestrator.playwright_available",
                return_value=True,
            ):
                out = orch.acquire(
                    "https://nha.gov.in/",
                    verify_fn=verify_source,
                    query="Ayushman Bharat",
                )
        self.assertTrue(out.ok)
        self.assertEqual(out.method.value, "browser_js")
        self.assertTrue(out.discovered_links)

    def test_browser_unavailable_returns_js_required(self):
        web = MagicMock()
        web.fetch_url.return_value = (_read("spa_shell_empty.html"), "text/html")
        web.extract_text_from_html.return_value = "x"
        orch = SourceAcquisitionOrchestrator(web)
        with patch(
            "app.services.acquisition.orchestrator.playwright_available",
            return_value=False,
        ):
            out = orch.acquire("https://nha.gov.in/", verify_fn=verify_source)
        self.assertFalse(out.ok)
        self.assertEqual(out.health, SourceHealth.JS_REQUIRED)


class TestTrustedRedirects(unittest.TestCase):
    def test_ssrf_hosts_rejected_by_verify(self):
        self.assertFalse(verify_source("http://127.0.0.1/secret"))
        self.assertFalse(verify_source("http://169.254.169.254/latest/meta-data"))
        self.assertFalse(verify_source("https://evil.com/x.pdf"))


class TestPaginationAndApiDiscovery(unittest.TestCase):
    def test_pagination_next_link(self):
        html = _read("pagination_portal.html").decode("utf-8")
        pages = discover_pagination_links(
            "https://nha.gov.in/docs", html, verify_fn=verify_source
        )
        self.assertTrue(any("page=2" in p for p in pages))

    def test_iframe_pdf_discovered(self):
        html = _read("iframe_viewer.html").decode("utf-8")
        links = discover_document_links(
            "https://nha.gov.in/viewer", html, verify_fn=verify_source
        )
        self.assertTrue(any("viewer-guidelines.pdf" in l["url"] for l in links))

    def test_public_api_hints(self):
        html = _read("public_api_portal.html").decode("utf-8")
        hints = discover_public_api_hints(
            "https://nha.gov.in/portal", html, verify_fn=verify_source
        )
        self.assertTrue(any(h["kind"] == "public_api" for h in hints))

    def test_public_api_json_to_text(self):
        payload = b'{"scheme":"Ayushman Bharat","eligibility":"SECC households"}'
        text = public_api_bytes_to_text(payload, "application/json")
        self.assertIn("Ayushman Bharat", text)
        self.assertIn("eligibility", text.lower())

    def test_captcha_acquisition_blocked(self):
        web = MagicMock()
        web.fetch_url.return_value = (_read("captcha_page.html"), "text/html")
        acq = StaticHttpAcquisition(web)
        res = acq.fetch("https://nha.gov.in/challenge", verify_fn=verify_source)
        self.assertFalse(res.ok)
        self.assertEqual(res.health, SourceHealth.CAPTCHA_BLOCKED)


class TestRelativeAndNestedPdf(unittest.TestCase):
    def test_relative_pdf_normalized(self):
        html = _read("static_portal.html").decode("utf-8")
        links = discover_document_links(
            "https://nha.gov.in/portal/schemes/", html, verify_fn=verify_source
        )
        urls = [l["url"] for l in links]
        self.assertTrue(any(u.startswith("https://nha.gov.in/") and u.endswith(".pdf") for u in urls))
        self.assertTrue(any("eligibility.pdf" in u for u in urls))


if __name__ == "__main__":
    unittest.main()
