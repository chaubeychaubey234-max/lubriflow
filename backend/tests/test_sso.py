"""SSO boundaries tested locally; live identity-provider acceptance is separate."""
from types import SimpleNamespace
from datetime import timedelta
import pytest
from fastapi import HTTPException, FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware
from test_api import client  # noqa: F401
from lubriflow import sso
from lubriflow.models import SSOAttempt, User, now
from lubriflow.auth import digest
from lubriflow.db import Session

CFG = SimpleNamespace(oidc_issuer='https://identity.example.test', oidc_required_amr=['mfa'], app_origin='http://localhost:3000', environment='test')


def test_binding_tenant_and_mfa_boundaries(client, monkeypatch):  # noqa: F811
    monkeypatch.setattr(sso, 'settings', lambda: CFG)
    actor = client.get('/api/auth/me').json()
    # API returns the current account, whose ID is required for explicit linking.
    with Session() as db:
        user = db.get(User, actor['id'])
        uid = user.id
    body = {'user_id': uid, 'subject': uid}
    assert client.post('/api/auth/sso/bindings', json=body).status_code == 200
    with Session() as db:
        claims = {'iss': CFG.oidc_issuer, 'sub': uid, 'amr': ['mfa']}
        assert sso.mapped_user(db, claims, CFG).id == uid
        for invalid in [dict(claims, iss='https://evil.test'), dict(claims, sub='unknown'), dict(claims, amr=[]), dict(claims, amr=[{}])]:
            with pytest.raises(HTTPException):
                sso.mapped_user(db, invalid, CFG)
        user = db.get(User, uid)
        user.active = False
        db.flush()
        with pytest.raises(HTTPException):
            sso.mapped_user(db, claims, CFG)
        db.rollback()
    assert client.post('/api/auth/sso/bindings', json={'user_id':'missing', 'subject':'foreign'}).status_code == 404
    assert client.delete('/api/auth/sso/bindings').status_code == 422
    assert client.request('DELETE', '/api/auth/sso/bindings', json=body).status_code == 200
    assert client.get('/api/workspace').status_code == 401  # unlink revokes sessions


def test_callback_missing_expired_and_failed_state(monkeypatch):
    monkeypatch.setattr(sso, 'settings', lambda: CFG)
    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key='test-secret-at-least-32-characters')
    app.include_router(sso.router)
    class RejectProvider:
        async def authorize_access_token(self, request):
            raise ValueError('invalid signature/nonce/code')
    monkeypatch.setattr(sso, 'provider', lambda: RejectProvider())
    with Session.begin() as db:
        for state, age in [('expired-test-state', -1), ('rejected-test-state', 5)]:
            existing = db.get(SSOAttempt, digest(state))
            if existing:
                db.delete(existing)
                db.flush()
            db.add(SSOAttempt(state_hash=digest(state), expires_at=now()+timedelta(minutes=age)))
    with TestClient(app) as c:
        for state in ['unknown', 'expired-test-state', 'rejected-test-state']:
            response = c.get('/api/auth/sso/callback', params={'state':state,'code':'invalid'})
            assert response.status_code == 401
            assert 'lubriflow_session=' not in response.headers.get('set-cookie','')
    with Session() as db:
        assert db.get(SSOAttempt, digest('rejected-test-state')) is None


def test_real_signed_id_token_validation():
    import asyncio
    import time
    from joserfc import jwt
    from joserfc.jwk import RSAKey
    from authlib.integrations.starlette_client import OAuth
    key = RSAKey.generate_key(2048)
    oidc_client = OAuth().register('test', client_id='client', issuer=CFG.oidc_issuer,
        jwks={'keys':[key.as_dict(private=False)]}, id_token_signing_alg_values_supported=['RS256'])
    claims = dict(iss=CFG.oidc_issuer, sub='subject', aud='client', exp=int(time.time())+300,
                  iat=int(time.time()), nonce='expected', amr=['mfa'])
    def parse(values, signing_key=key):
        encoded = jwt.encode({'alg':'RS256'}, values, signing_key)
        return asyncio.run(oidc_client.parse_id_token({'id_token':encoded,'access_token':'opaque'}, nonce='expected'))
    assert parse(claims)['sub'] == 'subject'
    for invalid in [dict(claims, nonce='wrong'), dict(claims, aud='other'), dict(claims, iss='https://evil.test'), dict(claims, exp=1)]:
        with pytest.raises(Exception):
            parse(invalid)
    with pytest.raises(Exception):
        parse(claims, RSAKey.generate_key(2048))
