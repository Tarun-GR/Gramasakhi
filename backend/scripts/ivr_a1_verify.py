#!/usr/bin/env python3
"""Deterministic IVR-A1 contract verification (no live Exotel call).

Run from backend/:
  .venv/Scripts/python.exe scripts/ivr_a1_verify.py
"""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.schemas.ivr import IvrGatherResponse  # noqa: E402
from app.services.ivr.language_session import get_language, reset_session_store  # noqa: E402

CALL_SID = "CA_VERIFY_IVR_A1_SESSION"


def _check(name: str, ok: bool, detail: str = "") -> bool:
    status = "PASS" if ok else "FAIL"
    suffix = f" — {detail}" if detail else ""
    print(f"  [{status}] {name}{suffix}")
    return ok


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    print("IVR-A1 verification (static contract, no telephony)")
    reset_session_store()
    client = TestClient(app)
    passed = 0
    total = 0

    def record(name: str, ok: bool, detail: str = "") -> None:
        nonlocal passed, total
        total += 1
        if _check(name, ok, detail):
            passed += 1

    missing = client.get("/api/ivr/language", params={"digits": "1"})
    record("Missing CallSid rejected", missing.status_code == 400)

    menu = client.get("/api/ivr/language", params={"CallSid": CALL_SID})
    record("Initial menu HTTP 200", menu.status_code == 200)
    try:
        IvrGatherResponse.model_validate(menu.json())
        record("Menu response matches Gather schema", True)
    except Exception as exc:
        record("Menu response matches Gather schema", False, str(exc))

    kn = client.get("/api/ivr/language", params={"CallSid": CALL_SID, "digits": '"1"'})
    record("Quoted digit 1 → kn", kn.status_code == 200 and get_language(CALL_SID) == "kn")

    invalid = client.get("/api/ivr/language", params={"CallSid": CALL_SID, "digits": "7"})
    record("Invalid digit handled", invalid.status_code == 200 and "Invalid" in invalid.json()["gather_prompt"]["text"])

    secret_leak = "EXOTEL_TEST_TOKEN_DO_NOT_EXPOSE"
    with __import__("unittest.mock", fromlist=["patch"]).patch(
        "app.core.config.settings.EXOTEL_API_TOKEN", secret_leak
    ):
        safe = client.get("/api/ivr/language", params={"CallSid": CALL_SID, "digits": "3"})
    record("No credential echo in response", secret_leak not in safe.text)

    print()
    print(f"Result: {passed}/{total} checks passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
