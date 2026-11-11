from copy import deepcopy
import pytest
from test_domain import ADMIN, BUYER, APPROVER, FINANCE
from lubriflow.domain import act, get, automation_plan, RuleError

pytest_plugins = ["test_domain"]


def policy(s, name="Normal purchases", lower=0, upper=1000, stages="approver,finance", automatic=False, **extra):
    return act(s, "master", dict(collection="approvalPolicies", name=name, minAmount=lower,
        maxAmount=upper, approvalStages=stages, allowAutomatic=automatic, **extra), ADMIN)


def order(s, price=50, **extra):
    return act(s, "order", dict(supplier=s["suppliers"][0]["id"], tax=0,
        lines=[dict(item=s["items"][0]["id"], qty=1, price=price)], **extra), BUYER)["id"]


def test_configurable_stages_require_distinct_users(s):
    s["settings"]["separation"] = True
    policy(s, stages="approver,approver,finance")
    po = order(s)
    act(s, "submit", dict(id=po), BUYER)
    act(s, "approve", dict(id=po), APPROVER)
    with pytest.raises(RuleError, match="different user"):
        act(s, "approve", dict(id=po), APPROVER)
    act(s, "approve", dict(id=po), dict(id="second", role="approver"))
    with pytest.raises(RuleError, match="finance"):
        act(s, "approve", dict(id=po), APPROVER)
    act(s, "approve", dict(id=po), FINANCE)
    assert get(s, "orders", po)["status"] == "Approved"


def test_overlap_and_gap_fail_closed_atomically(s):
    policy(s, upper=100)
    before = deepcopy(s)
    with pytest.raises(RuleError, match="overlap"):
        policy(s, name="Overlap", lower=99, upper=200)
    assert s == before
    po = order(s, price=100)
    before = deepcopy(s)
    with pytest.raises(RuleError, match="covers"):
        act(s, "submit", dict(id=po), BUYER)
    assert s == before
    policy(s, name="Higher purchases", lower=100, upper=200, stages="finance")
    act(s, "submit", dict(id=po), BUYER)
    assert get(s, "orders", po)["approvalRoute"]["stages"] == ["finance"]


def test_pending_matrix_cannot_change(s):
    p = policy(s)
    po = order(s)
    act(s, "submit", dict(id=po), BUYER)
    before = deepcopy(s)
    with pytest.raises(RuleError, match="pending"):
        policy(s, id=p["id"], stages="approver")
    assert s == before


def test_automatic_approval_requires_explicit_policy_permission(s):
    s["settings"].update(mode="automatic", autoApprove=True, limit=100)
    p = policy(s, stages="approver")
    po = order(s)
    assert ("approve", {"id": po}) not in automation_plan(s)
    policy(s, id=p["id"], stages="approver", automatic=True)
    assert ("approve", {"id": po}) in automation_plan(s)
    for action, data in automation_plan(s):
        act(s, action, data, dict(id="automation", role="system"))
    assert get(s, "orders", po)["status"] == "Approved"


def test_foreign_order_limits_use_base_currency(s):
    s["settings"].update(mode="automatic", autoApprove=True, limit=100, financeThreshold=100)
    po = order(s, price=50, currency="EUR", rate=3)
    assert ("approve", {"id": po}) not in automation_plan(s)
    act(s, "submit", dict(id=po), BUYER)
    assert get(s, "orders", po)["approvalRoute"]["stages"] == ["approver", "finance"]
    s["settings"]["budgetMonthly"] = 140
    with pytest.raises(RuleError, match="budget"):
        act(s, "approve", dict(id=po), APPROVER)


def test_changed_legacy_threshold_requires_resubmission(s):
    po = order(s)
    act(s, "submit", dict(id=po), BUYER)
    s["settings"]["financeThreshold"] = 1
    with pytest.raises(RuleError, match="changed"):
        act(s, "approve", dict(id=po), APPROVER)


def test_disabling_all_policies_does_not_restore_automatic_fallback(s):
    s["settings"].update(mode="automatic", autoApprove=True, limit=100)
    p = policy(s, stages="approver", automatic=True)
    policy(s, id=p["id"], stages="approver", automatic=True, active=False)
    po = order(s)
    assert ("approve", {"id": po}) not in automation_plan(s)
    with pytest.raises(RuleError, match="covers"):
        act(s, "submit", dict(id=po), BUYER)


@pytest.mark.parametrize("stages", ["buyer", "supplier", "approver,finance", "admin"])
def test_invalid_automatic_routes_rejected(s, stages):
    with pytest.raises(RuleError):
        policy(s, stages=stages, automatic=True)
