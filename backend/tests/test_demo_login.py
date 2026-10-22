"""FYP demo login — allowlisted OTP exposure and security."""

from __future__ import annotations

import os
import unittest
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
from app.models.user import User
from app.services.auth_rate_limit import reset_auth_rate_limits


DEMO_PHONE = "9999900001"
OTHER_PHONE = "9000111199"


class TestDemoLogin(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db_path = "test_demo_login.db"
        if os.path.exists(cls.db_path):
            os.remove(cls.db_path)
        cls.engine = create_engine(
            f"sqlite:///{cls.db_path}", connect_args={"check_same_thread": False}
        )
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
            os.remove(cls.db_path)

    def setUp(self):
        reset_auth_rate_limits()
        db = self.SessionLocal()
        db.query(OTPVerification).delete()
        db.query(CitizenAccount).delete()
        db.query(User).delete()
        db.commit()
        db.close()

    def _demo_patches(self):
        return (
            patch.object(settings, "APP_ENV", "production"),
            patch.object(settings, "DEMO_LOGIN_ENABLED", True),
            patch.object(settings, "DEMO_LOGIN_PHONES", DEMO_PHONE),
            patch.object(settings, "OTP_DELIVERY_MODE", "sms"),
            patch.object(settings, "OTP_DEV_POPUP_ENABLED", False),
        )

    def test_demo_info_when_enabled(self):
        with patch.object(settings, "DEMO_LOGIN_ENABLED", True):
            with patch.object(settings, "DEMO_LOGIN_PHONES", DEMO_PHONE):
                res = self.client.get("/api/auth/demo/info")
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertTrue(body["enabled"])
        self.assertEqual(body["demo_phone"], DEMO_PHONE)

    def test_demo_info_when_disabled(self):
        with patch.object(settings, "DEMO_LOGIN_ENABLED", False):
            res = self.client.get("/api/auth/demo/info")
        self.assertEqual(res.json()["enabled"], False)

    def test_production_demo_phone_returns_demo_otp(self):
        patches = self._demo_patches()
        for p in patches:
            p.start()
        try:
            with patch.object(security, "generate_otp", return_value="556677"):
                res = self.client.post("/api/auth/otp/send", json={"phone_number": DEMO_PHONE})
        finally:
            for p in patches:
                p.stop()
        self.assertEqual(res.status_code, 200, res.text)
        body = res.json()
        self.assertEqual(body["delivery_mode"], "demo")
        self.assertEqual(body["demo_otp"], "556677")
        self.assertNotIn("dev_otp", body)

    def test_production_other_phone_never_returns_demo_otp(self):
        patches = self._demo_patches()
        for p in patches:
            p.start()
        try:
            with patch.object(security, "generate_otp", return_value="556677"):
                res = self.client.post("/api/auth/otp/send", json={"phone_number": OTHER_PHONE})
        finally:
            for p in patches:
                p.stop()
        body = res.json()
        self.assertNotIn("demo_otp", body)
        self.assertNotIn("dev_otp", body)
        self.assertEqual(body.get("delivery_mode"), "sms")

    def test_demo_disabled_no_demo_otp_even_for_allowlisted_phone(self):
        with patch.object(settings, "APP_ENV", "production"):
            with patch.object(settings, "DEMO_LOGIN_ENABLED", False):
                with patch.object(settings, "DEMO_LOGIN_PHONES", DEMO_PHONE):
                    with patch.object(security, "generate_otp", return_value="556677"):
                        res = self.client.post(
                            "/api/auth/otp/send",
                            json={"phone_number": DEMO_PHONE},
                        )
        self.assertNotIn("demo_otp", res.json())

    def test_demo_verify_issues_citizen_token(self):
        db = self.SessionLocal()
        db.add(
            CitizenAccount(
                phone_number=DEMO_PHONE,
                password_hash=security.get_password_hash("unused"),
                display_name="FYP Demo",
            )
        )
        db.commit()
        db.close()

        patches = self._demo_patches()
        for p in patches:
            p.start()
        try:
            with patch.object(security, "generate_otp", return_value="112233"):
                send = self.client.post("/api/auth/otp/send", json={"phone_number": DEMO_PHONE})
            vid = send.json()["otp_verification_id"]
            verify = self.client.post(
                "/api/auth/otp/verify",
                json={
                    "phone_number": DEMO_PHONE,
                    "code": "112233",
                    "otp_verification_id": vid,
                },
            )
        finally:
            for p in patches:
                p.stop()
        self.assertEqual(verify.status_code, 200, verify.text)
        token = verify.json()["accessToken"]
        payload = security.decode_access_token(token)
        self.assertTrue(security.token_use_allowed(payload, "citizen"))

    def test_demo_citizen_cannot_access_super_admin(self):
        db = self.SessionLocal()
        db.add(
            User(
                email="admin@test.local",
                password_hash=security.get_password_hash("adminpass"),
                first_name="Admin",
                last_name="User",
                role="SUPER_ADMIN",
                is_active=True,
            )
        )
        db.commit()
        db.close()

        citizen_token = security.create_access_token(subject="citizen-uuid", token_use="citizen")
        res = self.client.get(
            "/api/v1/super-admin/knowledge-base",
            headers={"Authorization": f"Bearer {citizen_token}"},
        )
        self.assertIn(res.status_code, (401, 403, 404, 422))


if __name__ == "__main__":
    unittest.main()
