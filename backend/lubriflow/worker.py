import argparse
import logging
import time
from datetime import timedelta
from sqlalchemy import select
from langgraph.checkpoint.postgres import PostgresSaver
from .config import settings
from .db import Session
from .models import AutomationRun, Tenant, now
from .automation import build_graph
from .message_delivery import messaging_once, poll_whatsapp

logger = logging.getLogger("lubriflow.worker")


def schedule():
    with Session.begin() as db:
        tenants = db.scalars(
            select(Tenant).where(Tenant.next_run <= now()).with_for_update(skip_locked=True)
        ).all()
        for tenant in tenants:
            tenant.next_run = now() + timedelta(minutes=5)
            if tenant.settings.get("mode") == "automatic":
                active = db.scalar(
                    select(AutomationRun).where(
                        AutomationRun.tenant_id == tenant.id, AutomationRun.status.in_(["Queued", "Running"])
                    )
                )
                if not active:
                    db.add(AutomationRun(tenant_id=tenant.id, requested_by="scheduler"))


def work_once(graph):
    # Keep the job lock until completion. A process crash rolls the claim back to Queued.
    with Session.begin() as db:
        run = db.scalar(
            select(AutomationRun)
            .where(AutomationRun.status == "Queued")
            .order_by(AutomationRun.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if not run:
            return False
        config = {"configurable": {"thread_id": run.tenant_id + ":" + run.id}}
        try:
            checkpoint = graph.get_state(config)
            input_state = None if checkpoint.values else {"tenant_id": run.tenant_id, "run_id": run.id}
            result = (
                checkpoint.values
                if checkpoint.values and not checkpoint.next
                else graph.invoke(input_state, config)
            )
            run.status = "Completed"
            run.result = {k: result.get(k) for k in ["completed", "skipped"]}
        except Exception:
            logger.exception("Automation run failed: %s", run.id)
            run.status, run.result = (
                "Failed",
                {"error": "Automation failed. Review server logs using run ID."},
            )
        run.updated_at = now()
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    uri = settings().database_url.replace("postgresql+psycopg://", "postgresql://")
    with PostgresSaver.from_conn_string(uri) as saver:
        saver.setup()
        graph = build_graph(saver)
        while True:
            schedule()
            from .approval_policy import escalation_once
            escalation_once()
            did_work = work_once(graph)
            from .finance_scheduler import finance_once
            finance_once()
            messaging_once()
            poll_whatsapp()
            if args.once:
                return
            if not did_work:
                time.sleep(5)


if __name__ == "__main__":
    main()
