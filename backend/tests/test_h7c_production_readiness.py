"""H7-C — production readiness regression tests."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.database.session import Base, get_db
from app.main import app
from app.models import citizen_account, user, rag, audit, conversation  # noqa: F401


class TestH7CProductionReadiness(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db_path = "test_h7c_production.db"
        if os.path.exists(cls.db_path):
            try:
                os.remove(cls.db_path)
            except Exception:
                pass
        cls.engine = create_engine(
            f"sqlite:///{cls.db_path}", connect_args={"check_same_thread": False}
        )
        Base.metadata.drop_all(bind=cls.engine)
        Base.metadata.create_all(bind=cls.engine)
        cls.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=cls.engine)

        def _override_db():
            db = cls.SessionLocal()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = _override_db
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides.clear()
        cls.engine.dispose()
        if os.path.exists(cls.db_path):
            try:
                os.remove(cls.db_path)
            except Exception:
                pass

    def test_docs_disabled_in_production_source_guard(self):
        """Remediation: Swagger UI / OpenAPI must be gated off when APP_ENV=production."""
        import pathlib

        source = pathlib.Path("app/main.py").read_text(encoding="utf-8")
        self.assertIn('_IS_PRODUCTION_ENV = settings.APP_ENV.strip().lower() == "production"', source)
        self.assertIn("openapi_url=None if _IS_PRODUCTION_ENV", source)
        self.assertIn("docs_url=None if _IS_PRODUCTION_ENV", source)
        self.assertIn("redoc_url=None if _IS_PRODUCTION_ENV", source)

    def test_docs_available_in_development(self):
        res = self.client.get("/docs")
        self.assertEqual(res.status_code, 200)

    def test_health_db_host_redacted_for_postgres(self):
        with patch.object(settings, "DATABASE_URL", "postgresql://user:pass@secret-host/db"):
            res = self.client.get("/health/db")
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json()["host"], "redacted")

    def test_health_db_returns_503_when_connection_fails(self):
        class _BrokenEngine:
            dialect = type("D", (), {"name": "postgresql"})()

            def connect(self):
                raise OSError("connection refused")

        with patch("app.database.session.engine", _BrokenEngine()):
            with patch.object(settings, "DATABASE_URL", "postgresql://user:pass@secret-host/db"):
                res = self.client.get("/health/db")
        self.assertEqual(res.status_code, 503, res.text)
        self.assertFalse(res.json()["ok"])
        self.assertEqual(res.json()["detail"], "connection_failed")


if __name__ == "__main__":
    unittest.main()
