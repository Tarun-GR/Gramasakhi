import unittest
from unittest.mock import patch
import os
from datetime import datetime, timezone, timedelta

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database.session import Base
from app.models import citizen_account, user, rag, audit, conversation  # noqa: F401
from app.models.rag import RagDocument, DocumentChunk
from app.config.gov_sources import is_allowed_url, GOV_SOURCES, list_catalog_schemes
from app.services.web_ingestion_service import (
    WebIngestionService,
    compute_hash,
    normalize_metadata,
    MIN_HTML_CHARS,
)
from app.services.rag import ingest_raw_bytes, extract_text_from_bytes, chunk_text
from app.background_jobs.web_ingest_scheduler import should_run, _save_last_run, STATE_PATH


class TestWebIngestionHardening(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db_path = "test_web_ingest_harden.db"
        cls.engine = create_engine(f"sqlite:///{cls.db_path}")
        Base.metadata.create_all(bind=cls.engine)
        cls.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=cls.engine)

    @classmethod
    def tearDownClass(cls):
        if os.path.exists(cls.db_path):
            try:
                os.remove(cls.db_path)
            except Exception:
                pass

    def setUp(self):
        self.db = self.SessionLocal()
        self.db.query(DocumentChunk).delete()
        self.db.query(RagDocument).delete()
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def _rich_html(self, body: str) -> bytes:
        return (
            f"<html><body><main>{body}</main></body></html>"
        ).encode("utf-8")

    def test_allowlist_and_catalog(self):
        self.assertTrue(is_allowed_url("https://pmkisan.gov.in/"))
        self.assertFalse(is_allowed_url("https://evil.example.com/"))
        self.assertIn("central", {s["id"] for s in GOV_SOURCES})
        self.assertGreater(len(list_catalog_schemes()), 0)

    def test_normalize_metadata(self):
        meta = normalize_metadata(
            {
                "url": "https://pmkisan.gov.in/",
                "scheme_name": "PM-Kisan",
                "state": "India",
                "document_hash": "abc",
                "text_preview": "eligibility benefits apply",
            }
        )
        self.assertEqual(meta["scheme_name"], "PM-Kisan")
        self.assertEqual(meta["state"], "India")
        self.assertEqual(meta["source"], "https://pmkisan.gov.in/")
        self.assertEqual(meta["ingestion_type"], "web")
        self.assertIn(meta["category"], ("ELIGIBILITY", "APPLICATION", "BENEFITS", "GOVERNMENT_SCHEMES"))

    def test_filter_prefers_pdfs(self):
        service = WebIngestionService(self.db)
        links = [
            "https://pmkisan.gov.in/about",
            "https://pmkisan.gov.in/docs/guidelines.pdf",
            "https://www.myscheme.gov.in/schemes/pm-kisan",
        ]
        filtered = service.filter_relevant_documents(links, limit=2)
        self.assertTrue(filtered[0].endswith(".pdf"))

    @patch("app.services.rag.get_embeddings_batch")
    @patch("app.services.rag.upload_rag_document", return_value="/static/uploads/web.txt")
    def test_duplicate_ingestion_skipped(self, mock_upload, mock_embed):
        body = ("PM-KISAN benefits and eligibility for landholding farmer families. " * 40)
        html = self._rich_html(body)

        def fake_fetch(url):
            return html, "text/html"

        mock_embed.side_effect = lambda texts: [[0.1] * 1024 for _ in texts]
        service = WebIngestionService(self.db)
        service.fetch_url = fake_fetch  # type: ignore

        first = service.ingest_single_url(
            "https://pmkisan.gov.in/",
            scheme_name="PM-Kisan",
            state="India",
        )
        self.assertEqual(first["status"], "ok", first)

        second = service.ingest_single_url(
            "https://pmkisan.gov.in/",
            scheme_name="PM-Kisan",
            state="India",
        )
        self.assertEqual(second["status"], "skipped", second)
        self.assertEqual(second.get("reason"), "duplicate")
        self.assertEqual(self.db.query(RagDocument).count(), 1)

    @patch("app.services.rag.get_embeddings_batch")
    @patch("app.services.rag.upload_rag_document", return_value="/static/uploads/web.txt")
    def test_low_content_html_skipped(self, mock_upload, mock_embed):
        html = self._rich_html("Too short.")
        mock_embed.side_effect = lambda texts: [[0.1] * 1024 for _ in texts]
        service = WebIngestionService(self.db)
        service.fetch_url = lambda url: (html, "text/html")  # type: ignore

        result = service.ingest_single_url("https://pmkisan.gov.in/")
        self.assertEqual(result["status"], "skipped", result)
        self.assertEqual(result.get("reason"), "low_content")
        self.assertEqual(self.db.query(RagDocument).count(), 0)
        self.assertLess(len("Too short."), MIN_HTML_CHARS)

    @patch("app.services.rag.get_embeddings_batch")
    @patch("app.services.rag.upload_rag_document", return_value="/static/uploads/web.pdf")
    def test_pdf_preferred_over_html(self, mock_upload, mock_embed):
        html = (
            "<html><body><main>"
            + ("Landing page with little useful scheme detail. " * 5)
            + '<a href="https://pmkisan.gov.in/docs/guidelines.pdf">Guidelines PDF</a>'
            + "</main></body></html>"
        ).encode("utf-8")
        # PDF text long enough to ingest
        pdf_text = ("PM-KISAN official guidelines eligibility benefits. " * 50).encode("utf-8")

        def fake_fetch(url):
            if url.endswith(".pdf"):
                return pdf_text, "application/pdf"
            return html, "text/html"

        def fake_extract(content, ext):
            if ext == ".pdf":
                return [{"page": 1, "text": content.decode("utf-8", errors="ignore")}]
            return [{"page": 1, "text": content.decode("utf-8", errors="ignore")}]

        mock_embed.side_effect = lambda texts: [[0.2] * 1024 for _ in texts]
        service = WebIngestionService(self.db)
        service.fetch_url = fake_fetch  # type: ignore

        with patch("app.services.rag.extract_text_from_bytes", side_effect=fake_extract):
            result = service.ingest_single_url(
                "https://pmkisan.gov.in/",
                scheme_name="PM-Kisan",
                state="India",
            )

        self.assertEqual(result["status"], "ok", result)
        self.assertEqual(result.get("strategy"), "pdf_first")
        self.assertFalse(result.get("html_ingested", True))
        linked = result.get("linked_documents") or []
        self.assertTrue(any(r.get("status") == "ok" for r in linked))
        docs = self.db.query(RagDocument).all()
        self.assertGreaterEqual(len(docs), 1)
        self.assertTrue(any(d.document_type == "PDF" for d in docs))

    @patch("app.services.rag.get_embeddings_batch")
    @patch("app.services.rag.upload_rag_document", return_value="/static/uploads/web.txt")
    def test_chunk_metadata_required_fields(self, mock_upload, mock_embed):
        body = ("PM-KISAN benefits eligibility application procedure for farmers. " * 40)
        html = self._rich_html(body)
        mock_embed.side_effect = lambda texts: [[0.1] * 1024 for _ in texts]
        service = WebIngestionService(self.db)
        service.fetch_url = lambda url: (html, "text/html")  # type: ignore

        result = service.ingest_single_url(
            "https://pmkisan.gov.in/",
            scheme_name="PM-Kisan Samman Nidhi",
            state="India",
        )
        self.assertEqual(result["status"], "ok", result)
        chunks = self.db.query(DocumentChunk).all()
        self.assertGreater(len(chunks), 0)
        for c in chunks:
            meta = c.metadata_dict or {}
            self.assertTrue(meta.get("scheme_name"))
            self.assertTrue(meta.get("state"))
            self.assertTrue(meta.get("source"))
            self.assertEqual(meta.get("ingestion_type"), "web")
            self.assertTrue(meta.get("document_hash"))

    @patch("app.services.rag.get_embeddings_batch")
    @patch("app.services.rag.upload_rag_document", return_value="/static/uploads/manual.txt")
    def test_manual_ingest_still_works(self, mock_upload, mock_embed):
        text = ("Government scheme eligibility benefits procedure. " * 40).encode("utf-8")
        mock_embed.side_effect = lambda texts: [[0.05] * 1024 for _ in texts]
        doc = ingest_raw_bytes(
            db=self.db,
            uploaded_by=None,
            title="Manual Scheme Doc",
            category="GOVERNMENT_SCHEMES",
            version="1.0",
            contents=text,
            ext=".txt",
            scheme_name="Manual Scheme",
            source="manual-upload",
            document_hash=compute_hash(text),
        )
        self.assertEqual(doc.indexing_status, "INDEXED")
        self.assertEqual(doc.document_hash, compute_hash(text))
        self.assertIsNotNone(doc.last_ingested_at)

    def test_scheduler_threshold_skip(self):
        backup = None
        if STATE_PATH.exists():
            backup = STATE_PATH.read_text(encoding="utf-8")
        try:
            _save_last_run(datetime.now(timezone.utc))
            self.assertFalse(should_run(168))
            _save_last_run(datetime.now(timezone.utc) - timedelta(hours=200))
            self.assertTrue(should_run(168))
        finally:
            if backup is not None:
                STATE_PATH.write_text(backup, encoding="utf-8")
            elif STATE_PATH.exists():
                STATE_PATH.unlink()

    def test_existing_extract_chunk_unchanged(self):
        pages = extract_text_from_bytes(b"Hello scheme page one.", ".txt")
        chunks = chunk_text(pages)
        self.assertEqual(pages[0]["page"], 1)
        self.assertGreaterEqual(len(chunks), 1)


if __name__ == "__main__":
    unittest.main()
