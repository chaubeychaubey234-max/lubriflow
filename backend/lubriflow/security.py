"""Authenticated MFA management, with password proof and shared attempt limits."""
from datetime import timedelta
from urllib.parse import quote
from uuid import uuid4
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select, delete
from .auth import current_user, attempt_lock, password_valid, digest
from .config import settings
from .db import database
from .models import User, LoginSession, AuditEvent, now
from .mfa import encrypt, decrypt, new_secret, matching_step, verify_factor, new_recovery_codes, recovery_hash

router = APIRouter(prefix="/api/auth/mfa")


class Proof(BaseModel):
    password: str = Field(min_length=1, max_length=128)
    code: str = Field(default="", max_length=100)


def proof(db, user, password, code="", factor=True):
    attempt = attempt_lock(db, user.email)
    user = db.scalar(select(User).where(User.id == user.id).with_for_update().execution_options(populate_existing=True))
    if not password_valid(user, password) or (factor and not verify_factor(user, code)):
        attempt.failures += 1
        db.commit()
        raise HTTPException(400, "Invalid password or authenticator/recovery code.")
    return user


def record(db, user, action):
    event_id, timestamp = "EV-" + str(uuid4()), now()
    db.add(AuditEvent(
        tenant_id=user.tenant_id, id=event_id, at=timestamp, actor_id=user.id, action=action,
        payload=dict(id=event_id, at=timestamp.isoformat(), actor=user.name, actorId=user.id,
                     action=action, detail="Account security updated; other sessions revoked."),
    ))


def revoke_others(db, user, request):
    current = digest(request.cookies.get("lubriflow_session", ""))
    db.execute(delete(LoginSession).where(LoginSession.user_id == user.id, LoginSession.token_hash != current))


@router.get("")
def status(user=Depends(current_user)):
    return dict(enabled=bool(user.mfa_secret), available=bool(settings().mfa_encryption_key),
                recovery_remaining=len(user.mfa_recovery))


@router.post("/begin")
def begin(body: Proof, user=Depends(current_user), db=Depends(database)):
    user = proof(db, user, body.password)
    if user.mfa_secret:
        raise HTTPException(409, "Disable the existing authenticator before replacing it.")
    secret = new_secret()
    user.mfa_pending = encrypt(secret)
    user.mfa_pending_expires = now() + timedelta(minutes=10)
    db.commit()
    return dict(secret=secret, uri="otpauth://totp/" + quote("LubriFlow:" + user.email, safe="") +
                "?secret=" + secret + "&issuer=LubriFlow&algorithm=SHA1&digits=6&period=30")


@router.post("/confirm")
def confirm(body: Proof, request: Request, user=Depends(current_user), db=Depends(database)):
    user = proof(db, user, body.password, factor=False)
    if user.mfa_secret or not user.mfa_pending or user.mfa_pending_expires <= now():
        raise HTTPException(400, "Enrollment expired or is already complete. Start again if needed.")
    step = matching_step(decrypt(user.mfa_pending), body.code.strip())
    if step is None:
        attempt = attempt_lock(db, user.email)
        attempt.failures += 1
        db.commit()
        raise HTTPException(400, "Invalid authenticator code.")
    codes = new_recovery_codes()
    user.mfa_secret, user.mfa_last_step = user.mfa_pending, step
    user.mfa_pending, user.mfa_pending_expires = None, None
    user.mfa_recovery = [recovery_hash(code) for code in codes]
    revoke_others(db, user, request)
    record(db, user, "MFA enabled")
    db.commit()
    return dict(recovery_codes=codes)


@router.post("/recovery")
def regenerate(body: Proof, request: Request, user=Depends(current_user), db=Depends(database)):
    user = proof(db, user, body.password, body.code)
    if not user.mfa_secret:
        raise HTTPException(400, "Enable your authenticator first.")
    codes = new_recovery_codes()
    user.mfa_recovery = [recovery_hash(code) for code in codes]
    revoke_others(db, user, request)
    record(db, user, "MFA recovery codes replaced")
    db.commit()
    return dict(recovery_codes=codes)


@router.post("/disable")
def disable(body: Proof, request: Request, user=Depends(current_user), db=Depends(database)):
    from .models import CompanyMembership
    cfg = settings()
    privileged_membership = db.scalar(select(CompanyMembership.user_id).where(
        CompanyMembership.user_id == user.id, CompanyMembership.active.is_(True),
        CompanyMembership.role.in_(['admin', 'finance'])).limit(1))
    if (cfg.environment == 'production' or cfg.require_privileged_mfa) and (user.role in {'admin', 'finance'} or privileged_membership):
        raise HTTPException(403, 'MFA is mandatory for your privileged company roles.')
    user = proof(db, user, body.password, body.code)
    user.mfa_secret, user.mfa_pending, user.mfa_pending_expires, user.mfa_last_step = None, None, None, None
    user.mfa_recovery = []
    revoke_others(db, user, request)
    record(db, user, "MFA disabled")
    db.commit()
    return dict(ok=True)
