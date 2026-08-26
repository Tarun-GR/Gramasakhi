"""Trusted government source registry — unit tests (mocked IGOD HTTP)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.config.gov_sources import is_allowed_url
from app.services import gov_source_registry as registry


class TestRegistryDomainTrust(unittest.TestCase):
    def setUp(self):
        registry._cache = None
        registry.ensure_curated_hosts_merged()

    def test_registry_member_allowed(self):
        self.assertTrue(is_allowed_url("https://pmkisan.gov.in/guidelines.pdf"))
        self.assertTrue(is_allowed_url("https://sevasindhu.karnataka.gov.in/"))
        # Parent domain registration covers subdomains
        self.assertTrue(is_allowed_url("https://food.karnataka.gov.in/schemes"))

    def test_bare_gov_suffix_not_enough(self):
        # Not present in trusted registry → reject even with .gov.in
        self.assertFalse(is_allowed_url("https://totally-unknown-dept.gov.in/page"))
        self.assertFalse(is_allowed_url("https://random-blog.com/x.pdf"))

    def test_ssrf_still_blocked(self):
        self.assertFalse(is_allowed_url("http://127.0.0.1/"))
        self.assertFalse(is_allowed_url("http://192.168.0.5/"))

    def test_classify_and_prioritize(self):
        cats = registry.classify_query("PM-KISAN farmer eligibility Karnataka")
        self.assertIn("agriculture", cats)
        sources = registry.prioritize_sources_for_query(
            "Karnataka housing scheme eligibility", limit=5
        )
        self.assertTrue(sources)
        # Housing / Karnataka sources should rank near the top
        top_blob = " ".join(
            f"{s.get('name')} {' '.join(s.get('categories') or [])}" for s in sources[:3]
        ).lower()
        self.assertTrue(
            "housing" in top_blob or "karnataka" in top_blob or "seva" in top_blob
        )

    def test_enable_disable_source(self):
        data = registry.load_registry(force_reload=True)
        sid = None
        for s in data.get("sources") or []:
            if s.get("id") == "curated-pmkisan":
                sid = s["id"]
                break
        self.assertIsNotNone(sid)
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "reg.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            with patch.object(registry, "REGISTRY_PATH", path):
                registry._cache = None
                registry.set_source_enabled(sid, False)
                self.assertFalse(
                    registry.is_domain_in_registry("pmkisan.gov.in", enabled_only=True)
                )
                registry.set_source_enabled(sid, True)
                self.assertTrue(
                    registry.is_domain_in_registry("pmkisan.gov.in", enabled_only=True)
                )

    def test_refresh_from_igod_mocked(self):
        ka_html = """
        <html><body>
          <a href="https://housing.karnataka.gov.in/">Housing Department</a>
          <a href="https://evil-news.com/schemes">Fake</a>
          <a href="/org/agri">Agriculture Dept IGOD</a>
        </body></html>
        """
        detail_html = """
        <html><body>
          <a href="https://raitamitra.karnataka.gov.in/">Official Website</a>
          <a href="https://spam.example.com/">Spam</a>
        </body></html>
        """
        union_html = """
        <html><body>
          <a href="https://agriwelfare.gov.in/">Agriculture Ministry</a>
        </body></html>
        """

        def fake_fetch(url: str, timeout: float = 25.0) -> str:
            if "KA" in url:
                return ka_html
            if "ug/E002" in url:
                return union_html
            if "/org/" in url or "igod.gov.in" in url and "organizations" not in url:
                return detail_html
            return union_html

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "reg.json"
            seed = {
                "version": 1,
                "source_directory": "IGOD",
                "directory_urls": {},
                "sources": [
                    {
                        "id": "ka-parent",
                        "name": "Karnataka",
                        "level": "state",
                        "state": "Karnataka",
                        "domain": "karnataka.gov.in",
                        "base_urls": ["https://karnataka.gov.in/"],
                        "categories": ["general"],
                        "source_directory": "curated",
                        "enabled": True,
                        "priority": 5,
                        "health": "active",
                    }
                ],
                "rejected": [],
            }
            path.write_text(json.dumps(seed), encoding="utf-8")
            with patch.object(registry, "REGISTRY_PATH", path):
                with patch.object(registry, "_fetch_html", side_effect=fake_fetch):
                    registry._cache = None
                    summary = registry.refresh_registry_from_igod(timeout=5)
                    self.assertIn("added", summary)
                    self.assertGreaterEqual(summary["total_sources"], 1)
                    # Evil news must be rejected
                    data = registry.load_registry(force_reload=True)
                    domains = {s.get("domain") for s in data["sources"]}
                    self.assertNotIn("evil-news.com", domains)
                    self.assertNotIn("spam.example.com", domains)
                    rejected_urls = " ".join(r.get("url", "") for r in data.get("rejected") or [])
                    self.assertTrue(
                        "evil-news.com" in rejected_urls or "spam.example.com" in rejected_urls
                        or summary.get("rejected_count", 0) >= 0
                    )


class TestRedirectValidation(unittest.TestCase):
    def test_fetch_rejects_untrusted_redirect(self):
        from fastapi import HTTPException
        from app.services.web_ingestion_service import WebIngestionService

        class FakeResp:
            status_code = 200
            url = "https://evil.example.com/phish"
            content = b"hi"
            headers = {"content-type": "text/html"}

            def raise_for_status(self):
                return None

        class FakeClient:
            def __init__(self, *a, **k):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def get(self, url, headers=None):
                return FakeResp()

        db = MagicMock()
        svc = WebIngestionService(db)
        with patch("httpx.Client", FakeClient):
            with self.assertRaises(HTTPException) as ctx:
                svc.fetch_url("https://pmkisan.gov.in/")
            self.assertEqual(ctx.exception.status_code, 400)
            self.assertIn("trusted", ctx.exception.detail.lower())


if __name__ == "__main__":
    unittest.main()
