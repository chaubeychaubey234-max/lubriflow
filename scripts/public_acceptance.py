"""Exercise synthetic demo workflows over the real public HTTPS endpoint."""
import json
import os
from pathlib import Path
import time
from uuid import uuid4
import httpx


def main():
    origin = os.environ["PUBLIC_DEMO_ORIGIN"]
    if not origin.startswith("https://") or not origin.endswith(".trycloudflare.com"):
        raise SystemExit("This check is limited to the authorized temporary demo origin.")
    accounts = json.loads(Path("var/demo-access.json").read_text())["accounts"]
    clients, checks = {}, []
    def passed(label):
        checks.append(label)
        print("PASS " + label, flush=True)
    def call(role, path, body=None):
        result = clients[role].request("POST" if body is not None else "GET", "/api" + path, json=body)
        if result.status_code != 200:
            raise AssertionError(f"{role} {path}: HTTP {result.status_code}: {result.text[:300]}")
        return result.json()
    def command(role, action, data):
        revision = call(role, "/workspace")["revision"]
        return call(role, "/workspace", dict(action=action, data=data, revision=revision, requestId=str(uuid4())))
    def run_automation():
        run = call("admin", "/automation", {})
        for _ in range(30):
            result = next(row for row in call("admin", "/automation") if row["id"] == run["id"])
            if result["status"] == "Completed":
                return result
            if result["status"] == "Failed":
                raise AssertionError("Automation job failed")
            time.sleep(1)
        raise AssertionError("Automation worker did not finish within the polling limit")
    try:
        with httpx.Client(base_url=origin, timeout=30) as anonymous:
            assert anonymous.get("/").status_code == 200
            assert anonymous.get("/api/health").json()["status"] == "ok"
            assert anonymous.get("/api/workspace").status_code == 401
        passed("Public HTTPS page, API health and anonymous access rejection")
        for account in accounts:
            client = httpx.Client(base_url=origin, timeout=30,
                                 headers={"Origin": origin, "X-Lubriflow-Request": "1"})
            clients[account["role"]] = client
            response = client.post("/api/auth/login", json={k: account[k] for k in ["email", "password"]})
            assert response.status_code == 200, response.status_code
            cookie = response.headers["set-cookie"].lower()
            assert "secure" in cookie and "httponly" in cookie and "samesite=strict" in cookie
        passed("All eight role accounts sign in with Secure HttpOnly SameSite cookies")
        assert clients["supplier"].get("/api/workspace").status_code == 403
        viewer_revision = call("viewer", "/workspace")["revision"]
        assert clients["viewer"].post("/api/workspace", json=dict(action="supplier", data={"name": "Denied"},
               revision=viewer_revision, requestId=str(uuid4()))).status_code in (400, 403)
        assert clients["admin"].post("/api/workspace", json={}, headers={"Origin": "https://wrong.example"}).status_code == 403
        passed("Supplier/staff boundary, viewer write rejection and cross-origin rejection")
        state = call("buyer", "/workspace")["state"]
        item = next(row for row in state["items"] if row["sku"] == "DEMO-BOTTLE")
        vendor = item["supplier"]
        po = command("buyer", "order", dict(supplier=vendor, lines=[dict(item=item["id"], qty=10, price=2)], tax=5))["result"]["id"]
        command("buyer", "submit", dict(id=po))
        command("approver", "approve", dict(id=po))
        command("buyer", "dispatch", dict(id=po))
        command("stores", "receipt", dict(po=po, lines=[dict(item=item["id"], qty=10, price=2)]))
        invoice = command("finance", "invoice", dict(po=po, number="PUBLIC-MANUAL-" + uuid4().hex[:8],
                     lines=[dict(item=item["id"], qty=10, price=2)], amount=21, tax=5))["result"]["id"]
        command("finance", "match", dict(id=invoice))
        command("finance", "post", dict(id=invoice))
        command("finance", "pay", dict(id=invoice, amount=21, reference="PUBLIC-TEST-" + uuid4().hex[:8]))
        command("buyer", "close", dict(id=po))
        assert call("finance", "/finance")["reports"]["balanceDifference"] == 0
        passed("Manual PO approval, receipt, invoice match/post, recorded payment and closure; balanced books")
        command("admin", "item", dict(name="Demo reorder test " + uuid4().hex[:6], unit="pcs", supplier=vendor,
                                      price=1, stock=0, reorder=10, target=20, quality=False))
        command("admin", "settings", dict(mode="automatic", autoReorder=True, autoPO=True, autoApprove=True,
                                           autoMatch=True, limit=1000, financeThreshold=50000))
        auto_po = command("buyer", "order", dict(supplier=vendor, lines=[dict(item=item["id"], qty=20, price=2)], tax=5))["result"]["id"]
        run_automation()
        auto_state = call("buyer", "/workspace")["state"]
        assert next(row for row in auto_state["orders"] if row["id"] == auto_po)["status"] == "Approved"
        assert auto_state["requisitions"]
        passed("Live LangGraph worker creates replenishment requisitions and submits/approves eligible PO")
        command("buyer", "dispatch", dict(id=auto_po))
        command("stores", "receipt", dict(po=auto_po, lines=[dict(item=item["id"], qty=20, price=2)]))
        auto_invoice = command("finance", "invoice", dict(po=auto_po, number="PUBLIC-AUTO-" + uuid4().hex[:8],
                          lines=[dict(item=item["id"], qty=20, price=2)], amount=42, tax=5))["result"]["id"]
        run_automation()
        state = call("finance", "/workspace")["state"]
        assert next(row for row in state["invoices"] if row["id"] == auto_invoice)["status"] == "Matched"
        passed("Live LangGraph worker matches invoice against PO and accepted goods")
        command("finance", "post", dict(id=auto_invoice))
        command("finance", "pay", dict(id=auto_invoice, amount=42, reference="PUBLIC-TEST-" + uuid4().hex[:8]))
        command("buyer", "close", dict(id=auto_po))
        command("admin", "settings", dict(mode="manual"))
        for role in clients:
            call(role, "/auth/logout", {})
            assert clients[role].get("/api/auth/me").status_code == 401
        passed("Logout revokes sessions; demo returned to manual mode")
        Path("docs/public-test-results.json").write_text(json.dumps(dict(origin=origin, checks=checks,
            verified_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            automation_boundaries=["Dispatch, receiving, invoice entry, posting, payment recording and closure still require users",
                                   "Payments are records only; no bank transfer integration"],
            browser_interactions_verified=False), indent=2))
    finally:
        for client in clients.values():
            client.close()


if __name__ == "__main__":
    main()
