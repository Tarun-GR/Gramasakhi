"""
Create or update the dedicated FYP demo CitizenAccount (allowlisted phone only).

Usage (from backend/, with DATABASE_URL pointing at Supabase or local DB):

  .venv\\Scripts\\python.exe scripts\\provision_demo_citizen.py --phone 9999900001

Reads DEMO_LOGIN_PHONES from the environment when --phone is omitted.
"""

from __future__ import annotations

import argparse
import secrets
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.core import security  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.database.session import SessionLocal  # noqa: E402
from app.models.citizen_account import CitizenAccount  # noqa: E402
from app.services.demo_login import _normalize_phone, demo_phone_allowlist  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Provision FYP demo citizen account")
    parser.add_argument("--phone", help="10-digit demo mobile (defaults to first DEMO_LOGIN_PHONES entry)")
    parser.add_argument(
        "--display-name",
        default="FYP Demo Citizen",
        help="Display name stored on the citizen account",
    )
    args = parser.parse_args()

    phone_raw = args.phone or (demo_phone_allowlist()[0] if demo_phone_allowlist() else "")
    phone = _normalize_phone(phone_raw)
    if len(phone) != 10 or not phone.isdigit():
        print("ERROR: Provide a valid 10-digit demo phone via --phone or DEMO_LOGIN_PHONES.", file=sys.stderr)
        return 1

    db = SessionLocal()
    try:
        account = db.query(CitizenAccount).filter(CitizenAccount.phone_number == phone).first()
        if account:
            account.display_name = args.display_name
            account.is_active = True
            print(f"Updated existing demo citizen id={account.id} phone=***{phone[-4:]}")
        else:
            account = CitizenAccount(
                phone_number=phone,
                password_hash=security.get_password_hash(secrets.token_urlsafe(32)),
                display_name=args.display_name,
                is_active=True,
            )
            db.add(account)
            db.commit()
            db.refresh(account)
            print(f"Created demo citizen id={account.id} phone=***{phone[-4:]}")
        db.commit()
    finally:
        db.close()

    if not settings.DEMO_LOGIN_ENABLED:
        print(
            "NOTE: DEMO_LOGIN_ENABLED is false in this environment. "
            "Set DEMO_LOGIN_ENABLED=true on Render after provisioning.",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
