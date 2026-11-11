from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace
import pytest

from test_domain import ADMIN, BUYER, order, issue, receipt
from test_api import mutation, setup_order
from lubriflow.domain import act, RuleError, today, get
from lubriflow.models import now
from lubriflow.messaging import queue, plan_messages, validate_send
from lubriflow.message_delivery import send, DeliveryError, configured

pytest_plugins = ["test_domain", "test_api"]


def consent(s, channel="email"):
    act(s, "supplierMessaging", dict(supplier=s["suppliers"][0]["id"], channel=channel,
        address="vendor@example.test" if channel == "email" else "+12025550123", consent=True, evidence="Test permission"), ADMIN)


def test_rfq_consent_duplicate_and_response_stop(s):
    rfq = act(s, "createRFQ", dict(supplier=s["suppliers"][0]["id"], due=today(), lines=[dict(item=s["items"][0]["id"], qty=5)]), BUYER)
    with pytest.raises(RuleError, match="authorised"):
        queue(s, "rfq", rfq["id"], "email", BUYER)
    consent(s)
    a = queue(s, "rfq", rfq["id"], "email", BUYER)
    assert queue(s, "rfq", rfq["id"], "email", BUYER)["id"] == a["id"]
    assert len(s["communications"]) == 1
    act(s, "quote", dict(supplier=rfq["supplier"], rfq=rfq["id"], valid=today(), lines=rfq["lines"]), BUYER)
    with pytest.raises(RuleError, match="closed"):
        validate_send(s, a)


def test_manual_and_automatic_messages_require_approved_po(s):
    consent(s)
    po = order(s)
    with pytest.raises(RuleError, match="approved"):
        queue(s, "po", po, "email", BUYER)
    issue(s, po)
    s["settings"].update(mode="automatic", supplierMessaging=dict(enabled=True, channel="email", intervalDays=3, maxReminders=2))
    plan_messages(s)
    plan_messages(s)
    assert len(s["communications"]) == 1
    validate_send(s, s["communications"][0])
    s["settings"]["supplierMessaging"]["enabled"] = False
    with pytest.raises(RuleError, match="disabled"):
        validate_send(s, s["communications"][0])


def test_reminder_cadence_receipt_and_revocation(s):
    consent(s)
    po = order(s)
    issue(s, po)
    get(s, "orders", po)["due"] = (now() - timedelta(days=1)).date().isoformat()
    initial = queue(s, "po", po, "email", BUYER)
    initial.update(status="Accepted", acceptedAt=(now() - timedelta(days=4)).isoformat())
    reminder = queue(s, "deliveryChase", po, "email", BUYER)
    with pytest.raises(RuleError):
        queue(s, "deliveryChase", po, "email", BUYER)
    validate_send(s, reminder)
    receipt(s, po)
    with pytest.raises(RuleError):
        validate_send(s, reminder)
    s["suppliers"][0]["messaging"]["email"]["consent"] = False
    with pytest.raises(RuleError):
        validate_send(s, initial)


def test_policy_permissions_and_contact_header_injection(s):
    before = deepcopy(s)
    with pytest.raises(RuleError):
        act(s, "supplierMessaging", dict(supplier=s["suppliers"][0]["id"]), BUYER)
    assert s == before
    with pytest.raises(RuleError):
        act(s, "supplierMessaging", dict(supplier=s["suppliers"][0]["id"], channel="email", address="a@test.com\nBcc:other@test.com", consent=True, evidence="test"), ADMIN)
    assert s == before


def cfg():
    return SimpleNamespace(messaging_live=True, smtp_host="smtp.example.test", smtp_from="buyer@example.test", smtp_port=465,
        smtp_username="test", smtp_password="secret", twilio_account_sid="AC" + "1" * 32, twilio_auth_token="secret",
        twilio_whatsapp_from="whatsapp:+12025550124", whatsapp_templates={"rfq": "HX" + "2" * 32})


def test_whatsapp_template_payload_and_ambiguous_timeout(monkeypatch):
    def post(url, **kwargs):
        assert url.startswith("https://api.twilio.com/")
        assert kwargs["data"]["ContentSid"] == "HX" + "2" * 32
        assert "Body" not in kwargs["data"]
        return SimpleNamespace(status_code=201, json=lambda: {"sid": "SM" + "3" * 32})
    import httpx
    monkeypatch.setattr(httpx, "post", post)
    m = dict(channel="whatsapp", recipient="+12025550123", purpose="rfq", company="Company", source="RFQ-1", due=today(), summary="5 items", replyTo="Reply")
    assert configured(m, cfg())
    assert send(m, cfg()) == "SM" + "3" * 32
    def timeout(*args, **kwargs):
        raise httpx.ReadTimeout("lost response")
    monkeypatch.setattr(httpx, "post", timeout)
    with pytest.raises(DeliveryError) as error:
        send(m, cfg())
    assert error.value.status == "Uncertain"


def test_smtp_transport_acceptance_and_data_timeout(monkeypatch):
    import smtplib
    class SMTP:
        fail = False
        def __init__(self, *args, **kwargs):
            assert kwargs["context"].check_hostname
        def login(self, *args):
            pass
        def send_message(self, message):
            assert message["To"] == "vendor@example.test"
            if self.fail:
                raise TimeoutError()
        def close(self):
            pass
    monkeypatch.setattr(smtplib, "SMTP_SSL", SMTP)
    m = dict(channel="email", recipient="vendor@example.test", subject="RFQ", body="Details", id="MSG-1", tenant="TENANT")
    assert "MSG-1" in send(m, cfg())
    SMTP.fail = True
    with pytest.raises(DeliveryError) as error:
        send(m, cfg())
    assert error.value.status == "Uncertain"


def test_postgres_worker_claim_retry_and_no_duplicate(client, monkeypatch):
    from lubriflow import message_delivery as worker
    from lubriflow.db import Session
    from lubriflow.models import Tenant
    from lubriflow.repository import load, save
    from sqlalchemy import select
    supplier, item, po = setup_order(client)
    assert mutation(client, "supplierMessaging", dict(supplier=supplier, channel="email", address="vendor@example.test", consent=True, evidence="Fixture consent")).status_code == 200
    for action in ["submit", "approve"]:
        assert mutation(client, action, dict(id=po)).status_code == 200
    preview = client.post("/api/supplier-message-preview", json=dict(source=po, purpose="po", channel="email"))
    assert preview.status_code == 200 and "unit price" in preview.json()["body"]
    assert client.get("/api/workspace").json()["state"]["communications"] == []
    result = mutation(client, "queueSupplierMessage", dict(source=po, purpose="po", channel="email"))
    assert result.status_code == 200, result.text
    message_id = result.json()["result"]["id"]
    from lubriflow.models import User
    actor_id = result.json()["actor"]["id"]
    with Session() as db:
        tenant_id = db.get(User, actor_id).tenant_id
    config = cfg()
    config.messaging_tenant_ids = [tenant_id]
    monkeypatch.setattr(worker, "settings", lambda: config)
    calls = []
    def transport(message, config):
        calls.append(message["id"])
        if len(calls) == 1:
            raise DeliveryError("Retry", "Connection refused before sending")
        if len(calls) == 2:
            worker.messaging_once()  # Another worker must observe the committed Sending claim.
        return "provider-test-id"
    monkeypatch.setattr(worker, "send", transport)
    worker.messaging_once()
    worker.messaging_once()
    assert len(calls) == 1
    with Session.begin() as db:
        tenant = db.scalar(select(Tenant).where(Tenant.id == tenant_id).with_for_update())
        s = load(db, tenant)
        assert s["communications"][0]["status"] == "Retry"
        s["communications"][0]["nextAttemptAt"] = ""
        save(db, tenant, s)
    worker.messaging_once()
    worker.messaging_once()
    assert len(calls) == 2
    assert calls == [message_id, message_id]
    state = client.get("/api/workspace").json()["state"]
    assert state["communications"][0]["status"] == "Accepted"
    assert state["orders"][0]["status"] == "Issued"
    # A crashed worker's committed claim cannot be replayed as a fresh send.
    with Session.begin() as db:
        tenant = db.scalar(select(Tenant).where(Tenant.id == tenant_id).with_for_update())
        s = load(db, tenant)
        s["communications"][0].update(status="Sending", attemptedAt=(now() - timedelta(minutes=11)).isoformat())
        save(db, tenant, s)
    worker.messaging_once()
    worker.messaging_once()
    assert len(calls) == 2
    assert client.get("/api/workspace").json()["state"]["communications"][0]["status"] == "Uncertain"


def test_whatsapp_delivery_poll_and_tenant_isolation(client, monkeypatch):
    from lubriflow import message_delivery as worker
    from lubriflow.db import Session
    from lubriflow.models import Tenant, User
    from lubriflow.repository import load, save
    import httpx
    supplier, item, po = setup_order(client)
    for action in ["submit", "approve"]:
        mutation(client, action, dict(id=po))
    mutation(client, "supplierMessaging", dict(supplier=supplier, channel="whatsapp", address="+12025550123", consent=True, evidence="test"))
    response = mutation(client, "queueSupplierMessage", dict(source=po, purpose="po", channel="whatsapp"))
    assert response.status_code == 200
    with Session.begin() as db:
        tenant_id = db.get(User, response.json()["actor"]["id"]).tenant_id
        tenant = db.get(Tenant, tenant_id)
        s = load(db, tenant)
        s["communications"][0].update(status="Accepted", providerId="SM" + "3" * 32)
        save(db, tenant, s)
    config = cfg()
    config.messaging_tenant_ids = []
    monkeypatch.setattr(worker, "settings", lambda: config)
    calls = []
    def status(url, **kwargs):
        calls.append(url)
        return httpx.Response(200, json={"status": "delivered"}, request=httpx.Request("GET", url))
    monkeypatch.setattr(httpx, "get", status)
    worker.poll_whatsapp()
    assert not calls
    config.messaging_tenant_ids = [tenant_id]
    worker.poll_whatsapp()
    assert len(calls) == 1
    assert client.get("/api/workspace").json()["state"]["communications"][0]["status"] == "Delivered"
