import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import pytest
from cryptography.fernet import Fernet

pytest_plugins = ["test_api"]
PASSWORD = "test-password-at-least-12"


@pytest.fixture
def mfa_key(monkeypatch):
    from lubriflow.config import settings
    monkeypatch.setattr(settings(), "mfa_encryption_key", Fernet.generate_key().decode())


def test_rfc6238_vectors():
    from lubriflow.mfa import totp
    secret = base64.b32encode(b"12345678901234567890").decode()
    for timestamp, expected in [(59, "94287082"), (1111111109, "07081804"),
                                (1111111111, "14050471"), (1234567890, "89005924"),
                                (2000000000, "69279037"), (20000000000, "65353130")]:
        assert totp(secret, timestamp // 30, digits=8) == expected


def enroll(client, monkeypatch):
    from lubriflow import mfa
    monkeypatch.setattr(mfa, "time", lambda: 1800000000)
    result = client.post("/api/auth/mfa/begin", json=dict(password=PASSWORD))
    assert result.status_code == 200, result.text
    secret = result.json()["secret"]
    result = client.post("/api/auth/mfa/confirm", json=dict(password=PASSWORD, code=mfa.totp(secret, 60000000)))
    assert result.status_code == 200, result.text
    return secret, result.json()["recovery_codes"]


def user_email(client):
    from lubriflow.db import Session
    from lubriflow.models import User
    with Session() as db:
        return db.get(User, client.get("/api/auth/me").json()["id"]).email


def test_enrollment_encryption_login_replay_and_recovery(client, mfa_key, monkeypatch):
    from lubriflow.db import Session
    from lubriflow.models import User
    from lubriflow import mfa
    email = user_email(client)
    secret, codes = enroll(client, monkeypatch)
    with Session() as db:
        user = db.get(User, client.get("/api/auth/me").json()["id"])
        assert secret not in user.mfa_secret and codes[0] not in user.mfa_recovery
    client.post("/api/auth/logout", json={})
    login = dict(email=email, password=PASSWORD)
    assert client.post("/api/auth/login", json=login).status_code == 401
    assert client.post("/api/auth/login", json={**login, "code": mfa.totp(secret, 60000000)}).status_code == 401
    monkeypatch.setattr(mfa, "time", lambda: 1800000030)
    login["code"] = mfa.totp(secret, 60000001)
    assert client.post("/api/auth/login", json=login).status_code == 200
    assert client.post("/api/auth/login", json=login).status_code == 401
    assert client.post("/api/auth/login", json={**login, "code": codes[0]}).status_code == 200
    assert client.post("/api/auth/login", json={**login, "code": codes[0]}).status_code == 401
    assert client.get("/api/auth/mfa").json()["recovery_remaining"] == 9


def test_concurrent_recovery_code_only_works_once(client, mfa_key, monkeypatch):
    from lubriflow.auth import authenticate
    from lubriflow.db import Session
    from fastapi import HTTPException
    email = user_email(client)
    _, codes = enroll(client, monkeypatch)
    def login(_):
        with Session() as db:
            try:
                authenticate(db, email, PASSWORD, codes[0])
                return 200
            except HTTPException as error:
                return error.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(login, range(2))) == [200, 401]


def test_expired_enrollment_and_confirmation_lockout(client, mfa_key):
    from lubriflow.db import Session
    from lubriflow.models import User, now
    user_id = client.get("/api/auth/me").json()["id"]
    assert client.post("/api/auth/mfa/begin", json=dict(password=PASSWORD)).status_code == 200
    with Session.begin() as db:
        db.get(User, user_id).mfa_pending_expires = now() - timedelta(seconds=1)
    assert client.post("/api/auth/mfa/confirm", json=dict(password=PASSWORD, code="000000")).status_code == 400
    assert client.post("/api/auth/mfa/begin", json=dict(password=PASSWORD)).status_code == 200
    for _ in range(10):
        assert client.post("/api/auth/mfa/confirm", json=dict(password=PASSWORD, code="invalid")).status_code == 400
    assert client.post("/api/auth/mfa/confirm", json=dict(password=PASSWORD, code="invalid")).status_code == 429


def test_mfa_changes_revoke_other_sessions_and_require_factor(client, mfa_key, monkeypatch):
    from fastapi.testclient import TestClient
    from lubriflow.api import app
    email = user_email(client)
    with TestClient(app) as other:
        other.headers.update(dict(Origin="http://localhost:3000", **{"X-Lubriflow-Request": "1"}))
        assert other.post("/api/auth/login", json=dict(email=email, password=PASSWORD)).status_code == 200
        _, codes = enroll(client, monkeypatch)
        assert other.get("/api/auth/me").status_code == 401
        assert client.post("/api/auth/mfa/disable", json=dict(password=PASSWORD)).status_code == 400
        assert client.post("/api/auth/password", json=dict(current_password=PASSWORD, new_password="changed-password-123")).status_code == 400
        result = client.post("/api/auth/mfa/recovery", json=dict(password=PASSWORD, code=codes[0]))
        assert result.status_code == 200
        assert client.post("/api/auth/mfa/disable", json=dict(password=PASSWORD, code=codes[1])).status_code == 400
        assert client.post("/api/auth/mfa/disable", json=dict(password=PASSWORD, code=result.json()["recovery_codes"][0])).status_code == 200
        assert not client.get("/api/auth/mfa").json()["enabled"]
