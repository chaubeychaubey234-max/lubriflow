import pytest
from fastapi import HTTPException

pytest_plugins = ['test_api']


def test_company_directory_is_scoped_and_revocation_is_immediate(client):
    from lubriflow.db import Session
    from lubriflow.models import User, Tenant, CompanyMembership
    from lubriflow.company_access import company_role
    uid = client.get('/api/auth/me').json()['id']
    with Session.begin() as db:
        user = db.get(User, uid)
        home = user.tenant_id
        permitted, forbidden = Tenant(name='Permitted company', settings={}, series={}), Tenant(name='Hidden company', settings={}, series={})
        db.add_all([permitted, forbidden])
        db.flush()
        permitted_id, forbidden_id = permitted.id, forbidden.id
        db.add(CompanyMembership(user_id=uid, tenant_id=permitted_id, role='viewer', active=True))
        db.flush()
        assert company_role(db, user, permitted_id) == 'viewer'
        with pytest.raises(HTTPException): company_role(db, user, forbidden_id)
        assert user.tenant_id == home and user.role == 'admin'
    response = client.get('/api/companies')
    assert response.status_code == 200
    assert {row['id'] for row in response.json()['companies']} == {home, permitted_id}
    assert response.json()['switchingEnabled']
    with Session.begin() as db:
        db.get(CompanyMembership, (uid, permitted_id)).active = False
    assert {row['id'] for row in client.get('/api/companies').json()['companies']} == {home}


def test_explicit_inactive_home_membership_cannot_fall_back(client):
    from lubriflow.db import Session
    from lubriflow.models import User, CompanyMembership
    from lubriflow.company_access import company_role
    uid = client.get('/api/auth/me').json()['id']
    with Session.begin() as db:
        user = db.get(User, uid)
        db.add(CompanyMembership(user_id=uid, tenant_id=user.tenant_id, role='admin', active=False))
        db.flush()
        with pytest.raises(HTTPException): company_role(db, user, user.tenant_id)
    assert client.get('/api/companies').status_code == 403
    assert client.get('/api/workspace').status_code == 403
    assert client.get('/api/finance').status_code == 403
