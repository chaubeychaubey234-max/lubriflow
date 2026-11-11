from uuid import uuid4

pytest_plugins = ['test_api']


def add_user(client, email, role='buyer'):
    response = client.post('/api/users', json=dict(email=email, name='Staff member', role=role,
        password='member-password-123'))
    assert response.status_code == 200, response.text
    return response.json()['id']


def test_admin_can_assign_update_and_revoke_selected_company_membership(client):
    email = str(uuid4()) + '@example.test'
    person_id = add_user(client, email)
    result = client.post('/api/companies/members', json={'email': email, 'role': 'finance'})
    assert result.status_code == 200 and result.json()['role'] == 'finance'
    row = next(row for row in client.get('/api/companies/members').json() if row['id'] == person_id)
    assert row['explicit'] and row['role'] == 'finance'
    assert client.post('/api/companies/members', json={'email': email, 'role': 'buyer'}).status_code == 200
    assert client.post('/api/companies/members/' + person_id + '/revoke').status_code == 200
    assert next(row for row in client.get('/api/companies/members').json() if row['id'] == person_id)['active'] is False


def test_membership_admin_rejects_unknown_role_self_revoke_and_last_admin(client):
    own = client.get('/api/auth/me').json()['id']
    assert client.post('/api/companies/members', json={'email': 'no@example.test', 'role': 'buyer'}).status_code == 400
    assert client.post('/api/companies/members', json={'email': 'no@example.test', 'role': 'owner'}).status_code == 400
    assert client.post('/api/companies/members/' + own + '/revoke').status_code == 400


def test_buyer_cannot_manage_company_memberships(client):
    from lubriflow.db import Session
    from lubriflow.models import User
    uid = client.get('/api/auth/me').json()['id']
    with Session.begin() as db:
        db.get(User, uid).role = 'buyer'
    assert client.get('/api/companies/members').status_code == 403
    assert client.post('/api/companies/members', json={'email': 'a@example.test', 'role': 'buyer'}).status_code == 403
