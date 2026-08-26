"""IVR-A3 server-side authorization bridge to existing citizen chat (no caller JWT)."""

from __future__ import annotations

import logging
from enum import Enum

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.citizen_account import CitizenAccount

logger = logging.getLogger("gramsakhi.ivr.auth")


class IvrAuthFailure(str, Enum):
    IVR_CITIZEN_UNAVAILABLE = "ivr_citizen_unavailable"


class IvrAuthError(Exception):
    def __init__(self, failure: IvrAuthFailure, message: str = "") -> None:
        super().__init__(message or failure.value)
        self.failure = failure


def get_ivr_citizen(db: Session) -> CitizenAccount:
    """
    Resolve the dedicated IVR bridge CitizenAccount for server-side chat calls.

    Never accepts caller-supplied account IDs. Configure via:
    - IVR_CITIZEN_ACCOUNT_ID (preferred), or
    - IVR_SYSTEM_ACCOUNT_PHONE (lookup by phone)
    """
    account_id = (settings.IVR_CITIZEN_ACCOUNT_ID or "").strip()
    if account_id:
        account = (
            db.query(CitizenAccount)
            .filter(CitizenAccount.id == account_id, CitizenAccount.is_active.is_(True))
            .first()
        )
        if account:
            return account
        logger.warning("ivr_citizen_missing account_id=%s", account_id[:8] + "…")
        raise IvrAuthError(IvrAuthFailure.IVR_CITIZEN_UNAVAILABLE)

    phone = (settings.IVR_SYSTEM_ACCOUNT_PHONE or "").strip()
    if phone:
        account = (
            db.query(CitizenAccount)
            .filter(CitizenAccount.phone_number == phone, CitizenAccount.is_active.is_(True))
            .first()
        )
        if account:
            return account
        logger.warning("ivr_citizen_missing phone=redacted")

    raise IvrAuthError(IvrAuthFailure.IVR_CITIZEN_UNAVAILABLE)
