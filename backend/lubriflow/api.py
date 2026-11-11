from copy import deepcopy
import hashlib
import logging
from uuid import uuid4
from fastapi import FastAPI, Depends, Request, Response, UploadFile, File, Form
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, delete, text as sql_text
from sqlalchemy.exc import IntegrityError
from .config import settings
from .db import database
from .models import Tenant, User, LoginSession, AutomationRun, now
from .security import router as security_router
from .auth import current_user, staff, authenticate, actor, role, hash_password, digest
from .domain import RuleError, require, get, today, text, amount, identifier, allowed, procurement_insights
from .repository import load, save, tenant_lock, execute, replay_command, remember_command
from .finance import chart, reports
from .storage import put_document, read_document, remove_document
from .backup import router as backup_router
from .ocr import router as ocr_router
from .sso import router as sso_router
from .companies import router as companies_router
from .uae_tax_api import router as uae_tax_router
from starlette.middleware.sessions import SessionMiddleware

app = FastAPI(title="LubriFlow API", version="0.1.0", docs_url="/api/docs", openapi_url="/api/openapi.json")
logger = logging.getLogger("lubriflow")


class BodyLimit:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        chunks, size = [], 0
        while True:
            event = await receive()
            if event["type"] == "http.disconnect":
                return
            size += len(event.get("body", b""))
            if size > 20_000_000:
                return await JSONResponse({"detail": "Request is too large."}, status_code=413)(
                    scope, receive, send
                )
            chunks.append(event)
            if not event.get("more_body", False):
                break

        async def replay():
            return chunks.pop(0) if chunks else await receive()

        await self.app(scope, replay, send)


app.add_middleware(BodyLimit)
if settings().oidc_issuer:
    app.add_middleware(SessionMiddleware, secret_key=settings().oidc_session_secret,
                       session_cookie="lubriflow_oidc", max_age=300, same_site="lax",
                       https_only=settings().environment == "production")

app.include_router(backup_router)
app.include_router(ocr_router)
app.include_router(security_router)
app.include_router(sso_router)
app.include_router(companies_router)
app.include_router(uae_tax_router)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        if (
            request.headers.get("x-lubriflow-request") != "1"
            or request.headers.get("origin") != settings().app_origin
        ):
            return JSONResponse({"detail": "Untrusted request origin."}, status_code=403)
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    if settings().environment == "production":
        response.headers["Strict-Transport-Security"] = "max-age=31536000"
    return response


@app.exception_handler(RuleError)
@app.exception_handler(ValueError)
async def domain_error(request, exc):
    return JSONResponse({"detail": str(exc)}, status_code=409 if "Workspace changed" in str(exc) else 400)


@app.exception_handler(IntegrityError)
async def integrity_error(request, exc):
    return JSONResponse(
        {"detail": "A conflicting or duplicate record exists. Refresh and retry."}, status_code=409
    )


@app.exception_handler(KeyError)
async def missing_field(request, exc):
    return JSONResponse(
        {"detail": "A required field is missing. Review the voucher fields."}, status_code=400
    )


class Login(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=128)
    code: str = Field(default="", max_length=100)


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=12, max_length=128)
    code: str = Field(default="", max_length=100)


class Command(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: str = Field(pattern=r"^[A-Za-z]{1,40}$")
    data: dict = Field(default_factory=dict)
    requestId: str = Field(pattern=r"^[A-Za-z0-9_-]{8,120}$")
    revision: int = Field(ge=0)


class BankImportPreview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    csv: str = Field(min_length=1, max_length=1_000_000)
    bankLedger: str
    statementCurrency: str
    openingBalance: str | float | None = None
    mappingId: str | None = None
    mapping: dict[str, str] = Field(default_factory=dict, max_length=20)


class MaterialPlanPreview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    bom: str = Field(max_length=100)
    qty: float = Field(gt=0, le=1_000_000_000)
    warehouse: str = Field(max_length=100)
    reference: str = Field(min_length=1, max_length=100)
    bomSelections: dict[str, str] = Field(default_factory=dict, max_length=200)
    createPurchaseRequests: bool = False


@app.post('/api/material-plan-preview')
def material_plan_preview(body: MaterialPlanPreview, user=Depends(staff), db=Depends(database)):
    from .material_planning import plan
    role(user, 'admin', 'production')
    return plan(load(db, tenant_lock(db, user.tenant_id)), body.model_dump())


@app.post("/api/bank-import-preview")
def bank_import_preview(body: BankImportPreview, user=Depends(staff), db=Depends(database)):
    from .bank_import import import_statement
    role(user, "admin", "finance")
    s = load(db, tenant_lock(db, user.tenant_id))
    return import_statement(s, body.model_dump(), actor(user), preview=True)


@app.get("/api/bank-match-suggestions/{statement_id}")
def bank_match_suggestions(statement_id: str, user=Depends(staff), db=Depends(database)):
    from .bank_import import suggestions
    role(user, "admin", "finance")
    return suggestions(load(db, tenant_lock(db, user.tenant_id)), statement_id)


def snapshot(db, tenant, user):
    state = load(db, tenant)
    if user.role not in {"admin", "buyer", "approver", "finance"}:
        state["communications"] = []
        for supplier in state["suppliers"]:
            supplier.pop("messaging", None)
    if user.role not in {"admin","finance"}:
        for collection in "accountingDocuments bankFxMovements voucherTypes financeBudgets partyFunds fundAllocations fundRefunds financeSchedules fxRevaluations".split():
            state[collection]=[]
    state["drafts"] = [d for d in state["drafts"] if d["actor"] == user.id]
    if user.role != "admin":
        state["accounts"] = state["accounts"] if user.role == "finance" else []
    return dict(state=state, revision=tenant.revision, actor=actor(user))


@app.get("/api/health")
def health(db=Depends(database)):
    db.execute(sql_text("SELECT 1"))
    return {"status": "ok", "service": "lubriflow-api"}


@app.post("/api/auth/login")
def login(data: Login, response: Response, db=Depends(database)):
    require(not settings().oidc_only, "Password sign-in is disabled. Use company SSO.")
    user, token = authenticate(db, data.email.strip(), data.password, data.code)
    response.set_cookie(
        "lubriflow_session",
        token,
        httponly=True,
        secure=settings().environment == "production",
        samesite="strict",
        max_age=8 * 3600,
        path="/",
    )
    return actor(user)


@app.get("/api/auth/me")
def me(user=Depends(current_user)):
    return actor(user)


@app.post("/api/auth/password")
def change_password(
    body: PasswordChange, response: Response, user=Depends(current_user), db=Depends(database)
):
    from .security import proof
    user = proof(db, user, body.current_password, body.code)
    user.password_hash = hash_password(body.new_password)
    db.execute(delete(LoginSession).where(LoginSession.user_id == user.id))
    tenant = tenant_lock(db, user.tenant_id)
    state = load(db, tenant)
    audit(state, user, "Password changed", "Existing sessions revoked.")
    save(db, tenant, state)
    db.commit()
    response.delete_cookie("lubriflow_session", path="/")
    return {"ok": True, "message": "Password changed. Sign in again."}


@app.post("/api/auth/logout")
def logout(request: Request, response: Response, user=Depends(current_user), db=Depends(database)):
    db.execute(
        delete(LoginSession).where(
            LoginSession.token_hash == digest(request.cookies.get("lubriflow_session", ""))
        )
    )
    db.commit()
    response.delete_cookie("lubriflow_session", path="/")
    return {"ok": True}


@app.get("/api/workspace")
def workspace(user=Depends(staff), db=Depends(database)):
    tenant = tenant_lock(db, user.tenant_id)
    return snapshot(db, tenant, user)


@app.post("/api/workspace")
def command(body: Command, user=Depends(staff), db=Depends(database)):
    result, revision, duplicate = execute(
        db, user.tenant_id, actor(user), body.action, body.data, body.requestId, body.revision
    )
    output = snapshot(db, db.get(Tenant, user.tenant_id), user)
    db.commit()
    return dict(**output, result=result, duplicate=duplicate)


@app.get("/api/finance")
def financial_reports(
    start: str = "2000-01-01", end: str | None = None, user=Depends(staff), db=Depends(database)
):
    role(user, "admin", "finance")
    s = load(db, tenant_lock(db, user.tenant_id))
    return dict(accounts=chart(s), reports=reports(s, start, end or today()))


@app.get("/api/inventory-report")
def inventory_report_endpoint(user=Depends(staff), db=Depends(database)):
    from .inventory import inventory_report
    return inventory_report(load(db, tenant_lock(db, user.tenant_id)))


@app.get("/api/barcode")
def barcode_lookup(code: str, user=Depends(staff), db=Depends(database)):
    require(0 < len(code) <= 200, "Scan a valid barcode.")
    s = load(db, tenant_lock(db, user.tenant_id))
    matches = [i for i in s["items"] if code in {i.get("barcode"), i.get("sku")}]
    require(len(matches) == 1, "Barcode is unknown or ambiguous.")
    return dict(item=matches[0], positions=[p for p in s["stockPositions"] if p["item"] == matches[0]["id"]])


@app.get("/api/stock-trace")
def stock_trace(item: str, lot: str = "", serial: str = "", user=Depends(staff), db=Depends(database)):
    s = load(db, tenant_lock(db, user.tenant_id))
    get(s, "items", item)
    moves = [m for m in s["stockMoves"] if m["item"] == item and
             (not lot and not serial or any((not lot or a["lot"] == lot) and (not serial or a["serial"] == serial) for a in m.get("allocations", [])))]
    references = {m["reference"] for m in moves}
    production = [p for p in s["productionOrders"] if p["id"] in references]
    related_ids = {p.get("outputMovement") for p in production} | {c["movement"] for p in production for c in p["consumption"]}
    genealogy = [m for m in s["stockMoves"] if m["id"] in related_ids]
    related_references = references | {m["reference"] for m in genealogy}
    return dict(movements=moves, production=production, genealogy=genealogy,
                receipts=[r for r in s["receipts"] if r["id"] in related_references],
                deliveries=[r for r in s["deliveries"] if r["id"] in related_references],
                returns=[r for r in s["salesReturns"] if r["id"] in related_references])


class MessagePreview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    purpose: str = Field(max_length=30)
    source: str = Field(max_length=100)
    channel: str = Field(max_length=20)


@app.post("/api/supplier-message-preview")
def supplier_message_preview(body: MessagePreview, user=Depends(staff), db=Depends(database)):
    from .messaging import queue
    role(user, "admin", "buyer")
    s = load(db, tenant_lock(db, user.tenant_id))
    # In-memory preview only: no save, queue persistence or network side effects.
    return queue(s, body.purpose, body.source, body.channel, actor(user))


@app.get("/api/procurement-insights")
def procurement_reports(lookback_days: int = 90, user=Depends(staff), db=Depends(database)):
    role(user, "admin", "buyer", "approver", "finance")
    return procurement_insights(load(db, tenant_lock(db, user.tenant_id)), lookback_days)


class UserInput(BaseModel):
    email: str = Field(max_length=254)
    name: str = Field(min_length=1, max_length=200)
    role: str
    password: str = Field(min_length=12, max_length=128)
    supplier_id: str | None = None


@app.get("/api/users")
def users(user=Depends(staff), db=Depends(database)):
    role(user, "admin")
    return [
        dict(id=u.id, name=u.name, email=u.email, role=u.role, active=u.active, supplier_id=u.supplier_id)
        for u in db.scalars(select(User).where(User.tenant_id == user.tenant_id))
    ]


@app.post("/api/users")
def add_user(body: UserInput, user=Depends(staff), db=Depends(database)):
    role(user, "admin")
    require(
        body.role
        in {"admin", "buyer", "requester", "approver", "stores", "quality", "production", "sales", "finance", "viewer", "supplier"},
        "Unknown role.",
    )
    import re

    require(re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", body.email.strip()), "Invalid email.")
    tenant = tenant_lock(db, user.tenant_id)
    s = load(db, tenant)
    if body.role == "supplier":
        get(s, "suppliers", body.supplier_id)
    created = User(
        tenant_id=user.tenant_id,
        email=body.email.strip().casefold(),
        name=body.name,
        role=body.role,
        supplier_id=body.supplier_id if body.role == "supplier" else None,
        password_hash=hash_password(body.password),
    )
    db.add(created)
    audit(s, user, "User created", body.email)
    save(db, tenant, s)
    db.commit()
    return {"id": created.id}


@app.post("/api/users/{user_id}/disable")
def disable_user(user_id: str, user=Depends(staff), db=Depends(database)):
    role(user, "admin")
    require(user_id != user.id, "You cannot disable your own account.")
    tenant = tenant_lock(db, user.tenant_id)
    target = db.scalar(select(User).where(User.id == user_id, User.tenant_id == user.tenant_id))
    require(target is not None, "User not found.")
    target.active = False
    db.execute(delete(LoginSession).where(LoginSession.user_id == target.id))
    s = load(db, tenant)
    audit(s, user, "User disabled", target.email)
    save(db, tenant, s)
    db.commit()
    return {"ok": True}


def audit(s, user, action, detail):
    s["audit"].insert(
        0,
        dict(
            id="EV-" + str(uuid4()),
            at=now().isoformat(),
            actor=user.name,
            actorId=user.id,
            action=action,
            detail=detail,
        ),
    )


@app.post("/api/documents")
async def upload(
    collection: str = Form(),
    target: str = Form(),
    revision: int = Form(),
    file: UploadFile = File(),
    user=Depends(staff),
    db=Depends(database),
):
    actions = {
        "orders": "order",
        "requisitions": "requisition",
        "quotes": "quote",
        "receipts": "receipt",
        "invoices": "invoice",
    }
    require(
        collection in actions and allowed(actor(user), actions[collection]),
        "Your role cannot attach to this record.",
    )
    data = await file.read(10_000_001)
    require(0 < len(data) <= 10_000_000, "File must be between 1 byte and 10 MB.")
    kind = (
        "application/pdf"
        if data.startswith(b"%PDF-")
        else "image/png"
        if data.startswith(b"\x89PNG\r\n\x1a\n")
        else "image/jpeg"
        if data.startswith(b"\xff\xd8\xff")
        else None
    )
    require(kind is not None, "Upload a PDF, PNG or JPEG document.")
    tenant = tenant_lock(db, user.tenant_id)
    require(tenant.revision == revision, "Workspace changed. Refresh before saving.")
    s = load(db, tenant)
    get(s, collection, target)
    key = put_document(user.tenant_id, data)
    try:
        doc = dict(
            id=identifier(s, "DOC"),
            collection=collection,
            target=target,
            key=key,
            name=(file.filename or "document").replace("\r", "").replace("\n", "")[:200],
            type=kind,
            size=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
            actor=user.id,
        )
        s["attachments"].insert(0, doc)
        audit(s, user, "Document uploaded", doc["id"])
        save(db, tenant, s)
        db.commit()
        return {"id": doc["id"]}
    except Exception:
        remove_document(user.tenant_id, key)
        raise


@app.get("/api/documents/{document_id}")
def download(document_id: str, user=Depends(staff), db=Depends(database)):
    s = load(db, tenant_lock(db, user.tenant_id))
    doc = get(s, "attachments", document_id)
    return Response(
        read_document(user.tenant_id, doc["key"]),
        media_type=doc["type"],
        headers={"Content-Disposition": 'attachment; filename="document"'},
    )


@app.get("/api/portal")
def portal(user=Depends(current_user), db=Depends(database)):
    role(user, "supplier")
    tenant = tenant_lock(db, user.tenant_id)
    s = load(db, tenant)
    supplier = get(s, "suppliers", user.supplier_id)
    orders = [
        dict(
            id=o["id"],
            date=o["date"],
            due=o["due"],
            status=o["status"],
            tax=o["tax"],
            freight=o["freight"],
            paymentTerms=o["paymentTerms"],
            deliveryAddress=o["deliveryAddress"],
            response=o.get("supplierResponse"),
            lines=[
                dict(**l, name=get(s, "items", l["item"])["name"], unit=get(s, "items", l["item"])["unit"])
                for l in o["lines"]
            ],
        )
        for o in s["orders"]
        if o["supplier"] == supplier["id"]
        and o["status"] in {"Issued", "Acknowledged", "Part received", "Received", "Closed"}
    ]
    return dict(
        company=tenant.name,
        supplier=supplier["name"],
        revision=tenant.revision,
        orders=orders,
        submissions=[v for v in s["portalSubmissions"] if v["supplier"] == user.supplier_id],
    )


@app.post("/api/portal")
def portal_command(body: Command, user=Depends(current_user), db=Depends(database)):
    role(user, "supplier")
    tenant = tenant_lock(db, user.tenant_id)
    previous, fingerprint = replay_command(db, user.tenant_id, user.id, "portal", body)
    if previous is not None:
        return previous
    require(tenant.revision == body.revision, "Workspace changed. Refresh before saving.")
    s = load(db, tenant)
    po = get(s, "orders", body.data.get("po"))
    require(
        po["supplier"] == user.supplier_id
        and po["status"] in {"Issued", "Acknowledged", "Part received", "Received"},
        "Order is unavailable.",
    )
    if body.action == "respond":
        require(
            po["status"] == "Issued"
            and not po.get("supplierResponse")
            and body.data.get("decision") in {"accept", "decline"},
            "Order cannot receive this decision.",
        )
        note = text(body.data.get("note", ""), "Reason", body.data["decision"] == "decline")
        po["supplierResponse"] = dict(decision=body.data["decision"], note=note, actor=user.id)
        if body.data["decision"] == "accept":
            po["status"] = "Acknowledged"
    elif body.action == "submitInvoice":
        number = text(body.data.get("number"), "Invoice reference", True)
        require(
            not any(
                v["supplier"] == user.supplier_id and v["number"].casefold() == number.casefold()
                for v in s["portalSubmissions"] + s["invoices"]
            ),
            "Invoice reference already exists.",
        )
        s["portalSubmissions"].insert(
            0,
            dict(
                id=identifier(s, "SUB"),
                po=po["id"],
                supplier=user.supplier_id,
                number=number,
                amount=amount(body.data.get("amount"), True),
                date=today(),
                status="Awaiting finance review",
                note=text(body.data.get("note", "")),
            ),
        )
    else:
        raise RuleError("Unsupported supplier action.")
    audit(s, user, "Supplier " + body.action, po["id"])
    save(db, tenant, s)
    remember_command(db, user.tenant_id, user.id, body, fingerprint, {"ok": True})
    db.commit()
    return {"ok": True}


@app.get("/api/automation")
def runs(user=Depends(staff), db=Depends(database)):
    role(user, "admin")
    return [
        dict(id=r.id, status=r.status, result=r.result, createdAt=r.created_at.isoformat())
        for r in db.scalars(
            select(AutomationRun)
            .where(AutomationRun.tenant_id == user.tenant_id)
            .order_by(AutomationRun.created_at.desc())
            .limit(50)
        )
    ]


@app.post("/api/automation")
def enqueue(user=Depends(staff), db=Depends(database)):
    role(user, "admin")
    tenant = tenant_lock(db, user.tenant_id)
    require(tenant.settings.get("mode") == "automatic", "Switch to automatic mode first.")
    existing = db.scalar(
        select(AutomationRun).where(
            AutomationRun.tenant_id == user.tenant_id, AutomationRun.status.in_(["Queued", "Running"])
        )
    )
    if existing:
        return {"id": existing.id, "status": existing.status}
    run = AutomationRun(tenant_id=user.tenant_id, requested_by=user.id)
    db.add(run)
    db.commit()
    return {"id": run.id, "status": run.status}


@app.post("/api/imports")
def import_masters(body: Command, user=Depends(staff), db=Depends(database)):
    from .domain import act

    role(user, "admin")
    require(body.action in {"supplier", "item"}, "Import suppliers or items.")
    rows = body.data.get("rows")
    require(isinstance(rows, list) and 1 <= len(rows) <= 500, "Provide 1–500 rows.")
    tenant = tenant_lock(db, user.tenant_id)
    previous, fingerprint = replay_command(db, user.tenant_id, user.id, "imports", body)
    if previous is not None:
        return previous
    require(tenant.revision == body.revision, "Workspace changed. Refresh before saving.")
    s = load(db, tenant)
    for row in rows:
        if body.action == "item":
            row = deepcopy(row)
            supplier = next((v for v in s["suppliers"] if row.get("supplier") in {v["id"], v["name"]}), None)
            require(supplier is not None, "Unknown supplier in import.")
            row["supplier"] = supplier["id"]
            row["inspectionRequired"] = str(
                row.get("inspectionRequired", row.get("quality", ""))
            ).lower() in {"true", "yes", "1"}
        else:
            require(
                not any(v["name"].casefold() == str(row.get("name", "")).casefold() for v in s["suppliers"]),
                "Duplicate supplier in import.",
            )
        act(s, body.action, row, actor(user))
    if body.data.get("preview", True):
        return {"valid": True, "rows": len(rows)}
    save(db, tenant, s)
    remember_command(db, user.tenant_id, user.id, body, fingerprint, {"imported": len(rows)})
    db.commit()
    return {"imported": len(rows)}
