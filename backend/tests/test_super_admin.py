import unittest
from unittest.mock import patch, MagicMock
import os
from fastapi import HTTPException, UploadFile
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from io import BytesIO

from app.database.session import Base
from app.models import citizen_account, user, rag, audit, conversation  # noqa: F401
from app.models.rag import RagDocument, DocumentChunk
from app.services.rag import ingest_document, ALLOWED_EXTENSIONS, MAX_FILE_SIZE_BYTES


class TestAdminRagIngestion(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db_path = "test_gramsakhi.db"
        if os.path.exists(cls.db_path):
            try:
                os.remove(cls.db_path)
            except Exception:
                pass
        cls.engine = create_engine(f"sqlite:///{cls.db_path}")
        Base.metadata.drop_all(bind=cls.engine)
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

    def create_mock_upload_file(self, filename: str, content: bytes, content_type: str = "text/plain") -> UploadFile:
        file_like = BytesIO(content)
        mock_file = MagicMock()
        mock_file.read.side_effect = file_like.read
        mock_file.seek.side_effect = file_like.seek
        mock_file.filename = filename
        mock_file.content_type = content_type
        mock_file.file = file_like
        return mock_file

    def test_reject_unsupported_extension(self):
        upload = self.create_mock_upload_file("notes.docx", b"hello")
        with self.assertRaises(HTTPException) as ctx:
            ingest_document(
                db=self.db,
                uploaded_by=None,
                title="Bad file",
                category="GOVERNMENT_SCHEMES",
                version="1.0",
                file=upload,
            )
        self.assertEqual(ctx.exception.status_code, 400)

    def test_reject_empty_file(self):
        upload = self.create_mock_upload_file("empty.txt", b"")
        with self.assertRaises(HTTPException) as ctx:
            ingest_document(
                db=self.db,
                uploaded_by=None,
                title="Empty",
                category="GOVERNMENT_SCHEMES",
                version="1.0",
                file=upload,
            )
        self.assertEqual(ctx.exception.status_code, 400)

    def test_reject_oversized_file(self):
        content = b"x" * (MAX_FILE_SIZE_BYTES + 1)
        upload = self.create_mock_upload_file("big.txt", content)
        with self.assertRaises(HTTPException) as ctx:
            ingest_document(
                db=self.db,
                uploaded_by=None,
                title="Big",
                category="GOVERNMENT_SCHEMES",
                version="1.0",
                file=upload,
            )
        self.assertEqual(ctx.exception.status_code, 400)

    @patch("app.services.rag.get_embeddings_batch")
    @patch("app.services.rag.upload_rag_document")
    def test_successful_txt_ingest(self, mock_upload, mock_embed):
        mock_upload.return_value = "knowledge-base/schemes/x.txt"
        text = "PM-KISAN provides income support to landholding farmer families. " * 20
        mock_embed.return_value = [[0.1] * 1024 for _ in range(10)]
        upload = self.create_mock_upload_file("pmkisan.txt", text.encode("utf-8"))

        doc = ingest_document(
            db=self.db,
            uploaded_by=None,
            title="PM-KISAN Guidelines",
            category="GOVERNMENT_SCHEMES",
            version="1.0",
            file=upload,
            scheme_name="PM-KISAN",
            ministry="Agriculture",
        )
        self.assertIsNotNone(doc.id)
        self.assertEqual(doc.scheme_name, "PM-KISAN")
        self.assertEqual(doc.indexing_status, "INDEXED")
        self.assertIsNone(doc.hospital_id)
        chunks = self.db.query(DocumentChunk).filter(DocumentChunk.document_id == doc.id).all()
        self.assertGreater(len(chunks), 0)
        self.assertIn("scheme_name", chunks[0].metadata_dict or {})

    def test_allowed_extensions(self):
        self.assertIn(".pdf", ALLOWED_EXTENSIONS)
        self.assertIn(".txt", ALLOWED_EXTENSIONS)


if __name__ == "__main__":
    unittest.main()
