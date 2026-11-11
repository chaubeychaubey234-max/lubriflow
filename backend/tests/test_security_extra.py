from uuid import uuid4
from test_api import mutation, setup_order

pytest_plugins = ["test_api"]


def test_import_commit_retry_and_atomic_failure(client):
    rev = client.get("/api/workspace").json()["revision"]
    body = dict(
        action="supplier",
        data={"rows": [{"name": "Imported vendor"}], "preview": False},
        requestId=str(uuid4()),
        revision=rev,
    )
    first = client.post("/api/imports", json=body)
    assert first.status_code == 200, first.text
    assert client.post("/api/imports", json=body).json() == first.json()
    before = client.get("/api/workspace").json()
    body.update(
        requestId=str(uuid4()),
        revision=before["revision"],
        data={"rows": [{"name": "Will roll back"}, {"name": ""}], "preview": False},
    )
    assert client.post("/api/imports", json=body).status_code == 400
    assert client.get("/api/workspace").json()["revision"] == before["revision"]


def test_other_tenant_cannot_download_document(client):
    from fastapi.testclient import TestClient
    from lubriflow.api import app
    from lubriflow.db import Session
    from lubriflow.models import Tenant, User
    from lubriflow.repository import save
    from lubriflow.domain import empty
    from lubriflow.auth import hash_password

    _, _, po = setup_order(client)
    rev = client.get("/api/workspace").json()["revision"]
    doc = client.post(
        "/api/documents",
        data=dict(collection="orders", target=po, revision=rev),
        files={"file": ("a.pdf", b"%PDF-test", "application/pdf")},
    ).json()["id"]
    email = str(uuid4()) + "@example.test"
    with Session.begin() as db:
        tenant = Tenant(name="Other tenant", settings={}, series={})
        db.add(tenant)
        db.flush()
        save(db, tenant, empty("Other tenant"))
        db.add(
            User(
                tenant_id=tenant.id,
                email=email,
                name="Other admin",
                role="admin",
                password_hash=hash_password("other-password-123"),
            )
        )
    with TestClient(app) as other:
        other.headers.update({"Origin": "http://localhost:3000", "X-Lubriflow-Request": "1"})
        assert (
            other.post("/api/auth/login", json=dict(email=email, password="other-password-123")).status_code
            == 200
        )
        assert other.get("/api/documents/" + doc).status_code == 400
        assert other.get("/api/workspace").json()["state"]["orders"] == []


def test_password_change_revokes_sessions(client):
    old_cookie = client.cookies.get("lubriflow_session")
    assert (
        client.post(
            "/api/auth/password", json=dict(current_password="wrong", new_password="new-password-123")
        ).status_code
        == 400
    )
    result = client.post(
        "/api/auth/password",
        json=dict(current_password="test-password-at-least-12", new_password="new-password-123"),
    )
    assert result.status_code == 200, result.text
    client.cookies.set("lubriflow_session", old_cookie)
    assert client.get("/api/auth/me").status_code == 401


def test_saved_voucher_clears_own_draft(client):
    _, item, _ = setup_order(client)
    assert (
        mutation(client, "saveDraft", dict(kind="requisition", values={"note": "Draft"})).status_code == 200
    )
    assert mutation(client, "requisition", dict(lines=[dict(item=item, qty=1, price=5)])).status_code == 200
    assert client.get("/api/workspace").json()["state"]["drafts"] == []


def test_upload_rejects_unsupported_content(client):
    _, _, po = setup_order(client)
    rev = client.get("/api/workspace").json()["revision"]
    response = client.post(
        "/api/documents",
        data=dict(collection="orders", target=po, revision=rev),
        files={"file": ("a.pdf", b"<script>alert(1)</script>", "application/pdf")},
    )
    assert response.status_code == 400
    assert client.get("/api/workspace").json()["revision"] == rev
