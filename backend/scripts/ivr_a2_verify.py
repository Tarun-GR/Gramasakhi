#!/usr/bin/env python3
"""Deterministic IVR-A2 contract verification (no live Exotel call).

Run from backend/:
  .venv/Scripts/python.exe scripts/ivr_a2_verify.py
"""

from __future__ import annotations

import io
import sys
from pathlib import Path
from unittest.mock import patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.main import app  # noqa: E402
from app.services.ivr.call_state import IvrCallState, set_state  # noqa: E402
from app.services.ivr.exotel_recording import validate_exotel_recording_url  # noqa: E402
from app.services.ivr.language_session import (  # noqa: E402
    get_transcription,
    reset_session_store,
    set_language,
)
from app.services.ivr.stt_adapter import resolve_stt_language_hint  # noqa: E402
from app.services.voice import stt_service  # noqa: E402
from app.services.voice.audio_utils import make_tone_wav  # noqa: E402

CALL_SID = "CA_VERIFY_IVR_A2"
EXOTEL_URL = "https://s3-ap-southeast-1.amazonaws.com/exotelrecordings/verify.mp3"


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

    print("IVR-A2 verification (static contract, no telephony)")
    reset_session_store()
    client = TestClient(app)
    env_patchers = [
        patch.object(settings, "APP_ENV", "development"),
        patch.object(settings, "IVR_DIRECT_UPLOAD_IN_PRODUCTION", True),
        patch.object(settings, "IVR_WEBHOOK_SHARED_SECRET", ""),
    ]
    for p in env_patchers:
        p.start()

    try:
        return _run_checks(client)
    finally:
        for p in env_patchers:
            p.stop()
        stt_service.set_test_transcribe_hook(None)


def _run_checks(client) -> int:
    passed = 0
    total = 0

    def record(name: str, ok: bool, detail: str = "") -> None:
        nonlocal passed, total
        total += 1
        if _check(name, ok, detail):
            passed += 1

    record("kn → KN mapping (no session)", resolve_stt_language_hint(CALL_SID) is None)
    set_language(CALL_SID, "kn")
    set_state(CALL_SID, IvrCallState.READY_FOR_INPUT)
    record("kn → KN mapping", resolve_stt_language_hint(CALL_SID) == "KN")

    try:
        validate_exotel_recording_url(EXOTEL_URL)
        record("Exotel URL accepted", True)
    except ValueError as exc:
        record("Exotel URL accepted", False, str(exc))

    try:
        validate_exotel_recording_url("https://127.0.0.1/x.mp3")
        record("localhost rejected", False)
    except ValueError:
        record("localhost rejected", True)

    missing_sid = client.get("/api/ivr/transcribe", params={"RecordingUrl": EXOTEL_URL})
    record("CallSid required", missing_sid.status_code == 400)

    unknown = client.get(
        "/api/ivr/transcribe",
        params={"CallSid": "CA_VERIFY_UNKNOWN_IVR_A2", "RecordingUrl": EXOTEL_URL},
    )
    record("Unknown CallSid rejected", unknown.status_code == 400)

    stt_service.set_test_transcribe_hook(
        lambda data, **k: {
            "success": True,
            "text": "verify transcript",
            "detected_language": "KN",
            "confidence": 0.9,
            "low_confidence": False,
            "request_id": "verify",
        }
    )
    tone = make_tone_wav(0.2)
    ok = client.post(
        "/api/ivr/transcribe",
        params={"CallSid": CALL_SID},
        files={"audio": ("v.wav", io.BytesIO(tone), "audio/wav")},
    )
    record(
        "STT adapter stores transcript",
        ok.status_code == 200
        and ok.json().get("success") is True
        and get_transcription(CALL_SID) == "verify transcript",
    )
    record(
        "Transcript not in HTTP body",
        "verify transcript" not in ok.text,
    )

    print()
    print(f"Result: {passed}/{total} checks passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
