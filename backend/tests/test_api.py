"""Run only against the dedicated PostgreSQL test database specified in DATABASE_URL."""

import os
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor
import pytest

pytestmark = pytest.mark.skipif(
    "lubriflow_test" not in os.getenv("DATABASE_URL", ""), reason="Dedicated PostgreSQL test URL required"
)


@pytest.fixture
def client():
    if "lubriflow_test" not in os.getenv("DATABASE_URL", ""):
        pytest.skip("Dedicated PostgreSQL test URL required")
    from fastapi.testclient import TestClient
    from lubriflow.api import app
    from lubriflow.db import Session
    from lubriflow.models import Tenant, User
    from lubriflow.repository import save
    from lubriflow.domain import empty
    from lubriflow.auth import hash_password

    email = str(uuid4()) + "@example.test"
    with Session.begin() as db:
        tenant = Tenant(name="Integration test", settings={}, series={})
        db.add(tenant)
        db.flush()
        state = empty(tenant.name)
        state["settings"]["separation"] = False
        save(db, tenant, state)
        db.add(
            User(
                tenant_id=tenant.id,
                name="Test administrator",
                email=email,
                role="admin",
                password_hash=hash_password("test-password-at-least-12"),
            )
        )
    with TestClient(app) as c:
        c.headers.update({"Origin": "http://localhost:3000", "X-Lubriflow-Request": "1"})
        response = c.post("/api/auth/login", json={"email": email, "password": "test-password-at-least-12"})
        assert response.status_code == 200, response.text
        yield c


def mutation(client, action, data, revision=None, request_id=None):
    if revision is None:
        revision = client.get("/api/workspace").json()["revision"]
    return client.post(
        "/api/workspace",
        json=dict(action=action, data=data, revision=revision, requestId=request_id or str(uuid4())),
    )


def setup_order(client):
    supplier = mutation(client, "supplier", dict(name="Test vendor")).json()["result"]["id"]
    assert mutation(client, "approveSupplier", dict(id=supplier, approved=True)).status_code == 200
    item = mutation(
        client, "item", dict(name="Test item", unit="L", supplier=supplier, price=5, reorder=0, target=10)
    ).json()["result"]["id"]
    po = mutation(
        client, "order", dict(supplier=supplier, lines=[dict(item=item, qty=10, price=5)], tax=5)
    ).json()["result"]["id"]
    return supplier, item, po


def test_anonymous_and_csrf_boundaries(client):
    cookie = client.cookies.get("lubriflow_session")
    client.cookies.clear()
    for path in ["/api/workspace", "/api/finance", "/api/users", "/api/portal", "/api/automation"]:
        assert client.get(path).status_code == 401
    client.cookies.set("lubriflow_session", cookie)
    assert (
        client.post("/api/workspace", json={}, headers={"Origin": "https://untrusted.example"}).status_code
        == 403
    )


def test_idempotency_and_concurrent_revision(client):
    rev = client.get("/api/workspace").json()["revision"]
    key = str(uuid4())
    first = mutation(client, "supplier", {"name": "One"}, rev, key)
    assert first.status_code == 200, first.text
    repeat = mutation(client, "supplier", {"name": "One"}, rev, key)
    assert repeat.status_code == 200 and repeat.json()["duplicate"]
    assert mutation(client, "supplier", {"name": "Different"}, rev, key).status_code == 400
    assert mutation(client, "supplier", {"name": "Stale"}, rev).status_code == 409
    rev = client.get("/api/workspace").json()["revision"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(
            pool.map(lambda n: mutation(client, "supplier", {"name": f"Concurrent {n}"}, rev), range(2))
        )
    assert sorted(r.status_code for r in responses) == [200, 409]


def test_purchase_lifecycle_persists_real_relational_rows(client):
    supplier, item, po = setup_order(client)
    for action in ["submit", "approve", "dispatch"]:
        response = mutation(client, action, {"id": po})
        assert response.status_code == 200, response.text
    response = mutation(client, "receipt", dict(po=po, lines=[dict(item=item, qty=10, price=5)]))
    assert response.status_code == 200, response.text
    invoice = mutation(
        client,
        "invoice",
        dict(po=po, number="BILL-1", lines=[dict(item=item, qty=10, price=5)], amount=52.5, tax=5),
    ).json()["result"]["id"]
    for action in ["match", "post"]:
        response = mutation(client, action, {"id": invoice})
        assert response.status_code == 200, response.text
    assert mutation(client, "pay", dict(id=invoice, amount=52.5, reference="BANK-1")).status_code == 200
    assert mutation(client, "close", dict(id=po)).status_code == 200
    assert client.get("/api/finance").json()["reports"]["balanceDifference"] == 0


def test_supplier_isolation_and_staff_boundary(client):
    supplier, item, po = setup_order(client)
    for action in ["submit", "approve", "dispatch"]:
        mutation(client, action, {"id": po})
    other = mutation(client, "supplier", dict(name="Other supplier")).json()["result"]["id"]
    other_po = mutation(
        client, "order", dict(supplier=other, lines=[dict(item=item, qty=1, price=5)])
    ).json()["result"]["id"]
    email = str(uuid4()) + "@example.test"
    result = client.post(
        "/api/users",
        json=dict(
            email=email,
            name="Supplier",
            role="supplier",
            supplier_id=supplier,
            password="supplier-password-123",
        ),
    )
    assert result.status_code == 200, result.text
    client.post("/api/auth/logout", json={})
    assert (
        client.post("/api/auth/login", json=dict(email=email, password="supplier-password-123")).status_code
        == 200
    )
    assert client.get("/api/workspace").status_code == 403
    portal = client.get("/api/portal").json()
    assert [o["id"] for o in portal["orders"]] == [po]
    response = client.post(
        "/api/portal",
        json=dict(
            action="respond",
            data={"po": other_po, "decision": "accept"},
            revision=portal["revision"],
            requestId=str(uuid4()),
        ),
    )
    assert response.status_code == 400
    response = client.post(
        "/api/portal",
        json=dict(
            action="respond",
            data={"po": po, "decision": "accept"},
            revision=portal["revision"],
            requestId=str(uuid4()),
        ),
    )
    assert response.status_code == 200


def test_encrypted_backup_restores_attachment_and_retains_access(client):
    _, _, po = setup_order(client)
    rev = client.get("/api/workspace").json()["revision"]
    content = b"%PDF-1.4\nIntegration restore test\n%%EOF"
    response = client.post(
        "/api/documents",
        data=dict(collection="orders", target=po, revision=rev),
        files={"file": ("test.pdf", content, "application/pdf")},
    )
    assert response.status_code == 200, response.text
    doc = response.json()["id"]
    passphrase = "backup-test-passphrase"
    response = client.post("/api/backup/export", json={"passphrase": passphrase})
    assert response.status_code == 200, response.text
    envelope = response.json()
    # Restore an older snapshot after new relational rows have been added.
    supplier = client.get("/api/workspace").json()["state"]["suppliers"][0]["id"]
    later_item = mutation(
        client, "item", dict(name="Later item", unit="L", supplier=supplier, price=1, reorder=0, target=10)
    ).json()["result"]["id"]
    later_order = mutation(
        client, "order", dict(supplier=supplier, lines=[dict(item=later_item, qty=1, price=1)])
    )
    assert later_order.status_code == 200, later_order.text
    rev = client.get("/api/workspace").json()["revision"]
    body = dict(passphrase=passphrase, envelope=envelope, revision=rev, preview=True)
    assert (
        client.post("/api/backup/restore", json={**body, "passphrase": "incorrect-password"}).status_code
        == 400
    )
    response = client.post("/api/backup/restore", json=body)
    assert response.status_code == 200, response.text
    response = client.post(
        "/api/backup/restore", json={**body, "preview": False, "company": "Integration test"}
    )
    assert response.status_code == 200, response.text
    assert client.get("/api/documents/" + doc).content == content
    assert all(i["id"] != later_item for i in client.get("/api/workspace").json()["state"]["items"])
    assert client.get("/api/auth/me").status_code == 200


def test_langgraph_worker_runs_with_postgres_checkpoints(client):
    from langgraph.checkpoint.postgres import PostgresSaver
    from lubriflow.automation import build_graph
    from lubriflow.worker import work_once
    from lubriflow.config import settings

    _, _, po = setup_order(client)
    response = mutation(
        client,
        "settings",
        dict(mode="automatic", autoApprove=True, autoMatch=True, limit=100, financeThreshold=200),
    )
    assert response.status_code == 200, response.text
    run = client.post("/api/automation", json={}).json()
    with PostgresSaver.from_conn_string(
        settings().database_url.replace("postgresql+psycopg://", "postgresql://")
    ) as saver:
        saver.setup()
        graph = build_graph(saver)
        assert work_once(graph)
    history = client.get("/api/automation").json()
    result = next(r for r in history if r["id"] == run["id"])
    assert result["status"] == "Completed", result
    state = client.get("/api/workspace").json()["state"]
    assert next(o for o in state["orders"] if o["id"] == po)["status"] == "Approved"
    assert not state["payments"]
