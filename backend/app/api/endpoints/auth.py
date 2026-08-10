from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from datetime import datetime, timedelta, timezone
import secrets

from app.database.session import get_db
from app.models.family_account import FamilyAccount, OTPVerification
from app.schemas.auth import (
    LoginRequest,
    TokenResponse,
    OTPRequest,
    OTPVerifyRequest,
    RegisterRequest,
    ForgotPasswordResetRequest,
)
from app.core import security

router = APIRouter()


def _token_payload(account: FamilyAccount) -> dict:
    token = security.create_access_token(subject=str(account.id))
    return {
        "accessToken": token,
        "citizen_account_id": account.id,
        "family_account_id": account.id,  # backward-compatible alias
        "phone_number": account.phone_number,
    }


@router.post("/login", response_model=TokenResponse)
def login(request: LoginRequest, db: Session = Depends(get_db)):
    account = db.query(FamilyAccount).filter(
        FamilyAccount.phone_number == request.phone_number
    ).first()
    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No account found with this mobile number.",
        )

    if not account.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account has been deactivated. Please contact support.",
        )

    if request.login_type == "password":
        if not request.password:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Password is required for password login.",
            )
        if not security.verify_password(request.password, account.password_hash):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect password. Please try again.",
            )
    elif request.login_type == "otp":
        otp_rec = (
            db.query(OTPVerification)
            .filter(
                OTPVerification.phone_number == request.phone_number,
                OTPVerification.verified == True,  # noqa: E712
            )
            .order_by(OTPVerification.created_at.desc())
            .first()
        )
        if not otp_rec or otp_rec.expires_at < datetime.now(timezone.utc):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="OTP verification has expired or is invalid. Please verify OTP first.",
            )
        otp_rec.verified = False
        db.commit()
    else:
        raise HTTPException(status_code=400, detail="Invalid login method type.")

    return _token_payload(account)


@router.post("/otp/send")
def send_otp(request: OTPRequest, db: Session = Depends(get_db)):
    code = security.generate_otp()
    otp_hash = security.get_otp_hash(code)

    otp_record = OTPVerification(
        phone_number=request.phone_number,
        otp_hash=otp_hash,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=3),
        verified=False,
        attempt_count=0,
    )
    db.add(otp_record)
    db.commit()

    print("\n==============================================", flush=True)
    print(f"[SMS GATEWAY SIMULATOR] Sending code to +91 {request.phone_number}", flush=True)
    print(f"VERIFICATION OTP: {code}", flush=True)
    print("==============================================\n", flush=True)

    return {"message": "OTP verification code sent. Check server logs."}


@router.post("/otp/verify")
def verify_otp(request: OTPVerifyRequest, db: Session = Depends(get_db)):
    otp_rec = (
        db.query(OTPVerification)
        .filter(
            OTPVerification.phone_number == request.phone_number,
            OTPVerification.verified == False,  # noqa: E712
        )
        .order_by(OTPVerification.created_at.desc())
        .first()
    )

    if not otp_rec:
        raise HTTPException(status_code=400, detail="No active OTP request found for this phone.")

    if otp_rec.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="OTP has expired. Please request a new code.")

    if otp_rec.attempt_count >= 5:
        raise HTTPException(status_code=400, detail="Too many failed verification attempts.")

    if not security.verify_otp_hash(request.code, otp_rec.otp_hash):
        otp_rec.attempt_count += 1
        db.commit()
        raise HTTPException(status_code=400, detail="Invalid OTP code.")

    otp_rec.verified = True
    db.commit()

    account = db.query(FamilyAccount).filter(
        FamilyAccount.phone_number == request.phone_number
    ).first()
    if account:
        return _token_payload(account)

    return {"message": "OTP verification completed. Proceed to register your citizen account."}


@router.post("/register")
def register(request: RegisterRequest, db: Session = Depends(get_db)):
    existing = db.query(FamilyAccount).filter(
        FamilyAccount.phone_number == request.credentials.phone_number
    ).first()
    if existing:
        raise HTTPException(
            status_code=400,
            detail="An account with this mobile number already exists. Please login.",
        )

    raw_password = request.credentials.password or secrets.token_urlsafe(24)
    password_hash = security.get_password_hash(raw_password)
    account = FamilyAccount(
        phone_number=request.credentials.phone_number,
        password_hash=password_hash,
        display_name=request.display_name,
    )
    db.add(account)
    db.commit()
    db.refresh(account)

    return {
        "message": "Registration successful.",
        "citizen_account_id": account.id,
        "phone_number": account.phone_number,
    }


@router.post("/forgot-password/request")
def request_password_reset(request: OTPRequest, db: Session = Depends(get_db)):
    account = db.query(FamilyAccount).filter(
        FamilyAccount.phone_number == request.phone_number
    ).first()
    if not account:
        raise HTTPException(status_code=400, detail="Account with this mobile number does not exist.")

    code = security.generate_otp()
    otp_hash = security.get_otp_hash(code)

    otp_record = OTPVerification(
        phone_number=request.phone_number,
        otp_hash=otp_hash,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=3),
        verified=False,
        attempt_count=0,
    )
    db.add(otp_record)
    db.commit()

    print("\n==============================================", flush=True)
    print(
        f"[SMS GATEWAY SIMULATOR] Password reset requested for +91 {request.phone_number}",
        flush=True,
    )
    print(f"PASSWORD RESET OTP: {code}", flush=True)
    print("==============================================\n", flush=True)

    return {"message": "OTP verification code sent. Check server logs."}


@router.post("/forgot-password/reset")
def reset_password(request: ForgotPasswordResetRequest, db: Session = Depends(get_db)):
    otp_rec = (
        db.query(OTPVerification)
        .filter(
            OTPVerification.phone_number == request.phone_number,
            OTPVerification.verified == False,  # noqa: E712
        )
        .order_by(OTPVerification.created_at.desc())
        .first()
    )

    if not otp_rec or otp_rec.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="Invalid or expired OTP code.")

    if not security.verify_otp_hash(request.otp_code, otp_rec.otp_hash):
        otp_rec.attempt_count += 1
        db.commit()
        raise HTTPException(status_code=400, detail="Invalid OTP code.")

    account = db.query(FamilyAccount).filter(
        FamilyAccount.phone_number == request.phone_number
    ).first()
    if not account:
        raise HTTPException(status_code=400, detail="Account not found.")

    account.password_hash = security.get_password_hash(request.new_password)
    otp_rec.verified = True
    db.commit()

    return {"message": "Password updated successfully."}
