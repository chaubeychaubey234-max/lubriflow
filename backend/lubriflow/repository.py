from copy import deepcopy
from datetime import datetime
import hashlib
import json
from sqlalchemy import select, delete
from .models import Tenant, RECORDS, DocumentLine, AuditEvent, Mutation
from .domain import empty, act, require


def tenant_lock(db, tenant_id):
    return db.scalar(select(Tenant).where(Tenant.id == tenant_id).with_for_update())


def load(db, tenant):
    s = empty(tenant.name)
    s["settings"].update(deepcopy(tenant.settings))
    s["series"] = deepcopy(tenant.series)
    line_map = {}
    for row in db.scalars(
        select(DocumentLine).where(DocumentLine.tenant_id == tenant.id).order_by(DocumentLine.position)
    ):
        value = dict(
            row.payload,
            item=row.item_id,
            qty=float(row.quantity),
            price=float(row.unit_price),
            discount=float(row.discount),
        )
        if row.tax_rate is not None:
            value["taxRate"] = float(row.tax_rate)
        line_map.setdefault((row.collection, row.record_id), []).append(value)
    for name, model in RECORDS.items():
        s[name] = []
        for row in db.scalars(select(model).where(model.tenant_id == tenant.id).order_by(model.position)):
            value = deepcopy(row.payload)
            if value.pop("_hasLines", False):
                value["lines"] = line_map.get((name, row.id), [])
            s[name].append(value)
    s["audit"] = [
        deepcopy(r.payload)
        for r in db.scalars(
            select(AuditEvent).where(AuditEvent.tenant_id == tenant.id).order_by(AuditEvent.at.desc())
        )
    ]
    from .inventory import ensure_positions
    for item in s["items"]:
        ensure_positions(s, item)
    return s


def save(db, tenant, state):
    tenant.name = state["settings"]["company"]
    tenant.settings, tenant.series = deepcopy(state["settings"]), deepcopy(state["series"])
    tenant.revision += 1
    # Remove references to items deleted by a validated restore before deleting item rows.
    item_ids = [item["id"] for item in state["items"]]
    db.execute(
        delete(DocumentLine).where(DocumentLine.tenant_id == tenant.id, DocumentLine.item_id.not_in(item_ids))
    )
    existing_lines = {}
    for line in db.scalars(
        select(DocumentLine).where(DocumentLine.tenant_id == tenant.id).order_by(DocumentLine.position)
    ):
        value = dict(
            line.payload,
            item=line.item_id,
            qty=float(line.quantity),
            price=float(line.unit_price),
            discount=float(line.discount),
        )
        if line.tax_rate is not None:
            value["taxRate"] = float(line.tax_rate)
        existing_lines.setdefault((line.collection, line.record_id), []).append(value)
    # Persist item masters before any new normalized lines reference them. Restore
    # and bulk state saves can introduce BOMs and their items in one transaction.
    # Keep unchanged records and line rows untouched under the tenant lock.
    for collection, model in sorted(RECORDS.items(), key=lambda entry: entry[0] != 'items'):
        old = {r.id: r for r in db.scalars(select(model).where(model.tenant_id == tenant.id))}
        for position, record in enumerate(state[collection]):
            payload = deepcopy(record)
            item_lines = payload.pop("lines", None)
            if item_lines is not None:
                payload["_hasLines"] = True
            row = old.pop(record["id"], None)
            changed = row is None or row.payload != payload
            if row is None:
                row = model(tenant_id=tenant.id, id=record["id"])
                db.add(row)
            row.position = position
            row.status, row.supplier, row.date = (
                record.get("status"),
                record.get("supplier"),
                record.get("date"),
            )
            row.payload = payload
            # Line changes may occur without a header change, e.g. preclosure.
            if item_lines is not None and item_lines != existing_lines.get((collection, row.id), []):
                db.execute(
                    delete(DocumentLine).where(
                        DocumentLine.tenant_id == tenant.id,
                        DocumentLine.collection == collection,
                        DocumentLine.record_id == row.id,
                    )
                )
                for n, line in enumerate(item_lines):
                    db.add(
                        DocumentLine(
                            tenant_id=tenant.id,
                            collection=collection,
                            record_id=row.id,
                            position=n,
                            item_id=line["item"],
                            quantity=line["qty"],
                            unit_price=line["price"],
                            discount=line.get("discount", 0),
                            tax_rate=line.get("taxRate"),
                            payload={
                                k: v
                                for k, v in line.items()
                                if k not in {"item", "qty", "price", "discount", "taxRate"}
                            },
                        )
                    )
            elif item_lines is None and changed:
                db.execute(
                    delete(DocumentLine).where(
                        DocumentLine.tenant_id == tenant.id,
                        DocumentLine.collection == collection,
                        DocumentLine.record_id == row.id,
                    )
                )
        for row in old.values():
            db.execute(
                delete(DocumentLine).where(
                    DocumentLine.tenant_id == tenant.id,
                    DocumentLine.collection == collection,
                    DocumentLine.record_id == row.id,
                )
            )
            db.delete(row)
        db.flush()
    existing = set(db.scalars(select(AuditEvent.id).where(AuditEvent.tenant_id == tenant.id)))
    for event in state["audit"]:
        if event["id"] not in existing:
            db.add(
                AuditEvent(
                    tenant_id=tenant.id,
                    id=event["id"],
                    actor_id=event["actorId"],
                    action=event["action"],
                    at=datetime.fromisoformat(event["at"]),
                    payload=deepcopy(event),
                )
            )
    db.flush()


def execute(db, tenant_id, actor, action, data, request_id, revision=None):
    tenant = tenant_lock(db, tenant_id)
    fingerprint = hashlib.sha256(json.dumps([action, data], sort_keys=True).encode()).hexdigest()
    previous = db.get(Mutation, (tenant_id, request_id))
    if previous:
        require(
            previous.actor_id == actor["id"] and previous.request_hash == fingerprint,
            "Idempotency key was reused for a different command.",
        )
        return previous.result, tenant.revision, True
    require(revision is None or revision == tenant.revision, "Workspace changed. Refresh before saving.")
    s = load(db, tenant)
    if action == "delegateApproval":
        from .models import User
        require(actor["role"] == "admin", "Only administrators can assign approval substitutes.")
        target = db.scalar(select(User).where(User.id == data.get("userId"), User.tenant_id == tenant_id, User.active.is_(True)))
        require(target is not None, "Choose an active user in this company.")
        actor = dict(actor, approvalTarget=dict(id=target.id, name=target.name, role=target.role, active=target.active))
    result = act(s, action, data, actor)
    if action in {"order", "editOrder", "invoice", "editInvoice", "requisition", "quote", "supplier", "item"}:
        draft_key = actor["id"] + ":" + action + ":" + data.get("id", "")
        s["drafts"] = [draft for draft in s["drafts"] if draft["key"] != draft_key]
    save(db, tenant, s)
    db.add(
        Mutation(
            tenant_id=tenant_id,
            request_id=request_id,
            actor_id=actor["id"],
            request_hash=fingerprint,
            result=result,
        )
    )
    db.flush()
    return result, tenant.revision, False


def replay_command(db, tenant_id, actor_id, scope, body):
    fingerprint = hashlib.sha256(
        json.dumps([scope, body.action, body.data], sort_keys=True).encode()
    ).hexdigest()
    previous = db.get(Mutation, (tenant_id, body.requestId))
    if previous:
        require(
            previous.actor_id == actor_id and previous.request_hash == fingerprint,
            "Idempotency key was reused for a different command.",
        )
        return previous.result, fingerprint
    return None, fingerprint


def remember_command(db, tenant_id, actor_id, body, fingerprint, result):
    db.add(
        Mutation(
            tenant_id=tenant_id,
            request_id=body.requestId,
            actor_id=actor_id,
            request_hash=fingerprint,
            result=result,
        )
    )
