from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def uid():
    return str(uuid4())


def now():
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Tenant(Base):
    __tablename__ = "tenants"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(200))
    revision: Mapped[int] = mapped_column(Integer, default=0)
    settings: Mapped[dict] = mapped_column(JSONB, default=dict)
    series: Mapped[dict] = mapped_column(JSONB, default=dict)
    next_run: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    password_hash: Mapped[str] = mapped_column(String(300))
    role: Mapped[str] = mapped_column(String(30))
    supplier_id: Mapped[str | None] = mapped_column(String(100))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    mfa_secret: Mapped[str | None] = mapped_column(String(500))
    mfa_pending: Mapped[str | None] = mapped_column(String(500))
    mfa_pending_expires: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    mfa_last_step: Mapped[int | None] = mapped_column(Integer)
    mfa_recovery: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")


class CompanyMembership(Base):
    __tablename__ = 'company_memberships'
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey('tenants.id'), primary_key=True)
    role: Mapped[str] = mapped_column(String(30))
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class LoginSession(Base):
    __tablename__ = "login_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SSOIdentity(Base):
    __tablename__ = "sso_identities"
    issuer: Mapped[str] = mapped_column(String(500), primary_key=True)
    subject: Mapped[str] = mapped_column(String(255), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)


class SSOAttempt(Base):
    __tablename__ = "sso_attempts"
    state_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class LoginAttempt(Base):
    __tablename__ = "login_attempts"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    failures: Mapped[int] = mapped_column(Integer, default=0)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


# Typed searchable fields are columns. Optional commercial details are retained in JSONB.
# Collections have separate tables, so a supplier and an invoice cannot share a row namespace.
COLLECTIONS = (
    "accountingDocuments",
    "settingsChangeRequests",
    "bankFxMovements",
    "voucherTypes",
    "projects",
    "financeBudgets",
    "partyFunds",
    "fundAllocations",
    "fundRefunds",
    "financeSchedules",
    "fxRevaluations",
    "stockPositions", "stockCounts", "reservations", "landedCosts",
    "salesQuotes", "salesReturns", "customerCredits", "boms", "productionOrders",
    "rfqs",
    "communications",
    "suppliers",
    "items",
    "requisitions",
    "quotes",
    "orders",
    "receipts",
    "returns",
    "invoices",
    "credits",
    "payments",
    "stockMoves",
    "journal",
    "comments",
    "warehouses",
    "costCentres",
    "ledgers",
    "prices",
    "drafts",
    "attachments",
    "accounts",
    "portalSubmissions",
    "branches",
    "bins",
    "taxProfiles",
    "customers",
    "contracts",
    "approvalPolicies",
    "automationRules",
    "salesOrders",
    "deliveries",
    "salesInvoices",
    "customerPayments",
    "bankStatements",
    "assets",
    "depreciationRuns",
    "exchangeRates",
    "taxReturns",
)


class RecordMixin:
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), primary_key=True)
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    position: Mapped[int] = mapped_column(Integer)
    status: Mapped[str | None] = mapped_column(String(50), index=True)
    supplier: Mapped[str | None] = mapped_column(String(100), index=True)
    date: Mapped[str | None] = mapped_column(String(10), index=True)
    payload: Mapped[dict] = mapped_column(JSONB)


RECORDS = {
    name: type(
        name[0].upper() + name[1:] + "Record",
        (RecordMixin, Base),
        {"__tablename__": "business_" + name.lower()},
    )
    for name in COLLECTIONS
}


class DocumentLine(Base):
    __tablename__ = "document_lines"
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), primary_key=True)
    collection: Mapped[str] = mapped_column(String(40), primary_key=True)
    record_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    position: Mapped[int] = mapped_column(Integer, primary_key=True)
    item_id: Mapped[str] = mapped_column(String(100), index=True)
    quantity: Mapped[float] = mapped_column(Numeric(20, 6))
    unit_price: Mapped[float] = mapped_column(Numeric(20, 2))
    discount: Mapped[float] = mapped_column(Numeric(5, 2))
    tax_rate: Mapped[float | None] = mapped_column(Numeric(5, 2))
    payload: Mapped[dict] = mapped_column(JSONB)
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "item_id"], ["business_items.tenant_id", "business_items.id"]),
    )


class AuditEvent(Base):
    __tablename__ = "audit_events"
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), primary_key=True)
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    actor_id: Mapped[str] = mapped_column(String(100))
    action: Mapped[str] = mapped_column(String(100))
    payload: Mapped[dict] = mapped_column(JSONB)


class Mutation(Base):
    __tablename__ = "mutations"
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), primary_key=True)
    request_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    actor_id: Mapped[str] = mapped_column(String(100))
    request_hash: Mapped[str] = mapped_column(String(64))
    result: Mapped[dict] = mapped_column(JSONB)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class AutomationRun(Base):
    __tablename__ = "automation_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    requested_by: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(30), default="Queued", index=True)
    result: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (
        Index(
            "one_active_run_per_tenant",
            "tenant_id",
            unique=True,
            postgresql_where=text("status IN ('Queued','Running')"),
        ),
    )
