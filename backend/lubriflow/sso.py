"""OIDC authorization code + PKCE. No email matching or just-in-time role assignment."""
import secrets
from datetime import timedelta
from functools import lru_cache
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, delete
from authlib.integrations.starlette_client import OAuth
from .config import settings
from .db import database
from .auth import current_user, role, digest
from .models import SSOIdentity, SSOAttempt, User, LoginSession, now
from .models import AuditEvent
from uuid import uuid4

def record(db, user, action):
    event_id, timestamp = "EV-" + str(uuid4()), now()
    db.add(AuditEvent(tenant_id=user.tenant_id, id=event_id, at=timestamp, actor_id=user.id, action=action,
        payload=dict(id=event_id, at=timestamp.isoformat(), actor=user.name, actorId=user.id, action=action, detail=action)))

router = APIRouter(prefix="/api/auth/sso")


@lru_cache
def provider():
    cfg = settings()
    oauth = OAuth()
    return oauth.register("company", client_id=cfg.oidc_client_id, client_secret=cfg.oidc_client_secret,
        server_metadata_url=cfg.oidc_issuer.rstrip("/") + "/.well-known/openid-configuration",
        client_kwargs={"scope": "openid profile email", "code_challenge_method": "S256", "timeout": 15},
        claims_options={"iss": {"essential": True, "value": cfg.oidc_issuer}})


@router.get("/config")
def configuration():
    return dict(enabled=bool(settings().oidc_issuer), passwordEnabled=not settings().oidc_only)


@router.get("/login")
async def login(request: Request, db=Depends(database)):
    cfg = settings()
    if not cfg.oidc_issuer:
        raise HTTPException(404, "SSO is not configured.")
    # Bound table size by clearing expired attempts; state is also browser-cookie-bound.
    db.execute(delete(SSOAttempt).where(SSOAttempt.expires_at < now()))
    state = secrets.token_urlsafe(32)
    try:
        response = await provider().authorize_redirect(request, cfg.app_origin + "/api/auth/sso/callback", state=state)
    except Exception:
        request.session.clear()
        raise HTTPException(503, "Identity provider is unavailable.") from None
    db.add(SSOAttempt(state_hash=digest(state), expires_at=now() + timedelta(minutes=5)))
    db.commit()
    return response


def mapped_user(db, claims, cfg):
    if claims.get("iss") != cfg.oidc_issuer or not isinstance(claims.get("sub"), str):
        raise HTTPException(401, "Invalid identity claims.")
    amr = claims.get("amr", [])
    if not isinstance(amr, list) or not all(isinstance(x, str) for x in amr) or not set(cfg.oidc_required_amr).issubset(set(amr)):
        raise HTTPException(403, "Identity provider must supply the required MFA evidence.")
    link = db.get(SSOIdentity, (cfg.oidc_issuer, claims["sub"]))
    user = db.get(User, link.user_id) if link else None
    if not user or not user.active or user.role == "supplier":
        raise HTTPException(403, "This identity is not linked to an active staff account.")
    return user


@router.get("/callback")
async def callback(request: Request, db=Depends(database)):
    cfg = settings()
    if not cfg.oidc_issuer:
        raise HTTPException(404, "SSO is not configured.")
    state = request.query_params.get("state", "")
    attempt = db.scalar(select(SSOAttempt).where(SSOAttempt.state_hash == digest(state)).with_for_update())
    if not attempt or attempt.expires_at <= now():
        raise HTTPException(401, "Login expired or already used. Start sign-in again.")
    db.delete(attempt)
    db.commit()  # Consume even if the provider rejects the code; concurrent callbacks cannot replay it.
    try:
        token = await provider().authorize_access_token(request)
        claims = token.get("userinfo")
        if not token.get("id_token") or not claims:
            raise ValueError("ID token required")
    except Exception:
        request.session.clear()
        raise HTTPException(401, "SSO verification failed. Start sign-in again.") from None
    request.session.clear()  # Never retain provider tokens or identity data in browser storage.
    user = mapped_user(db, claims, cfg)
    session = secrets.token_urlsafe(48)
    db.add(LoginSession(token_hash=digest(session), user_id=user.id, expires_at=now() + timedelta(hours=8)))
    record(db, user, "SSO sign-in")
    db.commit()
    response = RedirectResponse(cfg.app_origin + "/", status_code=303)
    response.set_cookie("lubriflow_session", session, httponly=True, secure=cfg.environment == "production",
                        samesite="lax", max_age=8 * 3600, path="/")
    return response


class Binding(BaseModel):
    user_id: str = Field(max_length=36)
    subject: str = Field(min_length=1, max_length=255)


@router.post("/bindings")
def bind(body: Binding, user=Depends(current_user), db=Depends(database)):
    role(user, "admin")
    cfg = settings()
    if not cfg.oidc_issuer:
        raise HTTPException(400, "Configure the identity provider first.")
    target = db.get(User, body.user_id)
    if not target or target.tenant_id != user.tenant_id or target.role == "supplier":
        raise HTTPException(404, "Staff user not found in your company.")
    link = db.get(SSOIdentity, (cfg.oidc_issuer, body.subject))
    if link and link.user_id != target.id:
        raise HTTPException(409, "Identity is already bound to another account.")
    if not link:
        db.add(SSOIdentity(issuer=cfg.oidc_issuer, subject=body.subject, user_id=target.id))
    record(db, user, "SSO identity linked to " + target.id)
    db.commit()
    return {"ok": True}


@router.get("/bindings")
def bindings(user=Depends(current_user), db=Depends(database)):
    role(user, "admin")
    rows = db.scalars(select(SSOIdentity).join(User).where(User.tenant_id == user.tenant_id))
    return [{"issuer": row.issuer, "subject": row.subject, "user_id": row.user_id} for row in rows]


@router.delete("/bindings")
def unbind(body: Binding, user=Depends(current_user), db=Depends(database)):
    role(user, "admin")
    target = db.get(User, body.user_id)
    if not target or target.tenant_id != user.tenant_id:
        raise HTTPException(404, "Staff user not found in your company.")
    link = db.get(SSOIdentity, (settings().oidc_issuer, body.subject))
    if not link or link.user_id != target.id:
        raise HTTPException(404, "Identity binding not found.")
    db.delete(link)
    db.execute(delete(LoginSession).where(LoginSession.user_id == target.id))
    record(db, user, "SSO identity removed from " + target.id)
    db.commit()
    return {"ok": True}
