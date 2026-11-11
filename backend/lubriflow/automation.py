"""Persistent LangGraph execution over the same commands used by manual entry."""

from typing import TypedDict
from langgraph.graph import StateGraph, START, END
from .db import Session
from .repository import tenant_lock, load, execute
from .domain import automation_plan, RuleError


class RunState(TypedDict, total=False):
    tenant_id: str
    run_id: str
    commands: list
    completed: int
    skipped: list


def build_graph(checkpointer):
    def plan(state: RunState):
        with Session.begin() as db:
            s = load(db, tenant_lock(db, state["tenant_id"]))
            return {"commands": automation_plan(s), "completed": 0, "skipped": []}

    def apply_commands(state: RunState):
        completed, skipped = 0, []
        for index, (action, data) in enumerate(state["commands"]):
            try:
                with Session.begin() as db:
                    tenant = tenant_lock(db, state["tenant_id"])
                    if tenant.settings.get("mode") != "automatic":
                        skipped.append("Automation disabled during this run.")
                        break
                    # A policy change after planning must revoke the corresponding authority.
                    policy = {
                        "requisition": "autoReorder",
                        "forecastRequisition": "autoReorder",
                        "convert": "autoPO",
                        "submit": "autoApprove",
                        "approve": "autoApprove",
                        "match": "autoMatch",
                    }[action]
                    if not tenant.settings.get(policy):
                        skipped.append(action + ": policy disabled")
                        continue
                    if action in {"requisition", "forecastRequisition"}:
                        method = tenant.settings.get('reorderMethod', 'threshold')
                        if (action == 'forecastRequisition') != (method == 'forecast'):
                            skipped.append(action + ': replenishment method changed')
                            continue
                    execute(
                        db,
                        state["tenant_id"],
                        {"id": "automation", "name": "Automation", "role": "system"},
                        action,
                        data,
                        state["run_id"] + "-" + str(index),
                    )
                    completed += 1
            except RuleError as exc:
                skipped.append(action + ": " + str(exc))
        return {"completed": completed, "skipped": skipped}

    builder = StateGraph(RunState)
    builder.add_node("plan", plan)
    builder.add_node("apply_commands", apply_commands)
    builder.add_edge(START, "plan")
    builder.add_edge("plan", "apply_commands")
    builder.add_edge("apply_commands", END)
    return builder.compile(checkpointer=checkpointer)
