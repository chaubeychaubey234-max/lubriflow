from uuid import uuid4
from test_api import mutation, setup_order

pytest_plugins = ['test_api']


def test_request_company_role_never_changes_identity_and_revocation_applies(client):
    from lubriflow.db import Session
    from lubriflow.models import User, Tenant, CompanyMembership
    from lubriflow.repository import save
    from lubriflow.company_defaults import new_uae_company
    uid = client.get('/api/auth/me').json()['id']
    _, _, po = setup_order(client)
    rev = client.get('/api/workspace').json()['revision']
    uploaded = client.post('/api/documents', data=dict(collection='orders', target=po, revision=rev),
                           files={'file': ('isolation.pdf', b'%PDF-1.4\nHome only\n%%EOF', 'application/pdf')})
    assert uploaded.status_code == 200, uploaded.text
    document_id = uploaded.json()['id']
    original = client.get('/api/workspace').json()
    with Session.begin() as db:
        home = db.get(User, uid).tenant_id
        second = Tenant(name='Second UAE company', settings={}, series={})
        db.add(second)
        db.flush()
        save(db, second, new_uae_company(second.name))
        second_id = second.id
        db.add(CompanyMembership(user_id=uid, tenant_id=second_id, role='viewer', active=True))
    client.headers['X-Lubriflow-Company'] = second_id
    view = client.get('/api/workspace').json()
    assert view['state']['settings']['company'] == 'Second UAE company'
    assert view['actor']['role'] == 'viewer'
    assert client.get('/api/finance').status_code == 403
    denied = client.get('/api/documents/' + document_id)
    assert denied.status_code in {400, 403, 404}
    assert b'Home only' not in denied.content
    assert mutation(client, 'supplier', {'name': 'Forbidden'}).status_code == 400
    with Session.begin() as db:
        user = db.get(User, uid)
        assert user.tenant_id == home and user.role == 'admin'
        membership = db.get(CompanyMembership, (uid, second_id))
        membership.role = 'buyer'
    assert mutation(client, 'supplier', {'name': 'Second company supplier'}).status_code == 200
    del client.headers['X-Lubriflow-Company']
    assert b'Home only' in client.get('/api/documents/' + document_id).content
    assert client.get('/api/workspace').json()['state']['suppliers'] == original['state']['suppliers']
    client.headers['X-Lubriflow-Company'] = str(uuid4())
    assert client.get('/api/workspace').status_code == 403
    assert client.get('/api/finance').status_code == 403
    client.headers['X-Lubriflow-Company'] = second_id
    with Session.begin() as db:
        db.get(CompanyMembership, (uid, second_id)).active = False
    assert client.get('/api/workspace').status_code == 403
    assert client.get('/api/inventory-report').status_code == 403
