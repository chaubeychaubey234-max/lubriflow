from datetime import datetime, timedelta, timezone
from uuid import uuid4
from test_api import mutation, setup_order
from lubriflow import approval_policy

pytest_plugins = ["test_api"]


def test_delegation_validates_database_tenant_role_and_active_user(client):
    _, _, po = setup_order(client)
    assert mutation(client, "submit", dict(id=po)).status_code == 200
    user = client.post('/api/users', json=dict(name="Substitute", email=uuid4().hex+'@example.test',
        role='approver', password='a-test-password-long-enough')).json()
    # User creation response is deliberately minimal; query the authorized directory.
    users = client.get('/api/users').json()
    target = next(u for u in users if u['name'] == 'Substitute')
    assert mutation(client, 'delegateApproval', dict(id=po, userId=uuid4().hex, validHours=24,
        reason='Absence', approvalTarget=target)).status_code == 400
    assert mutation(client, 'delegateApproval', dict(id=po, userId=target['id'], validHours=24,
        reason='Absence')).status_code == 200
    assert client.post('/api/users/'+target['id']+'/disable',json={}).status_code == 200
    assert mutation(client, 'delegateApproval', dict(id=po, userId=target['id'], validHours=24,
        reason='Disabled')).status_code == 400
    assert user is not None


def test_worker_escalates_once_in_manual_mode(client, monkeypatch):
    current = [datetime(2026, 11, 10, 8, tzinfo=timezone.utc)]
    monkeypatch.setattr(approval_policy, 'utc_now', lambda: current[0])
    _, _, po = setup_order(client)
    assert mutation(client, 'master', dict(collection='approvalPolicies',name='Purchases',minAmount=0,
        maxAmount=100000,approvalStages='approver',approvalHours=1,escalationRole='finance')).status_code == 200
    assert mutation(client, 'submit', dict(id=po)).status_code == 200
    current[0] += timedelta(hours=2)
    approval_policy.escalation_once()
    approval_policy.escalation_once()
    state = client.get('/api/workspace').json()['state']
    order = next(o for o in state['orders'] if o['id'] == po)
    assert state['settings']['mode'] == 'manual'
    assert order['status'] == 'Pending approval'
    assert len(order['approvalEvents']) == 1
    assert order['approvalEscalation']['role'] == 'finance'
