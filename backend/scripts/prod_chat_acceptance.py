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
    ("pm_kisan", "What is PM-KISAN? Explain eligibility and benefits.", "EN", True),
    ("pmjay", "What is Ayushman Bharat PM-JAY? Explain eligibility and benefits for citizens.", "EN", True),
    ("gruha_lakshmi", "What is Gruha Lakshmi scheme? Explain eligibility and benefits.", "EN", True),
    ("gruha_jyothi", "What is Gruha Jyothi? Explain eligibility and benefits.", "EN", None),
    ("pmsby", "What is PM-SBY? Explain eligibility and benefits.", "EN", True),
    ("mgnrega", "What is MGNREGA? Explain eligibility and benefits.", "EN", True),
    (
        "unsupported_mars",
        "What is the Mars farmer subsidy eligibility in Karnataka?",
        "EN",
        False,
    ),
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
    parser.add_argument(
        "--expect-sha-prefix",
        default="",
        help="Fail if /health/build git_commit does not start with this prefix",
    )
    args = parser.parse_args()

    build = _get(args.base.replace("/api", "") + "/health/build")
    sha = str(build.get("git_commit") or "")
    print(f"git_commit={sha[:12]}")
    if args.expect_sha_prefix and not sha.startswith(args.expect_sha_prefix):
        print(f"FAIL: expected deployed sha prefix {args.expect_sha_prefix!r}")
        return 2

    token = args.token or _login(args.base, args.phone)
    results = []
    failures: list[str] = []
    for case_id, message, lang, expect_validated in CASES:
        t0 = time.time()
        try:
            r = _post(f"{args.base}/chat", {"message": message, "language": lang}, token=token)
            ms = int((time.time() - t0) * 1000)
            sources = r.get("sources") or []
            row = {
                "id": case_id,
                "ms": ms,
                "validated": r.get("validated"),
                "reason": r.get("reason"),
                "llm_invoked": r.get("llm_invoked"),
                "sources_n": len(sources),
                "request_id": r.get("request_id"),
                "answer_preview": (r.get("answer") or "")[:100],
            }
            if expect_validated is not None and row.get("validated") != expect_validated:
                failures.append(
                    f"{case_id}: expected validated={expect_validated} got {row.get('validated')}"
                )
            if expect_validated is True and row.get("reason") == "llm_unavailable":
                failures.append(f"{case_id}: LLM unavailable despite validated=true")
        except Exception as exc:  # noqa: BLE001
            row = {"id": case_id, "error": str(exc)[:200]}
            failures.append(f"{case_id}: {row['error']}")
        results.append(row)
        print(json.dumps(row))

    if failures:
        print("FAILURES:", "; ".join(failures))
        return 1
    print("PASS: all cases matched expectations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
