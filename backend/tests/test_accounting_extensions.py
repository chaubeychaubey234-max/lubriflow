from copy import deepcopy
import pytest
from lubriflow.domain import empty, act, get, today, RuleError, balance, journal
from lubriflow.finance import reports, account_balances
from lubriflow.accounting import remaining_funds
from test_domain import ADMIN, order, issue, receipt, bill, post

pytest_plugins = ["test_domain"]


def customer_invoice(s, qty=2, price=25, currency=None, rate=None):
    c = act(s, "master", dict(collection="customers", name="Customer"), ADMIN)
    data = dict(customer=c["id"], lines=[dict(item=s["items"][0]["id"], qty=qty, price=price)])
    if currency:
        data.update(currency=currency, rate=rate)
    o = act(s, "salesOrder", data, ADMIN)
    delivery = act(s, "deliverSale", dict(order=o["id"], lines=data["lines"]), ADMIN)
    inv = act(
        s,
        "salesInvoice",
        dict(order=o["id"], number="INV-" + o["id"], lines=data["lines"], **({"rate": rate} if rate else {})),
        ADMIN,
    )
    return c, delivery, inv


def test_year_close_zero_profit_and_abnormal_balances(s):
    day = today()
    journal(
        s,
        "zero",
        "zero",
        [dict(account="Sales revenue", credit=100), dict(account="Purchases", debit=100)],
        day,
    )
    act(s, "closePeriod", dict(through=day), ADMIN)
    act(s, "closeYear", dict(end=day, shortYearReason="Synthetic short accounting year"), ADMIN)
    balances = account_balances(s, day)
    assert balances["Sales revenue"] == balances["Purchases"] == 0
    assert reports(s, day, day)["profitAndLoss"]["revenue"] == 100
    with pytest.raises(RuleError):
        act(s, "closeYear", dict(end=day, shortYearReason="Synthetic short accounting year"), ADMIN)
    s = empty()
    journal(
        s,
        "contra",
        "abnormal",
        [dict(account="Sales revenue", debit=20), dict(account="Purchases", credit=20)],
        day,
    )
    act(s, "closePeriod", dict(through=day), ADMIN)
    act(s, "closeYear", dict(end=day, shortYearReason="Synthetic short accounting year"), ADMIN)
    assert account_balances(s, day)["Sales revenue"] == 0


def test_daily_depreciation_catchup_repeat_and_disposal(s):
    a = act(s, "asset", dict(name="Machine", cost=3650, residual=0, lifeMonths=12, date="2025-01-01"), ADMIN)
    act(s, "depreciate", dict(periodEnd="2025-01-10"), ADMIN)
    assert get(s, "assets", a["id"])["accumulated"] == 100
    act(s, "depreciate", dict(periodEnd="2025-01-11"), ADMIN)
    assert get(s, "assets", a["id"])["accumulated"] == 110
    count = len(s["journal"])
    act(s, "depreciate", dict(periodEnd="2025-01-11"), ADMIN)
    assert len(s["journal"]) == count
    act(s, "disposeAsset", dict(id=a["id"], date="2025-01-20", proceeds=3000, reason="Sale"), ADMIN)
    assert get(s, "assets", a["id"])["accumulated"] == 200
    assert account_balances(s, today())["Asset disposal result"] == 450
    assert reports(s, "2025-01-01", today())["balanceDifference"] == 0


def test_voucher_dimensions_budget_schedule_and_reversal(s):
    p = act(s, "project", dict(name="Project"), ADMIN)
    vt = act(s, "voucherType", dict(name="Office payment", family="payment"), ADMIN)
    entries = [
        dict(account="LED-PUR", debit=30, project=p["id"], costCentre="CC-OPS"),
        dict(account="LED-BANK", credit=30),
    ]
    act(
        s,
        "financeBudget",
        dict(project=p["id"], account="LED-PUR", start="2025-01-01", end="2025-12-31", amount=100),
        ADMIN,
    )
    j = act(
        s,
        "accountingVoucher",
        dict(voucherType=vt["id"], entries=entries, reference="V1", reason="Expense", date="2025-01-01"),
        ADMIN,
    )
    act(s, "reverseVoucher", dict(id=j["id"], date="2025-01-02", reason="Correction"), ADMIN)
    sch = act(
        s,
        "financeSchedule",
        dict(
            name="Rent accrual", kind="accrual", start="2025-02-01", reverseDate="2025-03-01", entries=entries
        ),
        ADMIN,
    )
    act(s, "runFinanceSchedules", dict(through="2025-03-01"), ADMIN)
    assert len(get(s, "financeSchedules", sch["id"])["runs"]) == 2
    n = len(s["journal"])
    act(s, "runFinanceSchedules", dict(through="2025-03-01"), ADMIN)
    assert len(s["journal"]) == n
    r = reports(s, "2025-01-01", "2025-12-31")
    assert r["budgetPerformance"][0]["actual"] == 0
    assert r["cashFlow"]["netMovement"] == 0


def test_advance_multiple_allocations_and_refund_atomicity(s):
    po = order(s)
    issue(s, po)
    receipt(s, po)
    one = bill(s, po, qty=5, number="A")
    post(s, one)
    two = bill(s, po, qty=5, number="B")
    post(s, two)
    f = act(
        s,
        "partyFunds",
        dict(side="supplier", party=s["suppliers"][0]["id"], amount=100, reference="ADV"),
        ADMIN,
    )
    before = deepcopy(s)
    with pytest.raises(RuleError):
        act(
            s,
            "allocateFunds",
            dict(fund=f["id"], allocations=[dict(invoice=one, amount=10), dict(invoice=two, amount=90)]),
            ADMIN,
        )
    assert s == before
    act(
        s,
        "allocateFunds",
        dict(fund=f["id"], allocations=[dict(invoice=one, amount=26.25), dict(invoice=two, amount=26.25)]),
        ADMIN,
    )
    assert balance(s, get(s, "invoices", one)) == 0
    act(s, "refundFunds", dict(fund=f["id"], amount=47.5, reference="REF", reason="Unused advance"), ADMIN)
    assert remaining_funds(s, get(s, "partyFunds", f["id"])) == 0
    assert reports(s, "2000-01-01", today())["balanceDifference"] == 0


def test_foreign_invoice_settlement_realized_fx(s):
    c, delivery, inv = customer_invoice(s, currency="EUR", rate=4)
    assert account_balances(s, today())["Accounts receivable"] == 200
    f = act(
        s,
        "partyFunds",
        dict(side="customer", party=c["id"], currency="EUR", rate=4.2, amount=50, reference="FX"),
        ADMIN,
    )
    act(s, "allocateFunds", dict(fund=f["id"], allocations=[dict(invoice=inv["id"], amount=50)]), ADMIN)
    b = account_balances(s, today())
    assert b["Accounts receivable"] == 0 and b["Foreign exchange differences"] == -10
    with pytest.raises(RuleError):
        act(s, "settings", dict(currency="AED"), ADMIN)


def test_paid_customer_return_creates_refundable_credit(s):
    c, delivery, inv = customer_invoice(s)
    act(s, "customerPayment", dict(invoice=inv["id"], amount=50, reference="PAID"), ADMIN)
    m = get(s, "stockMoves", delivery["movements"][0])
    ret = act(
        s,
        "salesReturn",
        dict(
            delivery=delivery["id"],
            position=m["allocations"][0]["position"],
            item=s["items"][0]["id"],
            qty=1,
            reason="Returned",
        ),
        ADMIN,
    )
    credit = act(
        s, "customerCredit", dict(invoice=inv["id"], **{"return": ret["id"]}, qty=1, reason="Refund"), ADMIN
    )
    assert credit["appliedAmount"] == 0
    act(
        s,
        "refundFunds",
        dict(fund=credit["creditFund"], amount=25, reference="REF", reason="Returned paid item"),
        ADMIN,
    )
    assert account_balances(s, today())["Accounts receivable"] == 0


def test_perpetual_receipt_bill_delivery_cogs_and_production():
    s = empty()
    s["settings"]["separation"] = False
    act(s, "enablePerpetual", dict(date=today()), ADMIN)
    vendor = act(s, "supplier", dict(name="Vendor"), ADMIN)
    act(s, "approveSupplier", dict(id=vendor["id"], approved=True), ADMIN)
    act(s, "item", dict(name="Component", supplier=vendor["id"], unit="EA", price=5, stock=0), ADMIN)
    po = order(s)
    issue(s, po)
    receipt(s, po)
    assert account_balances(s, today())["Goods received not invoiced"] == -50
    inv = bill(s, po)
    post(s, inv)
    assert account_balances(s, today())["Goods received not invoiced"] == 0
    c, delivery, si = customer_invoice(s)
    b = account_balances(s, today())
    assert (
        b["Cost of sales"] == 10
        and b["Inventory asset"] == 40
        and b["Delivered goods awaiting invoicing"] == 0
    )
    act(s, "settings", dict(modules={"manufacturing": True}), ADMIN)
    output = act(s, "item", dict(name="Output", supplier=vendor["id"], unit="EA", price=10), ADMIN)
    bom = act(
        s,
        "bom",
        dict(name="Assembly", output=output["id"], lines=[dict(item=s["items"][0]["id"], qty=2, price=5)]),
        ADMIN,
    )
    p = act(s, "productionOrder", dict(bom=bom["id"], qty=1), ADMIN)
    act(s, "releaseProduction", dict(id=p["id"]), ADMIN)
    act(
        s,
        "consumeProduction",
        dict(id=p["id"], lines=[dict(item=s["items"][0]["id"], qty=2, price=5)]),
        ADMIN,
    )
    assert account_balances(s, today())["Work in progress"] == 10
    act(s, "finishProduction", dict(id=p["id"], conversionCost=3), ADMIN)
    b = account_balances(s, today())
    assert b["Work in progress"] == 0 and b["Inventory asset"] == 43
    assert reports(s, "2000-01-01", today())["balanceDifference"] == 0


def test_accounting_permission_and_period_lock(s):
    with pytest.raises(RuleError):
        act(s, "partyFunds", dict(), dict(id="viewer", role="viewer"))
    act(s, "closePeriod", dict(through=today()), ADMIN)
    with pytest.raises(RuleError):
        act(
            s,
            "partyFunds",
            dict(side="supplier", party=s["suppliers"][0]["id"], amount=10, reference="blocked"),
            ADMIN,
        )


def test_fx_rounding_clears_control_accounts_exactly(s):
    c, _, inv = customer_invoice(s, qty=3, price=0.01, currency="EUR", rate="1.333333")
    f = act(
        s,
        "partyFunds",
        dict(side="customer", party=c["id"], currency="EUR", rate="1.333333", amount=0.03, reference="ROUND"),
        ADMIN,
    )
    for _ in range(3):
        act(s, "allocateFunds", dict(fund=f["id"], allocations=[dict(invoice=inv["id"], amount=0.01)]), ADMIN)
    b = account_balances(s, today())
    assert b["Accounts receivable"] == b["Customer advances"] == 0


def test_revaluation_then_credit_and_settlement(s):
    c, delivery, inv = customer_invoice(s, currency="EUR", rate=4)
    act(s, "exchangeRate", dict(fromCurrency="EUR", rate=4.2, date=today()), ADMIN)
    reval = act(s, "revalueFX", dict(date=today()), ADMIN)
    assert reval["items"][0]["difference"] == 10
    m = get(s, "stockMoves", delivery["movements"][0])
    ret = act(
        s,
        "salesReturn",
        dict(
            delivery=delivery["id"],
            position=m["allocations"][0]["position"],
            item=s["items"][0]["id"],
            qty=1,
            reason="Return",
        ),
        ADMIN,
    )
    credit = act(
        s, "customerCredit", dict(invoice=inv["id"], **{"return": ret["id"]}, qty=1, reason="Credit"), ADMIN
    )
    assert credit["carryingBase"] == 105
    f = act(
        s,
        "partyFunds",
        dict(side="customer", party=c["id"], amount=25, currency="EUR", rate=4.1, reference="PAY"),
        ADMIN,
    )
    act(s, "allocateFunds", dict(fund=f["id"], allocations=[dict(invoice=inv["id"], amount=25)]), ADMIN)
    assert account_balances(s, today())["Accounts receivable"] == 0
    assert reports(s, "2000-01-01", today())["balanceDifference"] == 0


def test_on_account_credit_can_be_refunded(s):
    c = act(s, "master", dict(collection="customers", name="Credit customer"), ADMIN)
    f = act(
        s,
        "onAccountCredit",
        dict(
            side="customer",
            party=c["id"],
            amount=100,
            taxAmount=5,
            account="SYS-REV",
            reference="REBATE",
            reason="Approved rebate",
        ),
        ADMIN,
    )
    act(
        s,
        "refundFunds",
        dict(fund=f["id"], amount=105, reference="REBATE-REFUND", reason="Settlement"),
        ADMIN,
    )
    assert remaining_funds(s, get(s, "partyFunds", f["id"])) == 0
    assert account_balances(s, today())["Customer advances"] == 0


from test_api import client as api_client  # noqa: E402,F401


def test_postgres_schedule_worker_and_disabled_owner(api_client):  # noqa: F811
    from test_api import mutation
    from lubriflow.finance_scheduler import finance_once
    from lubriflow.db import Session
    from lubriflow.models import User

    payload = dict(
        name="Automated rent",
        kind="recurring",
        executionMode="automatic",
        months=1,
        start=today(),
        entries=[dict(account="LED-PUR", debit=12), dict(account="LED-BANK", credit=12)],
    )
    response = mutation(api_client, "financeSchedule", payload)
    assert response.status_code == 200, response.text
    sid = response.json()["result"]["id"]
    finance_once()
    finance_once()
    state = api_client.get("/api/workspace").json()["state"]
    sch = get(state, "financeSchedules", sid)
    assert sch["status"] == "Completed" and len(sch["runs"]) == 1
    payload["name"] = "Disabled owner"
    response = mutation(api_client, "financeSchedule", payload)
    sid2 = response.json()["result"]["id"]
    uid = response.json()["actor"]["id"]
    with Session.begin() as db:
        db.get(User, uid).active = False
    finance_once()
    with Session.begin() as db:
        db.get(User, uid).active = True
    state = api_client.get("/api/workspace").json()["state"]
    assert get(state, "financeSchedules", sid2)["status"] == "Attention"


def test_foreign_bank_revaluation_and_settlement(s):
    bank = act(s, "master", dict(collection="ledgers", name="Euro bank", type="bank"), ADMIN)
    act(s, "bankCurrency", dict(bankLedger=bank["id"], currency="EUR"), ADMIN)
    act(
        s,
        "currencyTransfer",
        dict(
            fromBank="LED-BANK",
            toBank=bank["id"],
            fromAmount=400,
            toAmount=100,
            toRate=4,
            reference="BUY-EUR",
        ),
        ADMIN,
    )
    act(s, "exchangeRate", dict(fromCurrency="EUR", rate=4.2, date=today()), ADMIN)
    act(s, "revalueFX", dict(date=today()), ADMIN)
    assert account_balances(s, today())["Euro bank"] == 420
    f = act(
        s,
        "partyFunds",
        dict(
            side="supplier",
            party=s["suppliers"][0]["id"],
            currency="EUR",
            rate=4.1,
            amount=100,
            bankLedger=bank["id"],
            reference="FC-PAY",
        ),
        ADMIN,
    )
    assert account_balances(s, today())["Euro bank"] == 0
    from lubriflow.foreign_banking import balance as bank_balance

    assert bank_balance(s, get(s, "ledgers", bank["id"]), today()) == (0, 0)
    assert reports(s, "2000-01-01", today())["balanceDifference"] == 0
    with pytest.raises(RuleError):
        act(
            s,
            "partyFunds",
            dict(
                side="supplier",
                party=s["suppliers"][0]["id"],
                currency="EUR",
                rate=4.1,
                amount=1,
                bankLedger=bank["id"],
                reference="OVERDRAW",
            ),
            ADMIN,
        )
    assert f["amount"] == 100


def test_regional_defaults_and_year_boundary():
    s = empty()
    act(s, "dubaiAccountingDefaults", {}, ADMIN)
    assert s["settings"]["currency"] == "AED" and s["settings"]["timezone"] == "Asia/Dubai"
    act(s, "closePeriod", dict(through="2025-06-30"), ADMIN)
    with pytest.raises(RuleError, match="year end"):
        act(s, "closeYear", dict(end="2025-06-30"), ADMIN)
    act(s, "closeYear", dict(end="2025-06-30", shortYearReason="Approved initial six-month year"), ADMIN)


def test_asset_report_is_historical(s):
    a = act(
        s,
        "asset",
        dict(name="Historical asset", cost=3650, residual=0, lifeMonths=12, date="2025-01-01"),
        ADMIN,
    )
    act(s, "depreciate", dict(periodEnd="2025-01-10"), ADMIN)
    act(s, "disposeAsset", dict(id=a["id"], date="2025-01-20", proceeds=3000, reason="Sale"), ADMIN)
    row = reports(s, "2025-01-01", "2025-01-10")["fixedAssets"][0]
    assert row["accumulated"] == 100 and row["netBookValue"] == 3550
    assert reports(s, "2025-01-01", "2025-01-20")["fixedAssets"][0]["netBookValue"] == 0


def test_service_invoice_credit_allocation_tax_and_reporting(s):
    inv = act(
        s,
        "accountingInvoice",
        dict(
            side="supplier",
            party=s["suppliers"][0]["id"],
            amount=100,
            taxAmount=5,
            account="LED-PUR",
            reference="SERVICE",
            reason="Professional services",
        ),
        ADMIN,
    )
    credit = act(
        s,
        "onAccountCredit",
        dict(
            side="supplier",
            party=s["suppliers"][0]["id"],
            amount=10,
            taxAmount=0.5,
            account="LED-PUR",
            reference="SERVICE-CR",
            reason="Discount",
        ),
        ADMIN,
    )
    act(
        s, "allocateFunds", dict(fund=credit["id"], allocations=[dict(invoice=inv["id"], amount=10.5)]), ADMIN
    )
    f = act(
        s,
        "partyFunds",
        dict(side="supplier", party=s["suppliers"][0]["id"], amount=94.5, reference="SERVICE-PAY"),
        ADMIN,
    )
    act(s, "allocateFunds", dict(fund=f["id"], allocations=[dict(invoice=inv["id"], amount=94.5)]), ADMIN)
    assert account_balances(s, today())["Accounts payable"] == 0
    row = reports(s, "2000-01-01", today())["payables"][0]
    assert row["balance"] == 0
    tax = act(s, "taxWorkpaper", dict(start=today(), end=today()), ADMIN)
    assert tax["inputTax"] == 4.5


def test_reserved_ledger_names_cannot_shadow_control_accounts(s):
    with pytest.raises(RuleError):
        act(s, "master", dict(collection="ledgers", name="Inventory asset", type="bank"), ADMIN)
