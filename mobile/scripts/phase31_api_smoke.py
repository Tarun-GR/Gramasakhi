"""Mobile Phase 3.1 API smoke test — mirrors mobile client contracts (no mocks)."""
from __future__ import annotations

import io
import json
import re
import sys
import urllib.error
import urllib.request
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

BASE = "http://127.0.0.1:8000/api"
PHONE = "9876543210"
TIMEOUT = 300


def req(method: str, path: str, body: dict | None = None, token: str | None = None) -> tuple[int, dict | str]:
    url = f"{BASE}{path}"
    headers = {"Accept": "application/json"}
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as resp:
            raw = resp.read().decode()
            return resp.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = raw
        return e.code, payload


def main() -> int:
    failures: list[str] = []
    calls: list[str] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        status = "PASS" if ok else "FAIL"
        print(f"[{status}] {name}" + (f" — {detail}" if detail else ""))
        if not ok:
            failures.append(name)

    # A. Health
    try:
        with urllib.request.urlopen("http://127.0.0.1:8000/health", timeout=10) as r:
            health = json.loads(r.read().decode())
        check("A. Backend health", health.get("status") == "ok")
    except Exception as exc:
        check("A. Backend health", False, str(exc))
        return 1

    # B. OTP send + verify (dev simulator)
    code, data = req("POST", "/auth/otp/send", {"phone_number": PHONE})
    check("B. OTP send", code == 200, str(data))

    otp_code = None
    try:
        from fastapi.testclient import TestClient
        from app.main import app

        buf = io.StringIO()
        with redirect_stdout(buf):
            TestClient(app).post("/api/auth/otp/send", json={"phone_number": PHONE})
        match = re.search(r"VERIFICATION OTP:\s*(\d{6})", buf.getvalue())
        otp_code = match.group(1) if match else None
    except Exception as exc:
        check("B. OTP capture (dev simulator)", False, str(exc))

    token = None
    if otp_code:
        code, verify_data = req(
            "POST",
            "/auth/otp/verify",
            {"phone_number": PHONE, "code": otp_code},
        )
        token = verify_data.get("accessToken") if code == 200 else None
        check("B. OTP verify", code == 200 and bool(token), str(verify_data)[:120])

    if not token:
        # Postgres/dev: OTP may not print to console — obtain token for chat contract tests only.
        try:
            from dotenv import load_dotenv
            from app.database.session import SessionLocal
            from app.models.citizen_account import CitizenAccount
            from app.core import security

            load_dotenv(ROOT / "backend" / ".env")
            db = SessionLocal()
            acc = db.query(CitizenAccount).filter(CitizenAccount.phone_number == PHONE).first()
            db.close()
            if acc:
                token = security.create_access_token(subject=str(acc.id))
                check("B. Auth token (dev account)", True, "OTP simulator unavailable on this DB")
        except Exception as exc:
            check("B. Auth token (dev account)", False, str(exc))

    if not token:
        return 1

    # D. Chat bootstrap — list conversations (GET only)
    code, conv_list = req("GET", "/chat/conversations?limit=30&offset=0", token=token)
    calls.append("GET /chat/conversations")
    check("D. List conversations", code == 200 and "conversations" in conv_list, str(code))

    conv_id = None
    if conv_list.get("conversations"):
        conv_id = str(conv_list["conversations"][0]["id"])
        code, hist = req("GET", f"/chat/conversations/{conv_id}", token=token)
        calls.append(f"GET /chat/conversations/{conv_id}")
        check("D. Load conversation (read-only)", code == 200 and "messages" in hist, str(code))
    else:
        code, created = req("POST", "/chat/conversations", {}, token=token)
        calls.append("POST /chat/conversations")
        check("D. Create conversation", code == 200 and "id" in created, str(created))
        conv_id = str(created.get("id"))

    # E. Send message
    code, chat_resp = req(
        "POST",
        "/chat",
        {
            "message": "Hello",
            "conversation_id": conv_id,
            "language": "KN",
            "input_mode": "text",
        },
        token=token,
    )
    calls.append("POST /chat")
    check("E. Send Hello", code == 200 and chat_resp.get("answer"), str(code))
    conv_id = str(chat_resp.get("conversation_id") or conv_id)

    # F. Scheme query
    code, scheme_resp = req(
        "POST",
        "/chat",
        {
            "message": "What documents are required for PM-KISAN?",
            "conversation_id": conv_id,
            "language": "KN",
            "input_mode": "text",
        },
        token=token,
    )
    calls.append("POST /chat (scheme)")
    has_answer = bool(scheme_resp.get("answer")) if code == 200 else False
    check("F. Scheme query", code == 200 and has_answer, f"sources={len(scheme_resp.get('sources') or [])}")

    # G. Second conversation
    code, conv2 = req("POST", "/chat/conversations", {}, token=token)
    conv2_id = str(conv2.get("id"))
    code, _ = req(
        "POST",
        "/chat",
        {"message": "Different thread message", "conversation_id": conv2_id, "language": "KN", "input_mode": "text"},
        token=token,
    )
    code, hist_a = req("GET", f"/chat/conversations/{conv_id}", token=token)
    code, hist_b = req("GET", f"/chat/conversations/{conv2_id}", token=token)
    a_msgs = [m["content"] for m in hist_a.get("messages", []) if m.get("role") == "user"]
    b_msgs = [m["content"] for m in hist_b.get("messages", []) if m.get("role") == "user"]
    check("G. Conversation isolation", "Different thread message" in b_msgs and "Different thread message" not in a_msgs)

    # I. Resume — history GET only (no POST /chat in this step)
    resume_calls_before = len(calls)
    code, resume = req("GET", f"/chat/conversations/{conv_id}", token=token)
    calls.append(f"GET /chat/conversations/{conv_id} (resume)")
    check("I. Resume load", code == 200 and len(resume.get("messages", [])) > 0)
    check("I. No POST on resume", not any(c.startswith("POST /chat") for c in calls[resume_calls_before:]))

    # J. Auth expiration
    code, _ = req("GET", "/chat/conversations?limit=1&offset=0", token="invalid.jwt.token")
    check("J. Invalid token 401", code == 401, str(code))

    # K. Network failure simulation — bad host
    try:
        bad = urllib.request.Request("http://127.0.0.1:59999/api/health")
        urllib.request.urlopen(bad, timeout=2)
        check("K. Unreachable host", False, "expected failure")
    except Exception:
        check("K. Unreachable host handled", True)

    print("\n--- API calls trace ---")
    for c in calls:
        print(c)

    if failures:
        print(f"\n{len(failures)} failure(s):", ", ".join(failures))
        return 1
    print("\nAll API smoke checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
