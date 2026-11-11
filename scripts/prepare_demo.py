"""Create synthetic acceptance-test data only in the isolated lubriflow_demo database."""
import json
from pathlib import Path
import secrets
from sqlalchemy import select
from sqlalchemy.engine import make_url
from lubriflow.config import settings
from lubriflow.db import Session
from lubriflow.models import Tenant, User, uid
from lubriflow.auth import hash_password
from lubriflow.domain import empty, act
from lubriflow.repository import save


def main():
    if make_url(settings().database_url).database != "lubriflow_demo":
        raise SystemExit("Demo setup requires the isolated lubriflow_demo database.")
    path = Path("var/demo-access.json")
    if path.exists():
        raise SystemExit("Demo access already exists; refusing to overwrite credentials.")
    credentials = []
    with Session.begin() as db:
        if db.scalar(select(Tenant.id).limit(1)):
            raise SystemExit("Demo setup requires an empty database.")
        tenant = Tenant(name="LubriFlow Demo — Synthetic test data", settings={}, series={})
        db.add(tenant)
        db.flush()
        accounts = {}
        for role in ["admin", "buyer", "approver", "finance", "stores", "quality", "viewer", "supplier"]:
            password = secrets.token_urlsafe(24)
            user = User(id=uid(), tenant_id=tenant.id, email=role + "@demo.lubriflow.test",
                        name="Demo " + role.title(), role=role, password_hash=hash_password(password))
            accounts[role] = user
            credentials.append(dict(role=role, email=user.email, password=password))
        admin = dict(id=accounts["admin"].id, name=accounts["admin"].name, role="admin")
        buyer = dict(id=accounts["buyer"].id, name=accounts["buyer"].name, role="buyer")
        approver = dict(id=accounts["approver"].id, name=accounts["approver"].name, role="approver")
        state = empty(tenant.name)
        vendor = act(state, "supplier", dict(name="Demo Base Oil Supplier", email="supplier@example.test"), admin)["id"]
        act(state, "approveSupplier", dict(id=vendor, approved=True), admin)
        accounts["supplier"].supplier_id = vendor
        oil = act(state, "item", dict(name="Demo SN500 Base Oil", sku="DEMO-OIL-500", unit="L",
                  supplier=vendor, price=8, stock=0, reorder=100, target=500, quality=True), admin)["id"]
        bottle = act(state, "item", dict(name="Demo 1L Bottle", sku="DEMO-BOTTLE", unit="pcs",
                     supplier=vendor, price=2, stock=0, reorder=100, target=500, quality=False), admin)["id"]
        for item, qty, price in [(oil, 100, 8), (bottle, 50, 2)]:
            order = act(state, "order", dict(supplier=vendor, lines=[dict(item=item, qty=qty, price=price)], tax=5), buyer)["id"]
            act(state, "submit", dict(id=order), buyer)
            act(state, "approve", dict(id=order), approver)
            act(state, "dispatch", dict(id=order), buyer)
        save(db, tenant, state)
        db.add_all(accounts.values())
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with path.open("x") as stream:
            path.chmod(0o600)
            json.dump(dict(accounts=credentials, company=tenant.name), stream, indent=2)
    print("Synthetic demo prepared. Private credentials saved to var/demo-access.json.")


if __name__ == "__main__":
    main()
