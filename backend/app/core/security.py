from datetime import datetime, timedelta, timezone
from typing import Any, Optional, Union
from jose import jwt
import bcrypt
import hashlib
import hmac
import secrets
from app.core.config import settings

def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        pwd_bytes = plain_password.encode('utf-8')[:72]
        hash_bytes = hashed_password.encode('utf-8')
        return bcrypt.checkpw(pwd_bytes, hash_bytes)
    except Exception:
        return False

def get_password_hash(password: str) -> str:
    pwd_bytes = password.encode('utf-8')[:72]
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(pwd_bytes, salt).decode('utf-8')

def create_access_token(
    subject: Union[str, Any],
    expires_delta: timedelta = None,
    token_use: Optional[str] = None,
) -> str:
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)

    to_encode = {"exp": expire, "sub": str(subject)}
    if token_use:
        to_encode["token_use"] = token_use
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt


def decode_access_token(token: str) -> dict:
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])


def token_use_allowed(payload: dict, expected: str) -> bool:
    """Old tokens omit token_use; new tokens must match the endpoint audience."""
    use = payload.get("token_use")
    if use is None:
        return True
    return use == expected

def generate_otp() -> str:
    """Generates a random 6-digit numeric string for verification."""
    return "".join(secrets.choice("0123456789") for _ in range(6))

def get_otp_hash(otp: str) -> str:
    """HMAC-SHA256 of the OTP using SECRET_KEY as pepper (not reversible without the key)."""
    key = (settings.SECRET_KEY or "").encode("utf-8")
    return hmac.new(key, otp.encode("utf-8"), hashlib.sha256).hexdigest()

def verify_otp_hash(otp: str, hashed_otp: str) -> bool:
    """Verifies OTP against current HMAC hash, then legacy unsalted SHA-256."""
    if not hashed_otp:
        return False
    current = get_otp_hash(otp)
    if hmac.compare_digest(current, hashed_otp):
        return True
    legacy = hashlib.sha256(otp.encode("utf-8")).hexdigest()
    return hmac.compare_digest(legacy, hashed_otp)
