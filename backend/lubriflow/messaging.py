"""Supplier messages use a durable outbox and revalidate business state before sending."""
from datetime import timedelta
import hashlib
import re

from .domain import (require, get, text, lines, identifier, today, valid_date,
                     totals, received, effective, dec, qualified)
from .models import now

PURPOSES = {"rfq", "po", "rfqReminder", "ackReminder", "deliveryChase"}
DEFAULT_POLICY = dict(enabled=False, channel="email", intervalDays=3, maxReminders=3)


def policy(s):
    return {**DEFAULT_POLICY, **s["settings"].get("supplierMessaging", {})}


def recipient(supplier, channel):
    contact = supplier.get("messaging", {}).get(channel, {})
    require(contact.get("consent") is True, "Supplier has not authorised this messaging channel.")
    address = contact.get("address", "")
    pattern = r"[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+" if channel == "email" else r"\+[1-9][0-9]{7,14}"
    require(re.fullmatch(pattern, address), "Invalid supplier messaging address.")
    return address


def source_record(s, purpose, key):
    require(purpose in PURPOSES, "Unknown supplier message purpose.")
    return get(s, "rfqs" if purpose in {"rfq", "rfqReminder"} else "orders", key)


def eligible(s, purpose, source):
    if purpose in {"rfq", "rfqReminder"}:
        require(source["status"] == "Open", "RFQ is closed or has a supplier response.")
        if purpose == "rfq":
            require(source["due"] >= today(), "RFQ is past its response deadline.")
    elif purpose == "po":
        require(source["status"] in {"Approved", "Issued", "Acknowledged", "Part received"}, "PO must be approved and active before sending.")
    elif purpose == "ackReminder":
        require(source["status"] == "Issued", "PO no longer needs an acknowledgement reminder.")
    else:
        require(source["status"] in {"Issued", "Acknowledged", "Part received"} and source["due"] < today(), "PO delivery is not overdue.")
        require(any(dec(received(s, source["id"], line["item"], True)) < dec(effective(line)) for line in source["lines"]), "No outstanding delivery quantity.")


def fingerprint(source):
    # A revision changes when a PO is amended. RFQs are immutable after creation.
    return str(source.get("revision", 1))


def render(s, purpose, source):
    headings = dict(rfq="Request for quotation", po="Purchase order", rfqReminder="Quotation reminder",
                    ackReminder="Purchase order acknowledgement requested", deliveryChase="Overdue delivery update requested")
    supplier = get(s, "suppliers", source["supplier"])
    heading = headings[purpose]
    summary = []
    for line in source["lines"]:
        item = get(s, "items", line["item"])
        detail = f'{item["name"]}: {line["qty"]} {item["unit"]}'
        if purpose == "po":
            detail += f'; unit price {line["price"]}; discount {line.get("discount", 0)}%; tax {line.get("taxRate", source.get("tax", 0))}%'
        if purpose == "deliveryChase":
            detail += f'; outstanding {max(0, effective(line) - received(s, source["id"], line["item"], True))}'
        summary.append(detail)
    body = f'{heading}: {source["id"]}\nFrom: {s["settings"]["company"]}\nSupplier: {supplier["name"]}\nDue: {source["due"]}\n' + "\n".join(summary)
    if purpose == "po":
        body += f'\nCurrency: {s["settings"]["currency"]}\nTotal: {totals(source)["total"]}\nDelivery address: {source.get("deliveryAddress", "")}\nPayment terms: {source.get("paymentTerms", "")}\nPlease acknowledge this order.'
    else:
        body += "\nPlease reply with your quotation or delivery update, referencing the document number."
    body += "\n" + source.get("note", "")
    require(len(body) <= 20000, "Message is too long. Reduce the document notes or line count.")
    return heading + " " + source["id"], body


def queue(s, purpose, source_id, channel, actor, automatic=False):
    require(channel in {"email", "whatsapp"}, "Choose email or WhatsApp.")
    source = source_record(s, purpose, source_id)
    eligible(s, purpose, source)
    supplier = get(s, "suppliers", source["supplier"])
    require(qualified(supplier), "Supplier must have current qualification.")
    address = recipient(supplier, channel)
    initial = purpose in {"rfq", "po"}
    previous = [x for x in s["communications"] if x["source"] == source_id and x["purpose"] == purpose and x["channel"] == channel and x["sourceRevision"] == fingerprint(source)]
    if initial and previous:
        if not automatic and previous[0]["status"] in {"Cancelled", "Failed"}:
            # Explicit manual requeue only after a definitive non-delivery; never Uncertain.
            old = previous[0]
            old.update(recipient=address, status="Queued", automatic=False, attempts=0, nextAttemptAt="", error="")
            old["subject"], old["body"] = render(s, purpose, source)
            old["events"].append(dict(at=now().isoformat(), status="Queued", detail="Explicitly requeued by " + actor["id"]))
            return old
        return previous[0]
    if not initial:
        p = policy(s)
        require(len(previous) < p["maxReminders"], "Reminder limit reached.")
        related = [x for x in s["communications"] if x["source"] == source_id and x["channel"] == channel and x["sourceRevision"] == fingerprint(source)]
        initial_kind = "rfq" if purpose == "rfqReminder" else "po"
        require(any(x["purpose"] == initial_kind and x["status"] in {"Accepted", "Sent", "Delivered", "Read"} for x in related), "Send the initial document before reminders.")
        require(not any(x["status"] in {"Queued", "Sending", "Retry", "Uncertain"} for x in related), "A related message is still pending or uncertain.")
        last = max(x.get("acceptedAt", x["createdAt"]) for x in related)
        from datetime import datetime
        require(now() >= datetime.fromisoformat(last) + timedelta(days=p["intervalDays"]), "Reminder interval has not elapsed.")
    subject, body = render(s, purpose, source)
    key = f'{source_id}:{fingerprint(source)}:{purpose}:{channel}:{len(previous)}'
    r = dict(id="MSG-" + hashlib.sha256(key.encode()).hexdigest()[:28], source=source_id,
             sourceRevision=fingerprint(source), supplier=supplier["id"], purpose=purpose, channel=channel,
             recipient=address, subject=subject, body=body, status="Queued", automatic=automatic,
             createdAt=now().isoformat(), date=today(), attempts=0, events=[], createdBy=actor["id"])
    s["communications"].insert(0, r)
    return r


def message_action(s, action, d, actor):
    if action == "messagingPolicy":
        require(actor["role"] == "admin", "Administrator access required.")
        require(isinstance(d.get("enabled"), bool), "Choose enabled or disabled.")
        require(d.get("channel") in {"email", "whatsapp"}, "Choose email or WhatsApp.")
        days, maximum = int(d.get("intervalDays", 3)), int(d.get("maxReminders", 3))
        require(1 <= days <= 30 and 0 <= maximum <= 10, "Use 1–30 days and 0–10 reminders.")
        s["settings"]["supplierMessaging"] = dict(enabled=d["enabled"], channel=d["channel"], intervalDays=days, maxReminders=maximum)
        return dict(id="MESSAGING-POLICY")
    if action == "supplierMessaging":
        require(actor["role"] == "admin", "Administrator access required.")
        supplier = get(s, "suppliers", d["supplier"])
        require(d.get("channel") in {"email", "whatsapp"} and isinstance(d.get("consent"), bool), "Choose a channel and consent status.")
        contact = dict(address=text(d.get("address", "")), consent=d["consent"], evidence=text(d.get("evidence"), "Consent or revocation reference", True), updatedBy=actor["id"], updatedAt=now().isoformat())
        supplier.setdefault("messaging", {})[d["channel"]] = contact
        if d["consent"]:
            recipient(supplier, d["channel"])
        return supplier
    if action == "createRFQ":
        supplier = get(s, "suppliers", d["supplier"])
        require(qualified(supplier), "Choose a currently qualified supplier.")
        due = valid_date(d.get("due"))
        require(due >= today(), "RFQ deadline cannot be in the past.")
        r = dict(id=identifier(s, "REQQUOTE"), supplier=supplier["id"], due=due, date=today(), lines=lines(s, d.get("lines")), status="Open", note=text(d.get("note", "")))
        s["rfqs"].insert(0, r)
        return r
    if action == "closeRFQ":
        r = get(s, "rfqs", d["id"])
        require(r["status"] == "Open", "RFQ already closed.")
        r.update(status="Closed", reason=text(d.get("reason"), "Closure reason", True))
        return r
    if action == "cancelSupplierMessage":
        r = get(s, "communications", d["id"])
        require(r["status"] in {"Queued", "Retry"}, "Only unsent messages can be cancelled.")
        r.update(status="Cancelled", error=text(d.get("reason"), "Cancellation reason", True))
        return r
    return queue(s, d.get("purpose"), d.get("source"), d.get("channel"), actor)


def validate_send(s, message):
    if message["automatic"]:
        require(s["settings"]["mode"] == "automatic" and policy(s)["enabled"], "Automatic messaging is disabled.")
        require(policy(s)["channel"] == message["channel"], "Automatic channel changed.")
    source = source_record(s, message["purpose"], message["source"])
    eligible(s, message["purpose"], source)
    require(fingerprint(source) == message["sourceRevision"], "Document was amended after queueing.")
    supplier = get(s, "suppliers", message["supplier"])
    require(qualified(supplier) and recipient(supplier, message["channel"]) == message["recipient"], "Supplier qualification or contact changed.")
    require(render(s, message["purpose"], source) == (message["subject"], message["body"]), "Document details changed; cancel this message and review the current document.")


def plan_messages(s):
    from .domain import RuleError
    if s["settings"]["mode"] != "automatic" or not policy(s)["enabled"]:
        return
    p = policy(s)
    for purpose, records in [("rfq", s["rfqs"]), ("po", s["orders"]), ("rfqReminder", s["rfqs"]), ("ackReminder", s["orders"]), ("deliveryChase", s["orders"])]:
        for record in records:
            try:
                queue(s, purpose, record["id"], p["channel"], dict(id="automation"), automatic=True)
            except RuleError:
                continue


