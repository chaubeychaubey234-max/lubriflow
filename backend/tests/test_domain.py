from copy import deepcopy
import pytest
from lubriflow.domain import empty, act, get, today, totals, balance, received, automation_plan, RuleError
from lubriflow.finance import reports

ADMIN = dict(id="admin", role="admin", name="Administrator")
BUYER = dict(id="buyer", role="buyer")
APPROVER = dict(id="approver", role="approver")
FINANCE = dict(id="finance", role="finance")


@pytest.fixture
def s():
    state = empty("Test Lubricants")
    state["settings"]["separation"] = False
    supplier = act(state, "supplier", dict(name="Vendor", email="vendor@example.test"), ADMIN)
    act(state, "approveSupplier", dict(id=supplier["id"], approved=True), ADMIN)
    for name, quality in [("Bottle", False), ("Base oil", True)]:
        act(
            state,
            "item",
            dict(
                name=name,
                supplier=supplier["id"],
                unit="pcs",
                price=5,
                stock=100,
                reorder=10,
                target=100,
                quality=quality,
            ),
            ADMIN,
        )
    return state


def order(s, qty=10, quality=False, price=5):
    item = s["items"][1 if quality else 0]["id"]
    return act(
        s,
        "order",
        dict(supplier=s["suppliers"][0]["id"], lines=[dict(item=item, qty=qty, price=price)], tax=5),
        ADMIN,
    )["id"]


def issue(s, po):
    act(s, "submit", dict(id=po), ADMIN)
    while get(s, "orders", po)["status"] == "Pending approval":
        act(s, "approve", dict(id=po), ADMIN)
    act(s, "dispatch", dict(id=po), ADMIN)


def receipt(s, po, qty=10):
    item = get(s, "orders", po)["lines"][0]["item"]
    return act(
        s, "receipt", dict(po=po, batch="BATCH-001", lines=[dict(item=item, qty=qty, price=5)]), ADMIN
    )["id"]


def bill(s, po, qty=10, number="INV-1", price=5):
    ls = [dict(item=get(s, "orders", po)["lines"][0]["item"], qty=qty, price=price)]
    return act(
        s,
        "invoice",
        dict(po=po, number=number, lines=ls, tax=5, amount=totals(dict(lines=ls, tax=5))["total"]),
        ADMIN,
    )["id"]


def post(s, invoice):
    act(s, "match", dict(id=invoice), ADMIN)
    act(s, "post", dict(id=invoice), ADMIN)


def test_complete_partial_receipt_invoice_payment_close(s):
    po = order(s)
    issue(s, po)
    receipt(s, po, 4)
    first = bill(s, po, 4)
    post(s, first)
    act(s, "pay", dict(id=first, amount=10, reference="BANK-1"), ADMIN)
    assert get(s, "invoices", first)["status"] == "Part paid"
    act(s, "pay", dict(id=first, amount=11, reference="BANK-2"), ADMIN)
    receipt(s, po, 6)
    second = bill(s, po, 6, "INV-2")
    post(s, second)
    act(s, "pay", dict(id=second, amount=31.5, reference="BANK-3"), ADMIN)
    act(s, "close", dict(id=po), ADMIN)
    assert get(s, "orders", po)["status"] == "Closed"
    assert reports(s, "2000-01-01", today())["balanceDifference"] == 0


def test_quality_hold_reject_and_release(s):
    po = order(s, quality=True)
    issue(s, po)
    r = receipt(s, po)
    assert s["items"][1]["stock"] == 100
    assert get(s, "receipts", r)["status"] == "Inspection hold"
    with pytest.raises(RuleError):
        receipt(s, po, 1)
    act(s, "rejectReceipt", dict(id=r, reason="Off specification"), ADMIN)
    r = receipt(s, po)
    act(s, "accept", dict(id=r, reason="COA accepted"), ADMIN)
    assert s["items"][1]["stock"] == 110
    with pytest.raises(RuleError):
        act(s, "accept", dict(id=r, reason="Again"), ADMIN)


def test_posted_return_requires_credit_and_replacement(s):
    po = order(s)
    issue(s, po)
    r = receipt(s, po)
    invoice = bill(s, po)
    post(s, invoice)
    data = dict(receipt=r, lines=[dict(item=s["items"][0]["id"], qty=2, price=5)], reason="Damaged")
    with pytest.raises(RuleError):
        act(s, "return", data, ADMIN)
    act(s, "credit", dict(invoice=invoice, number="CR-1", lines=data["lines"], reason="Damaged"), ADMIN)
    assert balance(s, get(s, "invoices", invoice)) == 42
    act(s, "return", data, ADMIN)
    assert received(s, po, s["items"][0]["id"]) == 8
    receipt(s, po, 2)
    post(s, bill(s, po, 2, "REPLACEMENT"))


def test_stale_match_is_rechecked_at_posting(s):
    po = order(s)
    issue(s, po)
    receipt(s, po, 5)
    a, b = bill(s, po, 5), bill(s, po, 5, "INV-2")
    act(s, "match", dict(id=a), ADMIN)
    act(s, "match", dict(id=b), ADMIN)
    act(s, "post", dict(id=a), ADMIN)
    before = deepcopy(s)
    with pytest.raises(RuleError):
        act(s, "post", dict(id=b), ADMIN)
    assert s == before


def test_separate_approval_stages(s):
    s["settings"].update(separation=True, financeThreshold=50)
    po = act(
        s,
        "order",
        dict(supplier=s["suppliers"][0]["id"], lines=[dict(item=s["items"][0]["id"], qty=10, price=5)]),
        BUYER,
    )["id"]
    act(s, "submit", dict(id=po), BUYER)
    with pytest.raises(RuleError):
        act(s, "approve", dict(id=po), BUYER)
    act(s, "approve", dict(id=po), APPROVER)
    assert get(s, "orders", po)["status"] == "Pending approval"
    with pytest.raises(RuleError):
        act(s, "approve", dict(id=po), APPROVER)
    act(s, "approve", dict(id=po), FINANCE)
    assert get(s, "orders", po)["status"] == "Approved"


def test_budget_and_amendment_invalidate_approvals(s):
    po = order(s)
    act(s, "submit", dict(id=po), ADMIN)
    s["settings"]["budgetMonthly"] = 0
    with pytest.raises(RuleError):
        act(s, "approve", dict(id=po), ADMIN)
    s["settings"]["budgetMonthly"] = 1000
    act(s, "approve", dict(id=po), ADMIN)
    old = deepcopy(get(s, "orders", po))
    act(s, "editOrder", dict(**old, reason="Changed production requirement"), ADMIN)
    current = get(s, "orders", po)
    assert current["revision"] == 2 and current["status"] == "Draft" and current["approvals"] == []
    assert len(current["history"]) == 1


def test_duplicate_reference_overbilling_and_void(s):
    po = order(s)
    issue(s, po)
    first = bill(s, po, 6)
    with pytest.raises(RuleError):
        bill(s, po, 5, "INV-2")
    act(s, "voidInvoice", dict(id=first, reason="Cancelled by supplier"), ADMIN)
    bill(s, po, 10, "NEW")
    with pytest.raises(RuleError, match="Duplicate"):
        bill(s, po, 1, "inv-1")


def test_transfer_and_reversal(s):
    wh = act(s, "master", dict(collection="warehouses", name="Second warehouse"), ADMIN)["id"]
    item = s["items"][0]["id"]
    act(
        s,
        "stockTransfer",
        dict(item=item, qty=10, fromWarehouse="WH-MAIN", toWarehouse=wh, reason="Move"),
        ADMIN,
    )
    assert s["items"][0]["stock"] == 100 and s["items"][0]["stockByWarehouse"][wh] == 10
    po = order(s)
    issue(s, po)
    receipt(s, po)
    invoice = bill(s, po)
    post(s, invoice)
    payment = act(s, "pay", dict(id=invoice, amount=52.5, reference="PAY"), ADMIN)["id"]
    act(s, "reversePayment", dict(id=payment, reason="Rejected by bank"), ADMIN)
    assert balance(s, get(s, "invoices", invoice)) == 52.5
    assert reports(s, "2000-01-01", today())["balanceDifference"] == 0


def test_locked_period_and_expired_goods_are_atomic(s):
    po = order(s)
    issue(s, po)
    before = deepcopy(s)
    with pytest.raises(RuleError):
        act(
            s,
            "receipt",
            dict(po=po, expiry=today(), lines=[dict(item=s["items"][0]["id"], qty=1, price=5)]),
            ADMIN,
        )
    assert s == before
    s["settings"]["lockedThrough"] = today()
    with pytest.raises(RuleError, match="locked"):
        receipt(s, po)


def test_automation_scope_and_manual_mode(s):
    with pytest.raises(RuleError):
        automation_plan(s)
    s["settings"].update(mode="automatic", autoApprove=True, autoReorder=True, limit=100, financeThreshold=80)
    small, large = order(s), order(s, qty=18)
    assert ("approve", {"id": small}) in automation_plan(s)
    assert ("approve", {"id": large}) not in automation_plan(s)
    for action, data in automation_plan(s):
        act(s, action, data, dict(id="automation", role="system"))
    assert get(s, "orders", small)["status"] == "Approved"
    assert not s["payments"]
    with pytest.raises(RuleError):
        act(s, "post", dict(id="anything"), dict(id="automation", role="system"))


def test_financial_journal_and_reversal(s):
    capital = act(s, "account", dict(name="Owner capital", type="equity"), ADMIN)["id"]
    j = act(
        s,
        "journal",
        dict(
            reason="Opening funds",
            entries=[dict(account="LED-BANK", debit=1000), dict(account=capital, credit=1000)],
        ),
        ADMIN,
    )
    assert reports(s, "2000-01-01", today())["balanceSheet"]["assets"] == 1000
    act(s, "reverseJournal", dict(id=j["id"], reason="Correction"), ADMIN)
    assert reports(s, "2000-01-01", today())["balanceSheet"]["assets"] == 0
    with pytest.raises(RuleError):
        act(
            s,
            "journal",
            dict(
                reason="Unbalanced",
                entries=[dict(account="LED-BANK", debit=100), dict(account=capital, credit=90)],
            ),
            ADMIN,
        )


@pytest.mark.parametrize(
    "role,action",
    [
        ("viewer", "order"),
        ("stores", "pay"),
        ("buyer", "approve"),
        ("supplier", "invoice"),
        ("quality", "settings"),
    ],
)
def test_role_boundaries(s, role, action):
    before = deepcopy(s)
    with pytest.raises(RuleError, match="role"):
        act(s, action, {}, dict(id="other", role=role))
    assert s == before
