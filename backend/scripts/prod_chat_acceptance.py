#!/usr/bin/env python3
"""Live production chat acceptance (demo OTP). Requires network; no secrets logged."""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request

DEFAULT_BASE = "https://gramasakhi.onrender.com/api"
DEMO_PHONE = "9999900001"

CASES = [
    ("pm_kisan", "What is PM-KISAN? Explain eligibility and benefits.", "EN"),
    ("pmjay", "What is Ayushman Bharat PM-JAY? Explain eligibility and benefits for citizens.", "EN"),
    ("gruha_lakshmi", "What is Gruha Lakshmi scheme? Explain eligibility and benefits.", "EN"),
    ("gruha_jyothi", "What is Gruha Jyothi? Explain eligibility and benefits.", "EN"),
    ("unsupported", "What is the Mars farmer subsidy eligibility in Karnataka?", "EN"),
]


def _post(url: str, body: dict, token: str | None = None) -> dict:
    data = json.dumps(body).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _get(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _login(base: str, phone: str, retries: int = 5) -> str:
    send_url = f"{base}/auth/otp/send"
    verify_url = f"{base}/auth/otp/verify"
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            send = _post(send_url, {"phone_number": phone})
            demo = send.get("demo_otp")
            if not demo:
                raise RuntimeError("demo_otp not returned; is DEMO_LOGIN enabled on production?")
            ver = _post(
                verify_url,
                {
                    "phone_number": phone,
                    "code": demo,
                    "otp_verification_id": send["otp_verification_id"],
                },
            )
            token = ver.get("accessToken") or ver.get("access_token")
            if not token:
                raise RuntimeError("verify response missing accessToken")
            return token
        except urllib.error.HTTPError as exc:
            last_err = exc
            if exc.code == 429 and attempt + 1 < retries:
                time.sleep(90 * (attempt + 1))
                continue
            raise
    if last_err:
        raise last_err
    raise RuntimeError("login failed")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default=DEFAULT_BASE)
    parser.add_argument("--phone", default=DEMO_PHONE)
    parser.add_argument("--token", help="Bearer token (skip OTP)")
    args = parser.parse_args()

    build = _get(args.base.replace("/api", "") + "/health/build")
    print(f"git_commit={str(build.get('git_commit') or '')[:12]}")

    token = args.token or _login(args.base, args.phone)
    results = []
    for case_id, message, lang in CASES:
        t0 = time.time()
        try:
            r = _post(f"{args.base}/chat", {"message": message, "language": lang}, token=token)
            ms = int((time.time() - t0) * 1000)
            row = {
                "id": case_id,
                "ms": ms,
                "validated": r.get("validated"),
                "reason": r.get("reason"),
                "llm_invoked": r.get("llm_invoked"),
                "answer_preview": (r.get("answer") or "")[:100],
            }
        except Exception as exc:  # noqa: BLE001
            row = {"id": case_id, "error": str(exc)[:200]}
        results.append(row)
        print(json.dumps(row))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
