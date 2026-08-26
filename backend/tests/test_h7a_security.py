"""H7-A — security and privacy hardening regression tests."""

from __future__ import annotations

import io
import os
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core import security
from app.core.config import settings
from app.database.session import Base, get_db
from app.main import app
from app.models import citizen_account, user, rag, audit, conversation  # noqa: F401
from app.models.citizen_account import CitizenAccount, OTPVerification
from app.services.auth_rate_limit import reset_auth_rate_limits


class TestH7ASecurity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db_path = "test_h7a_security.db"
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

    def setUp(self):
        reset_auth_rate_limits()
        db = self.SessionLocal()
        db.query(OTPVerification).delete()
        db.query(CitizenAccount).delete()
        db.commit()
        db.close()

    def _register_payload(self, phone: str = "9333333333"):
        return {
            "credentials": {"phone_number": phone, "password": "password123"},
            "display_name": "Test Citizen",
        }

    def _send_and_verify_otp(self, phone: str = "9333333333", code: str = "654321"):
        with patch.object(security, "generate_otp", return_value=code):
            send = self.client.post("/api/auth/otp/send", json={"phone_number": phone})
        self.assertEqual(send.status_code, 200, send.text)
        verify = self.client.post(
            "/api/auth/otp/verify",
            json={"phone_number": phone, "code": code},
        )
        self.assertEqual(verify.status_code, 200, verify.text)

    def test_register_without_verified_otp_rejected(self):
        res = self.client.post("/api/auth/register", json=self._register_payload())
        self.assertEqual(res.status_code, 401, res.text)
        self.assertIn("OTP verification is required", res.json()["detail"])

    def test_register_after_otp_verification_succeeds(self):
        self._send_and_verify_otp()
        res = self.client.post("/api/auth/register", json=self._register_payload())
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json()["phone_number"], "9333333333")

    def test_password_reset_blocks_after_max_attempts(self):
        db = self.SessionLocal()
        account = CitizenAccount(
            phone_number="9444444444",
            password_hash=security.get_password_hash("password123"),
            display_name="Reset User",
        )
        db.add(account)
        otp_rec = OTPVerification(
            phone_number="9444444444",
            otp_hash=security.get_otp_hash("111111"),
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=3),
            verified=False,
            attempt_count=5,
        )
        db.add(otp_rec)
        db.commit()
        db.close()

        res = self.client.post(
            "/api/auth/forgot-password/reset",
            json={
                "phone_number": "9444444444",
                "otp_code": "111111",
                "new_password": "newpassword123",
            },
        )
        self.assertEqual(res.status_code, 400, res.text)
        self.assertIn("Too many failed verification attempts", res.json()["detail"])

    def test_otp_send_rate_limited(self):
        phone = "9555555555"
        with patch.object(security, "generate_otp", return_value="123456"):
            for _ in range(settings.AUTH_OTP_SEND_MAX_PER_WINDOW):
                res = self.client.post("/api/auth/otp/send", json={"phone_number": phone})
                self.assertEqual(res.status_code, 200, res.text)
            blocked = self.client.post("/api/auth/otp/send", json={"phone_number": phone})
        self.assertEqual(blocked.status_code, 429, blocked.text)

    def test_otp_not_printed_for_non_sqlite_database(self):
        phone = "9666666666"
        buffer = io.StringIO()
        with patch.object(settings, "DATABASE_URL", "postgresql://user:pass@db.example.com/postgres"):
            with patch.object(security, "generate_otp", return_value="987654"):
                with redirect_stdout(buffer):
                    res = self.client.post("/api/auth/otp/send", json={"phone_number": phone})
        self.assertEqual(res.status_code, 200, res.text)
        output = buffer.getvalue()
        self.assertNotIn("987654", output)
        self.assertNotIn(phone, output)

    def test_security_headers_present(self):
        res = self.client.get("/health")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.headers.get("X-Content-Type-Options"), "nosniff")
        self.assertEqual(res.headers.get("X-Frame-Options"), "DENY")
        self.assertEqual(res.headers.get("Referrer-Policy"), "strict-origin-when-cross-origin")

    def test_health_db_host_redacted_for_non_sqlite(self):
        with patch.object(settings, "DATABASE_URL", "postgresql://user:pass@secret-host/db"):
            res = self.client.get("/health/db")
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json()["host"], "redacted")

    def test_generate_otp_format(self):
        code = security.generate_otp()
        self.assertEqual(len(code), 6)
        self.assertTrue(code.isdigit())


if __name__ == "__main__":
    unittest.main()
