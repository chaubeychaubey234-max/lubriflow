from copy import deepcopy
import pytest
from test_domain import ADMIN, order, issue, receipt, bill, post

from lubriflow.domain import empty, act, get, today, automation_plan, procurement_insights, RuleError, totals
from lubriflow.backup import validate
from lubriflow.finance import reports

pytest_plugins = ["test_domain"]


def test_agreement_prefill_and_overlap(s):
    from lubriflow.domain import suggest

    item, supplier = s["items"][0]["id"], s["suppliers"][0]["id"]
    act(
        s,
        "priceAgreement",
        dict(
            item=item,
            supplier=supplier,
            price=3,
            discount=10,
            taxRate=5,
            validFrom=today(),
            validUntil=today(),
            reference="Contract",
        ),
        ADMIN,
    )
    assert suggest(s, supplier, item)["price"] == 3
    with pytest.raises(RuleError):
        act(
            s,
            "priceAgreement",
            dict(
                item=item,
                supplier=supplier,
                price=4,
                validFrom=today(),
                validUntil=today(),
                reference="Overlap",
            ),
            ADMIN,
        )


def test_industry_neutral_company_configuration_and_inspection(s):
    state = empty("Global Trading")
    assert state["settings"]["country"] == ""
    assert state["settings"]["defaultTax"] == 0
    assert state["settings"]["modules"]["manufacturing"] is False
    act(
        state,
        "settings",
        dict(
            currency="EUR",
            timezone="Europe/Paris",
            fiscalYearStart="04-01",
            taxRegime="eu-vat",
            modules={"sales": True, "manufacturing": True},
        ),
        ADMIN,
    )
    assert state["settings"]["currency"] == "EUR"
    assert state["settings"]["modules"]["manufacturing"] is True
    with pytest.raises(RuleError):
        act(state, "settings", dict(currency="EURO"), ADMIN)


def test_configurable_general_masters(s):
    branch = act(s, "master", dict(collection="branches", name="North branch"), ADMIN)
    tax = act(s, "master", dict(collection="taxProfiles", name="Reduced rate", rate=7.5), ADMIN)
    customer = act(
        s,
        "master",
        dict(collection="customers", name="Customer One", creditDays=30, creditLimit=25000),
        ADMIN,
    )
    bin_record = act(s, "master", dict(collection="bins", name="A-01", warehouse="WH-MAIN"), ADMIN)
    assert branch["name"] == "North branch"
    assert tax["rate"] == 7.5
    assert customer["creditLimit"] == 25000
    assert bin_record["warehouse"] == "WH-MAIN"


def test_sales_delivery_invoice_and_receivable_payment(s):
    customer = act(s, "master", dict(collection="customers", name="Sales customer", creditDays=30), ADMIN)
    item = s["items"][0]["id"]
    order = act(s, "salesOrder", dict(customer=customer["id"], lines=[dict(item=item, qty=4, price=20)], tax=5), ADMIN)
    delivery = act(s, "deliverSale", dict(order=order["id"], lines=[dict(item=item, qty=4, price=20)]), ADMIN)
    invoice = act(s, "salesInvoice", dict(order=order["id"], number="SALE-1", lines=delivery["lines"], tax=5), ADMIN)
    payment = act(s, "customerPayment", dict(invoice=invoice["id"], amount=84, reference="RECEIPT-1"), ADMIN)
    assert payment["status"] == "Recorded"
    assert reports(s, "2000-01-01", today())["balanceDifference"] == 0


def test_treasury_asset_tax_and_financial_close_controls(s):
    customer = act(s, "master", dict(collection="customers", name="Treasury customer"), ADMIN)
    item = s["items"][0]["id"]
    order = act(s, "salesOrder", dict(customer=customer["id"], lines=[dict(item=item, qty=2, price=25)]), ADMIN)
    delivery = act(s, "deliverSale", dict(order=order["id"], lines=[dict(item=item, qty=2, price=25)]), ADMIN)
    invoice = act(s, "salesInvoice", dict(order=order["id"], number="TREASURY-1", lines=delivery["lines"]), ADMIN)
    receipt = act(s, "customerPayment", dict(invoice=invoice["id"], amount=50, reference="BANK-RECEIPT"), ADMIN)
    statement = act(s, "bankStatement", dict(reference="STMT-1", amount=50, direction="debit"), ADMIN)
    reconciled = act(s, "reconcileBank", dict(statement=statement["id"], collection="customerPayments", transaction=receipt["id"]), ADMIN)
    assert reconciled["status"] == "Reconciled"
    asset = act(s, "asset", dict(name="Forklift", cost=1200, residual=0, lifeMonths=12), ADMIN)
    run = act(s, "depreciate", dict(periodEnd=today()), ADMIN)
    assert asset["id"] in {charge["asset"] for charge in run["charges"]}
    workpaper = act(s, "taxWorkpaper", dict(start=today(), end=today()), ADMIN)
    assert workpaper["outputTax"] == 0
    fx = act(s, "exchangeRate", dict(fromCurrency="EUR", toCurrency="USD", rate=1.08), ADMIN)
    assert fx["rate"] == 1.08
    act(s, "closePeriod", dict(through=today()), ADMIN)
    closing = act(s, "closeYear", dict(end=today(),shortYearReason="Synthetic short accounting year"), ADMIN)
    assert closing["reference"] == "YEAR-" + today()
    assert reports(s, "2000-01-01", today())["balanceDifference"] == 0


def test_reorder_with_prior_order_rate_does_not_duplicate_item_keys(s):
    po = order(s)
    issue(s, po)
    receipt(s, po)
    s["items"][0]["stock"] = 0
    s["items"][0]["stockByWarehouse"]["WH-MAIN"] = 0
    s["settings"].update(mode="automatic", autoReorder=True)
    plan = automation_plan(s)
    assert plan and plan[0][0] == "requisition"
    act(s, *plan[0], dict(id="automation", role="system"))
    assert automation_plan(s) == []


def test_procurement_insights_compare_quotes_and_score_suppliers(s):
    item, supplier = s["items"][0]["id"], s["suppliers"][0]["id"]
    act(s, "quote", dict(supplier=supplier, valid=today(), leadDays=4, lines=[dict(item=item, qty=5, price=4)]), ADMIN)
    insights = procurement_insights(s)
    assert insights["quoteComparisons"][0]["offers"][0]["supplier"] == supplier
    assert insights["supplierScorecards"][0]["supplier"] == supplier


def test_preclose_and_overreceipt(s):
    po = order(s)
    issue(s, po)
    receipt(s, po, 4)
    act(
        s,
        "preclose",
        dict(id=po, lines=[dict(item=s["items"][0]["id"], qty=6, price=5)], reason="Demand reduced"),
        ADMIN,
    )
    assert get(s, "orders", po)["status"] == "Received"
    with pytest.raises(RuleError):
        receipt(s, po, 1)


def test_draft_permissions_and_failed_mutation_rollback(s):
    actor = dict(id="buyer", role="buyer")
    act(s, "saveDraft", dict(kind="order", values={"note": "Draft"}), actor)
    assert s["drafts"][0]["actor"] == "buyer"
    with pytest.raises(RuleError):
        act(s, "saveDraft", dict(kind="journal", values={}), actor)
    before = deepcopy(s)
    with pytest.raises(RuleError):
        act(
            s,
            "stockTransfer",
            dict(
                item=s["items"][0]["id"], qty=5, fromWarehouse="WH-MAIN", toWarehouse="MISSING", reason="Move"
            ),
            ADMIN,
        )
    assert s == before


def test_supplier_submission_review_never_posts(s):
    po = order(s)
    issue(s, po)
    invoice = bill(s, po)
    s["portalSubmissions"] = [
        dict(
            id="SUB-1",
            po=po,
            supplier=s["suppliers"][0]["id"],
            number="INV-1",
            amount=52.5,
            status="Awaiting finance review",
        )
    ]
    act(s, "linkSubmission", dict(id="SUB-1", invoice=invoice), ADMIN)
    assert s["portalSubmissions"][0]["status"] == "Entered for matching"
    assert get(s, "invoices", invoice)["status"] == "Pending match"


def test_restore_rejects_negative_balanced_journal(s):
    s["journal"] = [
        dict(id="JV-1", date=today(), entries=[dict(account="A", debit=-10), dict(account="B", credit=-10)])
    ]
    with pytest.raises(RuleError, match="Negative"):
        validate(s)


def test_discounted_line_taxes_use_decimal_rounding(s):
    assert totals(dict(lines=[dict(qty=3, price=0.1, discount=0, taxRate=5)], tax=0))["total"] == 0.32
    po = act(
        s,
        "order",
        dict(
            supplier=s["suppliers"][0]["id"],
            lines=[dict(item=s["items"][0]["id"], qty=10, price=5, discount=10, taxRate=5)],
            tax=5,
        ),
        ADMIN,
    )["id"]
    issue(s, po)
    receipt(s, po)
    invoice = act(
        s,
        "invoice",
        dict(
            po=po,
            number="DISCOUNT",
            lines=[dict(item=s["items"][0]["id"], qty=10, price=5, discount=10, taxRate=5)],
            amount=47.25,
            tax=5,
        ),
        ADMIN,
    )["id"]
    post(s, invoice)
    assert get(s, "invoices", invoice)["status"] == "Posted"
