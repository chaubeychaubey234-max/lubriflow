"""Run only explicitly authorised automatic schedules; failures hold for finance review."""

import logging
from uuid import uuid4
from sqlalchemy import select
from .db import Session
from .models import Tenant, User, now, RECORDS
from .repository import load, save
from .domain import act, RuleError, today
from .accounting import add_months

logger = logging.getLogger(__name__)


def due(schedule, through):
    dates = [add_months(schedule["start"], i) for i in range(schedule["months"])]
    if schedule["kind"] == "accrual":
        dates.append(schedule["reverseDate"])
    return any(
        day <= through and not any(r["period"] == i for r in schedule["runs"]) for i, day in enumerate(dates)
    )


def finance_once():
    with Session() as db:
        schedules=RECORDS["financeSchedules"]
        ids=list(db.scalars(select(Tenant.id).join(schedules,schedules.tenant_id==Tenant.id).where(schedules.status=="Active",schedules.payload["automatic"].as_boolean().is_(True)).distinct()))
    for tid in ids:
        try:
            with Session.begin() as db:
                tenant = db.scalar(select(Tenant).where(Tenant.id == tid).with_for_update(skip_locked=True))
                if not tenant:
                    continue
                s = load(db, tenant)
                changed = False
                for sch in list(s["financeSchedules"]):
                    if sch["status"] != "Active" or not sch.get("automatic") or not due(sch, today()):
                        continue
                    owner = db.get(User, sch.get("authorisedBy", ""))
                    try:
                        if (
                            not owner
                            or not owner.active
                            or owner.tenant_id != tid
                            or owner.role not in {"admin", "finance"}
                        ):
                            raise RuleError(
                                "Schedule authorisation is no longer valid. Finance must review and resume."
                            )
                        act(
                            s,
                            "runFinanceSchedules",
                            {"id": sch["id"], "through": today()},
                            dict(id="finance-scheduler", name="Finance scheduler", role="finance"),
                        )
                    except RuleError as exc:
                        # act rolls back all effects of the failed run in memory.
                        target = next(x for x in s["financeSchedules"] if x["id"] == sch["id"])
                        target.update(status="Attention", lastError=str(exc))
                        s["audit"].insert(
                            0,
                            dict(
                                id="EV-" + str(uuid4()),
                                at=now().isoformat(),
                                actor="Finance scheduler",
                                actorId="finance-scheduler",
                                action="Schedule held",
                                detail=sch["id"] + ": " + str(exc),
                            ),
                        )
                    changed = True
                if changed:
                    save(db, tenant, s)
        except Exception:
            logger.exception("Finance schedule tenant failed: %s", tid)
