"""Replay documented sample values; invoice-line quantity is an explicit test assumption."""

from copy import deepcopy
import pytest
from test_domain import ADMIN, BUYER, APPROVER, FINANCE, issue
from lubriflow.domain import act, get, RuleError

pytest_plugins = ["test_domain"]


def test_sample_po_requires_finance(s):
    s["settings"].update(separation=True, financeThreshold=25000)
    po = act(
        s,
        "order",
        dict(
            supplier=s["suppliers"][0]["id"],
            lines=[dict(item=s["items"][0]["id"], qty=500, price=125)],
            tax=18,
        ),
        BUYER,
    )
    act(s, "submit", dict(id=po["id"]), BUYER)
    act(s, "approve", dict(id=po["id"]), APPROVER)
    assert get(s, "orders", po["id"])["status"] == "Pending approval"
    before = deepcopy(s)
    with pytest.raises(RuleError):
        act(s, "dispatch", dict(id=po["id"]), BUYER)
    assert s == before
    act(s, "approve", dict(id=po["id"]), FINANCE)
    assert get(s, "orders", po["id"])["status"] == "Approved"


def test_sample_rejection_and_invoice_quantity_assumptions(s):
    item = s["items"][1]["id"]
    initial = get(s, "items", item)["stock"]
    po = act(
        s,
        "order",
        dict(supplier=s["suppliers"][0]["id"], lines=[dict(item=item, qty=500, price=125)], tax=18),
        ADMIN,
    )
    issue(s, po["id"])
    # Current receiving represents accepted/rejected quantities as separate receipts.
    rejected = act(
        s, "receipt", dict(po=po["id"], batch="SAMPLE-LOT", lines=[dict(item=item, qty=10, price=125)]), ADMIN
    )
    act(s, "rejectReceipt", dict(id=rejected["id"], reason="Sample rejected 10 units"), ADMIN)
    accepted = act(
        s,
        "receipt",
        dict(po=po["id"], batch="SAMPLE-LOT", lines=[dict(item=item, qty=490, price=125)]),
        ADMIN,
    )
    act(s, "accept", dict(id=accepted["id"], reason="Sample accepted 490 units"), ADMIN)
    assert get(s, "items", item)["stock"] == initial + 490
    # Pack lacks invoice lines. These are two explicitly constructed alternatives.
    invoice = act(
        s,
        "invoice",
        dict(
            po=po["id"],
            number="SAMPLE-490",
            lines=[dict(item=item, qty=490, price=125)],
            tax=18,
            amount=72275,
        ),
        ADMIN,
    )
    act(s, "match", dict(id=invoice["id"]), ADMIN)
    act(s, "post", dict(id=invoice["id"]), ADMIN)
    assert get(s, "invoices", invoice["id"])["status"] == "Posted"
    other = act(
        s,
        "invoice",
        dict(
            po=po["id"], number="SAMPLE-10", lines=[dict(item=item, qty=10, price=125)], tax=18, amount=1475
        ),
        ADMIN,
    )
    act(s, "match", dict(id=other["id"]), ADMIN)
    before = deepcopy(s)
    with pytest.raises(RuleError):
        act(s, "post", dict(id=other["id"]), ADMIN)
    assert s == before
