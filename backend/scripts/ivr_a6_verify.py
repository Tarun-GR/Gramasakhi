#!/usr/bin/env python3
"""Deterministic IVR-A6 security verification (no live telephony)."""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from unittest.mock import patch

from app.core.config import settings  # noqa: E402
from app.services.ivr.call_sid_validation import normalize_call_sid  # noqa: E402
from app.services.ivr.exotel_recording import validate_exotel_recording_url  # noqa: E402
from app.services.ivr.ivr_config import collect_ivr_production_config_errors  # noqa: E402
from app.services.ivr.public_url import validate_ivr_public_base_url  # noqa: E402
from app.services.otp_dev_retrieval import otp_dev_retrieval_active  # noqa: E402


def _check(name: str, ok: bool) -> bool:
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
    return ok


def main() -> int:
    passed = 0
    total = 0

    def record(name: str, ok: bool) -> None:
        nonlocal passed, total
        total += 1
        if _check(name, ok):
            passed += 1

    try:
        normalize_call_sid("CA_VERIFY_A6_SESSION_OK")
        record("CallSid validation", True)
    except Exception:
        record("CallSid validation", False)

    blocked = False
    try:
        validate_exotel_recording_url("https://127.0.0.1/x.mp3")
    except ValueError:
        blocked = True
    record("SSRF localhost blocked", blocked)

    prod_errors = collect_ivr_production_config_errors(settings)
    record("Production config audit runs", isinstance(prod_errors, list))

    https_required = False
    try:
        validate_ivr_public_base_url("http://api.example.in", app_env="production")
    except ValueError:
        https_required = True
    record("Production HTTPS required", https_required)

    with patch.object(settings, "APP_ENV", "production"):
        with patch.object(settings, "OTP_DEV_RETRIEVAL_ENABLED", True):
            record("OTP dev gated off in production", not otp_dev_retrieval_active())

    doc = BACKEND_ROOT / "docs" / "IVR_A6.md"
    record("IVR_A6 documentation exists", doc.is_file() and "Redis" in doc.read_text(encoding="utf-8"))

    print(f"\nResult: {passed}/{total} checks passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
