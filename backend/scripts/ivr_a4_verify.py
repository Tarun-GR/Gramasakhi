#!/usr/bin/env python3
"""Deterministic IVR-A4 contract verification (no live telephony)."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.main import app  # noqa: E402
from app.services.ivr.audio_token_store import reset_audio_token_store  # noqa: E402
from app.services.ivr.language_session import get_session_store, reset_session_store, set_language  # noqa: E402
from app.services.voice import tts_service  # noqa: E402

CALL_SID = "CA_VERIFY_IVR_A4"
FAKE_MP3 = b"\xff\xfb" + b"\x01" * 64


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

    print("IVR-A4 verification (static contract, no telephony)")
    reset_session_store()
    reset_audio_token_store()
    client = TestClient(app)
    passed = 0
    total = 0

    def record(name: str, ok: bool, detail: str = "") -> None:
        nonlocal passed, total
        total += 1
        if _check(name, ok, detail):
            passed += 1

    with patch.object(settings, "IVR_PUBLIC_BASE_URL", "https://api.gramsakhi.example.in"):
        set_language(CALL_SID, "en")
        get_session_store().set_last_response_text(CALL_SID, "Verified playback text.")
        get_session_store().set_last_response_language(CALL_SID, "EN")
        from app.services.ivr.call_state import IvrCallState, set_state

        set_state(CALL_SID, IvrCallState.SYNTHESIZING)
        tts_service.set_test_synthesize_hook(
            lambda text, language=None, request_id=None: {
                "success": True,
                "audio": FAKE_MP3,
                "mime_type": "audio/mpeg",
                "language": language,
                "request_id": request_id or "v",
            }
        )
        tts_resp = client.post("/api/ivr/tts", json={"CallSid": CALL_SID})
        record("TTS endpoint success", tts_resp.status_code == 200 and tts_resp.json().get("success"))
        audio_url = tts_resp.json().get("audio_url") or ""
        token = audio_url.rsplit("/", 1)[-1]
        fetch = client.get(f"/api/ivr/audio/{token}")
        record("Audio fetch 200", fetch.status_code == 200 and fetch.content == FAKE_MP3)
        replay = client.get(f"/api/ivr/audio/{token}")
        record("Single-use token", replay.status_code == 404)
        record("No transcript in TTS body", "Verified playback text" not in tts_resp.text)

    print()
    print(f"Result: {passed}/{total} checks passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
