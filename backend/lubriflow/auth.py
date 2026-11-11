import hashlib
import secrets
from types import SimpleNamespace
from datetime import timedelta
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, InvalidHashError
from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from .db import database
from .models import User, LoginSession, LoginAttempt, now

password_hasher = PasswordHasher()
dummy_hash = password_hasher.hash(secrets.token_urlsafe(32))


def hash_password(password):
    if not 12 <= len(password) <= 128:
        raise ValueError("Use a password of 12–128 characters.")
    return password_hasher.hash(password)


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def attempt_lock(db, email):
    key = digest(email.casefold())
    db.execute(insert(LoginAttempt).values(key=key, failures=0, window_start=now()).on_conflict_do_nothing())
    attempt = db.scalar(select(LoginAttempt).where(LoginAttempt.key == key).with_for_update())
    if attempt.window_start < now() - timedelta(minutes=15):
        attempt.failures, attempt.window_start = 0, now()
    if attempt.failures >= 10:
        db.commit()
        raise HTTPException(429, "Too many attempts. Try again in 15 minutes.")
    return attempt


def password_valid(user, password):
    try:
        valid = password_hasher.verify(user.password_hash if user else dummy_hash, password)
    except (VerificationError, InvalidHashError):
        valid = False
    return bool(user and user.active and valid)


def authenticate(db, email, password, code=""):
    from .mfa import verify_factor

    attempt = attempt_lock(db, email)
    user = db.scalar(select(User).where(User.email == email.casefold()).with_for_update())
    if not password_valid(user, password) or not verify_factor(user, code):
        attempt.failures += 1
        db.commit()
        raise HTTPException(401, "Invalid credentials. Include an authenticator or recovery code if enabled.")
    attempt.failures = 0
    token = secrets.token_urlsafe(48)
    db.add(LoginSession(token_hash=digest(token), user_id=user.id, expires_at=now() + timedelta(hours=8)))
    db.commit()
    return user, token


def current_user(request: Request, db=Depends(database)):
    token = request.cookies.get("lubriflow_session", "")
    session = db.get(LoginSession, digest(token)) if token else None
    user = db.get(User, session.user_id) if session and session.expires_at > now() else None
    if not user or not user.active:
        raise HTTPException(401, "Sign in required.")
    if user.role != 'supplier':
        from .company_access import company_role
        # Enforce explicit revocation on every authenticated request, including legacy home access.
        company_role(db, user, user.tenant_id)
    return user


def staff(request: Request, user=Depends(current_user), db=Depends(database)):
    if user.role == "supplier":
        raise HTTPException(403, "Supplier access is restricted to the portal.")
    from .company_access import company_role
    tenant_id = request.headers.get('x-lubriflow-company', user.tenant_id)
    selected_role = company_role(db, user, tenant_id)
    from .config import settings
    cfg = settings()
    if (cfg.environment == 'production' or cfg.require_privileged_mfa) and selected_role in {'admin', 'finance'} and not user.mfa_secret:
        raise HTTPException(403, 'MFA enrollment required before privileged company access.')
    # Request-local authorization context; never assign tenant/role on the persistent identity.
    return SimpleNamespace(id=user.id, name=user.name, email=user.email,
                           tenant_id=tenant_id, role=selected_role, active=user.active,
                           supplier_id=None, home_tenant_id=user.tenant_id)


def actor(user):
    return dict(id=user.id, name=user.name, role=user.role)


def role(user, *roles):
    if user.role not in roles:
        raise HTTPException(403, "Your role cannot perform this action.")
