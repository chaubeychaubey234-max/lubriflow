import base64
import hashlib
import json
import os
from copy import deepcopy
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from .auth import staff, role
from .db import database
from .domain import require, COLLECTIONS, lines, get, dec, act, valid_date
from .repository import tenant_lock, load, save
from .storage import read_document, put_document, remove_document

router = APIRouter(prefix="/api/backup")


class BackupRequest(BaseModel):
    passphrase: str = Field(min_length=12, max_length=200)


class RestoreRequest(BackupRequest):
    envelope: dict
    revision: int
    preview: bool = True
    company: str = ""


def cipher(passphrase, salt):
    key = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=600000).derive(
        passphrase.encode()
    )
    return Fernet(base64.urlsafe_b64encode(key))


def validate(s):
    require(s.get("version") == 4, "Unsupported backup version.")
    # Backups predating messaging have no outbox or RFQ records.
    s.setdefault("communications", [])
    s.setdefault("rfqs", [])
    for name in ("stockPositions", "stockCounts", "reservations", "landedCosts", "salesQuotes", "salesReturns", "customerCredits", "boms", "productionOrders"):
        s.setdefault(name, [])
    for name in "accountingDocuments bankFxMovements voucherTypes projects financeBudgets partyFunds fundAllocations fundRefunds financeSchedules fxRevaluations".split():
        s.setdefault(name,[])
    for collection in COLLECTIONS:
        require(isinstance(s.get(collection), list), "Missing collection: " + collection)
        ids = set()
        for r in s[collection]:
            require(
                isinstance(r.get("id"), str) and len(r["id"]) <= 100 and r["id"] not in ids,
                "Duplicate or invalid identifier.",
            )
            ids.add(r["id"])
            if "lines" in r:
                lines(s, r["lines"])
    from .accounting import validate_accounting
    validate_accounting(s)
    for item in s["items"]:
        if item.get("positionsInitialized"):
            positions = [p for p in s["stockPositions"] if p["item"] == item["id"]]
            require(sum((dec(p["qty"]) for p in positions), dec(0)) == dec(item["stock"]), "Stock position totals do not match item balance.")
            for p in positions:
                require(dec(p["qty"]) >= 0 and dec(p["value"]) >= 0, "Negative stock quantity or value.")
                get(s, "warehouses", p["warehouse"])
                if p["bin"]:
                    require(get(s, "bins", p["bin"])["warehouse"] == p["warehouse"], "Stock bin warehouse mismatch.")
                require(p["status"] in {"Available", "Quarantined"}, "Unknown stock disposition.")
                if p["serial"] and p["qty"]:
                    require(p["qty"] == 1 and sum(1 for other in positions if other["serial"] == p["serial"] and other["qty"] > 0) == 1, "Duplicate or invalid stocked serial.")
                require(sum((dec(r["remaining"]) for r in s["reservations"] if r["position"] == p["id"] and r["status"] == "Active"), dec(0)) <= dec(p["qty"]), "Reservations exceed stock.")
        get(s, "suppliers", item["supplier"])
        require(
            dec(item["stock"]) >= 0
            and dec(item["stock"]) == sum(map(dec, item["stockByWarehouse"].values())),
            "Stock balance mismatch.",
        )
        for warehouse, qty in item["stockByWarehouse"].items():
            if item.get("positionsInitialized"):
                require(sum((dec(p["qty"]) for p in positions if p["warehouse"] == warehouse), dec(0)) == dec(qty), "Warehouse position total mismatch.")
            get(s, "warehouses", warehouse)
            require(dec(qty) >= 0, "Negative warehouse stock.")
    for order in s["orders"]:
        get(s, "suppliers", order["supplier"])
        get(s, "warehouses", order["warehouse"])
        get(s, "ledgers", order["purchaseLedger"])
    for invoice in s["invoices"]:
        require(
            get(s, "orders", invoice["po"])["supplier"] == invoice["supplier"], "Invoice supplier mismatch."
        )
        require(dec(invoice["amount"]) > 0, "Invalid invoice amount.")
    for receipt in s["receipts"]:
        get(s, "orders", receipt["po"])
        get(s, "warehouses", receipt["warehouse"])
    for returned in s["returns"]:
        require(get(s, "receipts", returned["receipt"])["po"] == returned["po"], "Return reference mismatch.")
    for credit in s["credits"]:
        original = get(s, "invoices", credit["invoice"])
        require(
            original["supplier"] == credit["supplier"] and original["po"] == credit["po"],
            "Credit reference mismatch.",
        )
    for payment in s["payments"]:
        get(s, "invoices", payment["invoice"])
        require(dec(payment["amount"]) > 0, "Invalid payment amount.")
    for entry in s["journal"]:
        valid_date(entry["date"])
        require(
            bool(entry["entries"])
            and sum(dec(e.get("debit", 0)) - dec(e.get("credit", 0)) for e in entry["entries"]) == 0,
            "Unbalanced journal.",
        )
        require(
            all(dec(e.get("debit", 0)) >= 0 and dec(e.get("credit", 0)) >= 0 for e in entry["entries"]),
            "Negative journal amount.",
        )
    for doc in s["attachments"]:
        require(
            doc["collection"] in {"orders", "requisitions", "quotes", "receipts", "invoices"},
            "Invalid attachment collection.",
        )
        get(s, doc["collection"], doc["target"])
        require(
            doc["type"] in {"application/pdf", "image/png", "image/jpeg"} and 0 < doc["size"] <= 10_000_000,
            "Invalid attachment metadata.",
        )
    # Reuse the live policy validator.
    scratch = deepcopy(s)
    act(scratch, "settings", s["settings"], {"id": "restore-check", "role": "admin"})
    return s


@router.post("/export")
def export(body: BackupRequest, user=Depends(staff), db=Depends(database)):
    role(user, "admin")
    s = load(db, tenant_lock(db, user.tenant_id))
    files, total = [], 0
    for doc in s["attachments"]:
        raw = read_document(user.tenant_id, doc["key"])
        total += len(raw)
        require(
            total <= 10_000_000,
            "Portable backup supports 10 MB of attachments. Use database/object-store backups for larger datasets.",
        )
        files.append(
            dict(id=doc["id"], data=base64.b64encode(raw).decode(), sha256=hashlib.sha256(raw).hexdigest())
        )
    raw = json.dumps({"state": s, "files": files}).encode()
    require(len(raw) <= 14_000_000, "Backup is too large for portable export.")
    salt = os.urandom(16)
    return dict(
        format="lubriflow-v2-encrypted",
        salt=base64.b64encode(salt).decode(),
        data=cipher(body.passphrase, salt).encrypt(raw).decode(),
    )


@router.post("/restore")
def restore(body: RestoreRequest, user=Depends(staff), db=Depends(database)):
    from .api import audit

    role(user, "admin")
    require(body.envelope.get("format") == "lubriflow-v2-encrypted", "Unsupported backup format.")
    try:
        salt = base64.b64decode(body.envelope["salt"], validate=True)
        require(len(salt) == 16, "Invalid backup salt.")
        bundle = json.loads(cipher(body.passphrase, salt).decrypt(body.envelope["data"].encode()))
    except (InvalidToken, KeyError, ValueError):
        raise ValueError("Backup is damaged or passphrase is incorrect.") from None
    s = validate(bundle["state"])
    tenant = tenant_lock(db, user.tenant_id)
    require(tenant.revision == body.revision, "Workspace changed. Refresh before saving.")
    files = bundle["files"]
    require(len(files) == len(s["attachments"]), "Attachment count mismatch.")
    decoded, total = [], 0
    for doc in s["attachments"]:
        file = next((f for f in files if f["id"] == doc["id"]), None)
        require(file is not None, "Missing attachment.")
        raw = base64.b64decode(file["data"], validate=True)
        total += len(raw)
        require(
            total <= 10_000_000
            and len(raw) == doc["size"]
            and hashlib.sha256(raw).hexdigest() == file["sha256"],
            "Attachment integrity check failed.",
        )
        decoded.append((doc, raw))
    if body.preview:
        return dict(orders=len(s["orders"]), invoices=len(s["invoices"]), documents=len(decoded))
    require(body.company == tenant.name, "Type the current company name to restore.")
    # Account identities are external to the backup and are never replaced.
    current = load(db, tenant)
    require(not any(m["status"] == "Sending" for m in current["communications"]), "Wait for in-flight supplier messages before restoring.")
    # External messages cannot be undone by restoring business records. Preserve current
    # delivery history and pause automation so an old snapshot cannot resend supplier POs.
    s["communications"] = current["communications"]
    for message in s["communications"]:
        if message["status"] in {"Queued", "Retry"}:
            message.update(status="Cancelled", error="Backup restored; review document before sending.")
    s["settings"].setdefault("supplierMessaging", {})["enabled"] = False
    s["audit"] = current["audit"]
    for prefix, number in current["series"].items():
        s["series"][prefix] = max(number, s["series"].get(prefix, 0))
    uploaded = []
    try:
        for doc, raw in decoded:
            doc["key"] = put_document(user.tenant_id, raw)
            uploaded.append(doc["key"])
        audit(
            s,
            user,
            "Encrypted backup restored",
            "Business records replaced; current users and audit preserved.",
        )
        save(db, tenant, s)
        db.commit()
    except Exception:
        for key in uploaded:
            remove_document(user.tenant_id, key)
        raise
    return {"ok": True}
