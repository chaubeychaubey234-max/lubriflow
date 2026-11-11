"""Validate the running Next.js proxy and FastAPI session flow against a test database."""
import os
import secrets
from uuid import uuid4
import httpx
from lubriflow.db import Session
from lubriflow.models import Tenant, User
from lubriflow.domain import empty
from lubriflow.repository import save
from lubriflow.auth import hash_password

if 'lubriflow_test' not in os.environ.get('DATABASE_URL', ''):
    raise SystemExit('Run only with the dedicated PostgreSQL test database.')
email, password = str(uuid4())+'@example.test', secrets.token_urlsafe(24)
with Session.begin() as db:
    tenant = Tenant(name='HTTP integration', settings={}, series={})
    db.add(tenant)
    db.flush()
    save(db, tenant, empty(tenant.name))
    db.add(User(tenant_id=tenant.id, email=email, name='HTTP tester', role='admin', password_hash=hash_password(password)))
with httpx.Client(base_url='http://localhost:3000', timeout=20) as client:
    response = client.get('/')
    assert response.status_code == 200 and 'LubriFlow' in response.text
    assert client.get('/api/health').json()['status'] == 'ok'
    assert client.get('/api/workspace').status_code == 401
    client.headers.update({'Origin':'http://localhost:3000','X-Lubriflow-Request':'1'})
    response = client.post('/api/auth/login', json=dict(email=email,password=password))
    assert response.status_code == 200, response.text
    assert 'HttpOnly' in response.headers['set-cookie']
    assert client.get('/api/workspace').json()['state']['settings']['company'] == 'HTTP integration'
    assert client.post('/api/auth/logout', json={}).status_code == 200
    assert client.get('/api/workspace').status_code == 401
print('PASS Next.js page, API proxy, PostgreSQL health, cookie login, workspace access and logout.')
