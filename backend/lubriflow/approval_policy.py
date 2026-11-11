"""Company purchase approval ranges, expressed in company base currency."""
from .domain import amount, dec, money, require, totals, RuleError
from datetime import datetime, timedelta, timezone


def base_value(order):
    return money(dec(totals(order)["total"]) * dec(order.get("rate", 1)))


def configure(s, record, data):
    require(not any(o["status"] == "Pending approval" for o in s["orders"]),
            "Finish or reject pending purchase approvals before changing the approval matrix.")
    lower = amount(data.get("minAmount", 0))
    upper = amount(data.get("maxAmount", 0), positive=True)
    require(upper > lower, "Upper approval limit must exceed the lower limit.")
    sequence = str(data.get("approvalStages", "approver")).split(",")
    stages = [r.strip() for r in sequence]
    require(1 <= len(stages) <= 5 and all(r in {"approver", "finance", "admin"} for r in stages),
            "Use one to five stages: approver, finance or admin, separated by commas.")
    automatic = data.get("allowAutomatic", False)
    hours = amount(data.get("approvalHours") or 0)
    require(hours == int(hours) and hours <= 8760, "Approval deadline must be whole hours from 0 to 8760; zero disables escalation.")
    escalation_role = data.get("escalationRole") or "admin"
    require(escalation_role in {"admin", "finance"}, "Escalations go to admin or finance.")
    require(isinstance(automatic, bool), "Automatic approval permission must be true or false.")
    require(not automatic or stages == ["approver"],
            "Automatic approval is only available for a single approver stage.")
    if record["active"]:
        for other in s["approvalPolicies"]:
            if other["id"] == record["id"] or not other.get("active") or not other.get("policyVersion"):
                continue
            require(upper <= other["minAmount"] or lower >= other["maxAmount"],
                    "Active approval ranges cannot overlap. Upper limits are exclusive.")
    record.update(minAmount=lower, maxAmount=upper, approvalStages=",".join(stages),
                  allowAutomatic=automatic, approvalHours=int(hours), escalationRole=escalation_role,
                  policyVersion=record.get("policyVersion", 0) + 1)


def route(s, order):
    policies = [p for p in s["approvalPolicies"] if p.get("active") and p.get("policyVersion")]
    value = base_value(order)
    if any(p.get("policyVersion") for p in s["approvalPolicies"]):
        matches = [p for p in policies if p["minAmount"] <= value < p["maxAmount"]]
        require(len(matches) == 1, "No unique approval policy covers this order's base-currency total.")
        p = matches[0]
        return dict(policy=p["id"], version=p["policyVersion"], stages=p["approvalStages"].split(","),
                    allowAutomatic=p["allowAutomatic"], approvalHours=p.get("approvalHours", 0),
                    escalationRole=p.get("escalationRole", "admin"))
    return dict(policy="legacy-threshold", version=1,
                stages=["approver", "finance"] if value >= s["settings"]["financeThreshold"] else ["approver"],
                allowAutomatic=True)


def automatic_allowed(s, order):
    try:
        policy = route(s, order)
    except RuleError:
        return False
    value = base_value(order)
    return (s["settings"]["mode"] == "automatic" and s["settings"]["autoApprove"]
            and policy["allowAutomatic"] and policy["stages"] == ["approver"]
            and value <= s["settings"]["limit"] and value < s["settings"]["financeThreshold"])


def utc_now():
    return datetime.now(timezone.utc)


def same_route(saved, current):
    def normalized(value):
        return dict(value, approvalHours=value.get("approvalHours", 0), escalationRole=value.get("escalationRole", "admin"))
    return normalized(saved) == normalized(current)


def begin_stage(order):
    now = utc_now()
    order["approvalStageStartedAt"] = now.isoformat()
    hours = order.get("approvalRoute", {}).get("approvalHours", 0)
    order["approvalDueAt"] = (now + timedelta(hours=hours)).isoformat() if hours else None
    order.pop("approvalEscalation", None)
    order.pop("approvalDelegate", None)


def current_delegate(order):
    delegation = order.get("approvalDelegate")
    if (delegation and delegation["stage"] == len(order["approvals"])
            and delegation["revision"] == order["revision"]
            and datetime.fromisoformat(delegation["expiresAt"]) > utc_now()):
        return delegation
    return None


def approval_action(s, action, data, actor):
    from .domain import get, text
    order = get(s, "orders", data["id"])
    require(order["status"] == "Pending approval", "Order must be awaiting approval.")
    policy = route(s, order)
    require(same_route(order.get("approvalRoute", policy), policy), "Approval policy changed. Reject and resubmit.")
    stage = len(order["approvals"])
    require(stage < len(policy["stages"]), "No pending approval stage.")
    if action == "escalateApproval":
        due = order.get("approvalDueAt")
        require(due and datetime.fromisoformat(due) <= utc_now(), "Approval deadline has not passed.")
        require(not order.get("approvalEscalation"), "This stage is already escalated.")
        event = dict(kind="Escalated", stage=stage, revision=order["revision"], at=utc_now().isoformat(),
                     dueAt=due, role=policy.get("escalationRole", "admin"))
        order["approvalEscalation"] = event
    elif action == "delegateApproval":
        require(actor["role"] == "admin", "Only administrators can assign approval substitutes.")
        target = actor.get("approvalTarget")
        require(target and target["id"] == data.get("userId") and target["active"],
                "Choose an active user in this company.")
        require(target["role"] == policy["stages"][stage], "Substitute must hold the required stage role.")
        if s["settings"]["separation"]:
            require(target["id"] != order["createdBy"] and not any(a["actor"] == target["id"] for a in order["approvals"]),
                    "Substitute cannot be the creator or an earlier approver.")
        hours = amount(data.get("validHours", 24), positive=True)
        require(hours == int(hours) and hours <= 720, "Delegation lasts 1 to 720 whole hours.")
        event = dict(kind="Delegated", stage=stage, revision=order["revision"], at=utc_now().isoformat(),
                     userId=target["id"], name=target["name"], role=target["role"], delegatedBy=actor["id"],
                     expiresAt=(utc_now()+timedelta(hours=hours)).isoformat(), reason=text(data.get("reason"), "Reason", True))
        order["approvalDelegate"] = event
    else:
        require(action == "revokeApprovalDelegation" and actor["role"] == "admin", "Only administrators can revoke a delegation.")
        require(order.get("approvalDelegate"), "No delegation to revoke.")
        event = dict(kind="Delegation revoked", stage=stage, revision=order["revision"], at=utc_now().isoformat(),
                     userId=order["approvalDelegate"]["userId"], actor=actor["id"], reason=text(data.get("reason"), "Reason", True))
        order.pop("approvalDelegate")
    order.setdefault("approvalEvents", []).append(event)
    return order


def escalation_once():
    """Escalate overdue stages into an audited in-app queue; never approve or send messages."""
    from sqlalchemy import select
    from .db import Session
    from .models import RECORDS
    from .repository import tenant_lock, load, save
    from .domain import act
    import logging
    with Session() as db:
        model = RECORDS["orders"]
        tenants = list(db.scalars(select(model.tenant_id).where(model.status == "Pending approval").distinct()))
    for tenant_id in tenants:
        try:
            with Session.begin() as db:
                tenant = tenant_lock(db, tenant_id)
                state = load(db, tenant)
                changed = False
                for order in state["orders"]:
                    due = order.get("approvalDueAt")
                    if order["status"] != "Pending approval" or not due or order.get("approvalEscalation"):
                        continue
                    if datetime.fromisoformat(due) > utc_now():
                        continue
                    try:
                        act(state, "escalateApproval", dict(id=order["id"]), dict(id="approval-scheduler", role="system"))
                        changed = True
                    except RuleError:
                        continue
                if changed:
                    save(db, tenant, state)
        except Exception:
            logging.getLogger(__name__).exception("Approval escalation failed for tenant %s", tenant_id)
