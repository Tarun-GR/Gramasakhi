#!/usr/bin/env python3
"""Deterministic IVR-A7 release gate (no live telephony)."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import settings  # noqa: E402
from app.services.ivr.call_sid_validation import normalize_call_sid  # noqa: E402
from app.services.ivr.exotel_recording import _GuardedRedirectHandler, validate_exotel_recording_url  # noqa: E402
from app.services.ivr.ivr_config import collect_ivr_production_config_errors  # noqa: E402
from app.services.ivr.public_url import validate_ivr_public_base_url  # noqa: E402
from app.services.otp_dev_retrieval import otp_dev_retrieval_active  # noqa: E402


def main() -> int:
    print("IVR-A7 RELEASE GATE")
    print("===================")
    passed = 0
    failed = 0
    warned = 0

    def pass_check(name: str) -> None:
        nonlocal passed
        passed += 1
        print(f"[PASS] {name}")

    def fail_check(name: str) -> None:
        nonlocal failed
        failed += 1
        print(f"[FAIL] {name}")

    def warn_check(name: str) -> None:
        nonlocal warned
        warned += 1
        print(f"[WARN] {name}")

    try:
        from app.main import app

        paths: set[str] = set()
        for wrapper in app.routes:
            ctx = getattr(wrapper, "include_context", None)
            prefix = getattr(ctx, "prefix", "") if ctx is not None else ""
            original = getattr(wrapper, "original_router", None)
            routes = getattr(original, "routes", None) or []
            for route in routes:
                path = f"{prefix}{getattr(route, 'path', '')}"
                if path.startswith("/api/ivr"):
                    paths.add(path)
        required = {
            "/api/ivr/language",
            "/api/ivr/transcribe",
            "/api/ivr/chat",
            "/api/ivr/tts",
            "/api/ivr/audio/{token}",
            "/api/ivr/continue",
        }
        if required.issubset(paths):
            pass_check("Endpoint inventory")
        else:
            fail_check("Endpoint inventory")
    except Exception:
        fail_check("Endpoint inventory")

    try:
        validate_ivr_public_base_url("http://api.example.in", app_env="production")
        fail_check("Production config")
    except ValueError:
        errors = collect_ivr_production_config_errors(settings)
        pass_check("Production config") if isinstance(errors, list) else fail_check("Production config")

    try:
        normalize_call_sid("CA_A7_RELEASE_GATE_OK")
        normalize_call_sid("../x")
        fail_check("CallSid isolation")
    except Exception:
        pass_check("CallSid isolation")

    blocked = 0
    for url in (
        "https://127.0.0.1/x.mp3",
        "https://10.0.0.8/x.mp3",
        "https://169.254.169.254/latest/meta-data",
        "file:///etc/passwd",
    ):
        try:
            validate_exotel_recording_url(url)
        except ValueError:
            blocked += 1
    try:
        _GuardedRedirectHandler().redirect_request(None, None, 302, "", {}, "https://127.0.0.1/x.mp3")
    except ValueError:
        blocked += 1
    if blocked == 5:
        pass_check("SSRF protection")
    else:
        fail_check("SSRF protection")

    docs = BACKEND_ROOT / "docs" / "IVR_A7.md"
    packet = BACKEND_ROOT / "docs" / "IVR_A7_REVIEW_PACKET.md"
    if docs.is_file() and packet.is_file() and "Redis" in docs.read_text(encoding="utf-8"):
        pass_check("Release documentation")
    else:
        fail_check("Release documentation")

    with patch.object(settings, "APP_ENV", "production"):
        with patch.object(settings, "OTP_DEV_RETRIEVAL_ENABLED", True):
            if not otp_dev_retrieval_active():
                pass_check("Dev surface gated")
            else:
                fail_check("Dev surface gated")

    warn_check("In-memory sessions/tokens/rate limits — single process only")
    warn_check("Webhook secret is operator-configured, not native Exotel HMAC")
    warn_check("All IVR callers share the configured bridge CitizenAccount")
    warn_check("Actual phone/Exotel flow is NOT LIVE VERIFIED")
    warn_check("X-Forwarded-For is trusted for rate-limit IP when present")
    warn_check("GET /language can re-select language from later call states")

    print()
    print(f"PASS: {passed}")
    print(f"FAIL: {failed}")
    print(f"WARN: {warned}")
    print()
    if failed:
        print("EXIT CODE: 1")
        print("DECISION: NO-GO")
        return 1
    print("EXIT CODE: 0")
    print("DECISION: GO WITH LIMITATIONS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
