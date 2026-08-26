#!/usr/bin/env python3
"""Deterministic IVR-A5 contract verification (no live telephony)."""

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
from app.services.ivr.call_state import IvrCallState, get_state, set_state  # noqa: E402
from app.services.ivr.language_session import get_session_store, reset_session_store, set_language  # noqa: E402
from app.services.voice import tts_service  # noqa: E402

CALL_SID = "CA_VERIFY_IVR_A5"
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

    print("IVR-A5 verification (static contract, no telephony)")
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

    lang = client.get("/api/ivr/language", params={"CallSid": CALL_SID, "digits": "3"})
    record("Language → READY_FOR_INPUT", lang.status_code == 200 and get_state(CALL_SID) == IvrCallState.READY_FOR_INPUT)

    with patch.object(settings, "IVR_PUBLIC_BASE_URL", "https://api.gramsakhi.example.in"):
        set_language(CALL_SID, "en")
        store = get_session_store()
        store.set_transcription(CALL_SID, transcription="Verify multi-turn")
        store.set_last_response_text(CALL_SID, "Multi-turn answer.")
        store.set_last_response_language(CALL_SID, "EN")
        set_state(CALL_SID, IvrCallState.SYNTHESIZING)
        tts_service.set_test_synthesize_hook(
            lambda text, language=None, request_id=None: {
                "success": True,
                "audio": FAKE_MP3,
                "mime_type": "audio/mpeg",
            }
        )
        tts = client.post("/api/ivr/tts", json={"CallSid": CALL_SID})
        record("TTS → PLAYING_RESPONSE", tts.status_code == 200 and get_state(CALL_SID) == IvrCallState.PLAYING_RESPONSE)

        menu = client.get("/api/ivr/continue", params={"CallSid": CALL_SID})
        record("Continue menu", menu.status_code == 200 and get_state(CALL_SID) == IvrCallState.ASK_CONTINUE)

        cont = client.post("/api/ivr/continue", json={"CallSid": CALL_SID, "digits": "1"})
        record("Continue → READY_FOR_INPUT", cont.json().get("continue_loop") and get_state(CALL_SID) == IvrCallState.READY_FOR_INPUT)

        end = client.post("/api/ivr/continue", json={"CallSid": CALL_SID, "digits": "2"})
        record("End clears session", end.json().get("end_call") and not store.session_exists(CALL_SID))

    print()
    print(f"Result: {passed}/{total} checks passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
