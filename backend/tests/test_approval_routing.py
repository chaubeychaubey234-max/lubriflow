from copy import deepcopy
from datetime import datetime, timedelta, timezone
import pytest
from test_domain import ADMIN, BUYER, APPROVER, FINANCE
from test_approval_matrix import policy, order
from lubriflow.domain import act, get, RuleError
from lubriflow import approval_policy

pytest_plugins = ["test_domain"]


@pytest.fixture
def clock(monkeypatch):
    current = [datetime(2026, 11, 10, 8, tzinfo=timezone.utc)]
    monkeypatch.setattr(approval_policy, "utc_now", lambda: current[0])
    return current


def delegate(s, po, target="substitute", role="approver"):
    admin = dict(ADMIN, approvalTarget=dict(id=target, name=target, role=role, active=True))
    return act(s, "delegateApproval", dict(id=po, userId=target, validHours=2, reason="Approver absent"), admin)


def test_stage_deadline_and_escalation_are_idempotent(s, clock):
    policy(s, approvalHours=2, escalationRole="finance")
    po = order(s)
    act(s, "submit", dict(id=po), BUYER)
    with pytest.raises(RuleError, match="not passed"):
        act(s, "escalateApproval", dict(id=po), ADMIN)
    clock[0] += timedelta(hours=2)
    act(s, "escalateApproval", dict(id=po), dict(id="worker", role="system"))
    record = get(s, "orders", po)
    assert record["status"] == "Pending approval"
    assert record["approvalEscalation"]["role"] == "finance"
    before = deepcopy(s)
    with pytest.raises(RuleError, match="already"):
        act(s, "escalateApproval", dict(id=po), ADMIN)
    assert s == before
    act(s, "approve", dict(id=po), APPROVER)
    record = get(s, "orders", po)
    assert "approvalEscalation" not in record
    assert datetime.fromisoformat(record["approvalDueAt"]) == clock[0] + timedelta(hours=2)
    act(s, "approve", dict(id=po), FINANCE)
    assert get(s, "orders", po)["approvalDueAt"] is None


def test_named_delegation_expires_without_bypassing_stage(s, clock):
    policy(s)
    po = order(s)
    act(s, "submit", dict(id=po), BUYER)
    delegate(s, po)
    with pytest.raises(RuleError, match="substitute"):
        act(s, "approve", dict(id=po), APPROVER)
    clock[0] += timedelta(hours=2)
    act(s, "approve", dict(id=po), APPROVER)
    assert get(s, "orders", po)["status"] == "Pending approval"
    assert "approvalDelegate" not in get(s, "orders", po)


def test_delegate_approval_and_revoke_history(s, clock):
    policy(s)
    po = order(s)
    act(s, "submit", dict(id=po), BUYER)
    delegate(s, po)
    act(s, "revokeApprovalDelegation", dict(id=po, reason="Returned"), ADMIN)
    delegate(s, po)
    act(s, "approve", dict(id=po), dict(id="substitute", role="approver"))
    assert len(get(s, "orders", po)["approvalEvents"]) == 3
    assert get(s, "orders", po)["approvals"][0]["actor"] == "substitute"


def test_delegation_permissions_separation_and_role(s, clock):
    s["settings"]["separation"] = True
    policy(s)
    po = order(s)
    act(s, "submit", dict(id=po), BUYER)
    with pytest.raises(RuleError, match="role"):
        delegate(s, po, role="buyer")
    with pytest.raises(RuleError, match="creator"):
        delegate(s, po, target=BUYER["id"])
    with pytest.raises(RuleError, match="role"):
        act(s, "delegateApproval", dict(id=po, userId="substitute"), APPROVER)
    with pytest.raises(RuleError, match="active"):
        act(s, "delegateApproval", dict(id=po, userId="forged", approvalTarget={"role": "admin"}), ADMIN)


def test_existing_route_without_deadline_fields_is_compatible(s):
    p = policy(s)
    po = order(s)
    act(s, "submit", dict(id=po), BUYER)
    r = get(s, "orders", po)
    r["approvalRoute"].pop("approvalHours")
    r["approvalRoute"].pop("escalationRole")
    act(s, "approve", dict(id=po), APPROVER)
    assert get(s, "orders", po)["approvalRoute"]["policy"] == p["id"]
