pytest_plugins = ['test_api']


def test_required_mfa_blocks_privileged_workspace_but_allows_enrollment(client, monkeypatch):
    from lubriflow.config import settings
    cfg = settings()
    monkeypatch.setattr(cfg, 'require_privileged_mfa', True)
    assert client.get('/api/workspace').status_code == 403
    assert client.get('/api/finance').status_code == 403
    assert client.get('/api/auth/me').status_code == 200
    assert client.get('/api/auth/mfa').status_code == 200
    response = client.post('/api/auth/mfa/disable', json={'password': 'test-password-at-least-12'})
    assert response.status_code == 403


def test_nonprivileged_role_is_not_blocked_by_enrollment_policy(client, monkeypatch):
    from lubriflow.config import settings
    from lubriflow.db import Session
    from lubriflow.models import User
    uid = client.get('/api/auth/me').json()['id']
    with Session.begin() as db:
        db.get(User, uid).role = 'buyer'
    monkeypatch.setattr(settings(), 'require_privileged_mfa', True)
    assert client.get('/api/workspace').status_code == 200
