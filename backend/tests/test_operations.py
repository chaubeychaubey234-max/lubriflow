from copy import deepcopy
import pytest
from test_domain import ADMIN, order, issue, receipt
from test_api import mutation, setup_order
from lubriflow.domain import act, get, RuleError, today
from lubriflow.inventory import ensure_positions, inventory_report
from lubriflow.sales import receivable

pytest_plugins = ["test_domain", "test_api"]


def prepare(s):
    for item in s["items"]:
        ensure_positions(s, item)
    return s["items"][0]["id"]


def customer(s):
    return act(s, "master", dict(collection="customers", name="Industrial customer", creditDays=30), ADMIN)["id"]


def test_bin_transfer_conserves_value_and_rejects_wrong_warehouse(s):
    item = prepare(s)
    bin_id = act(s, "master", dict(collection="bins", name="A1", warehouse="WH-MAIN"), ADMIN)["id"]
    before = inventory_report(s)["value"]
    act(s, "relocateStock", dict(item=item, qty=20, fromWarehouse="WH-MAIN", toWarehouse="WH-MAIN", toBin=bin_id, reason="Put away"), ADMIN)
    pos = next(p for p in s["stockPositions"] if p["bin"] == bin_id)
    assert pos["qty"] == 20 and pos["value"] == 100
    assert inventory_report(s)["value"] == before
    other = act(s, "master", dict(collection="warehouses", name="Other"), ADMIN)["id"]
    previous = deepcopy(s)
    with pytest.raises(RuleError, match="different warehouse"):
        act(s, "stockTransfer", dict(item=item, qty=1, fromWarehouse="WH-MAIN", toWarehouse=other, toBin=bin_id, reason="Bad bin"), ADMIN)
    assert s == previous


def test_reservations_prevent_overcommit_and_only_owner_can_consume(s):
    item = prepare(s)
    c = customer(s)
    order1 = act(s, "salesOrder", dict(customer=c, lines=[dict(item=item, qty=80, price=10)]), ADMIN)
    pos = next(p for p in s["stockPositions"] if p["item"] == item)
    reservation = act(s, "reserveStock", dict(position=pos["id"], source=order1["id"], qty=80), ADMIN)
    before = deepcopy(s)
    with pytest.raises(RuleError, match="unreserved"):
        act(s, "stockIssue", dict(item=item, qty=21, reason="Cannot steal allocated stock"), ADMIN)
    assert s == before
    order2 = act(s, "salesOrder", dict(customer=c, lines=[dict(item=item, qty=5, price=10)]), ADMIN)
    with pytest.raises(RuleError, match="different source"):
        act(s, "deliverSale", dict(order=order2["id"], lines=[dict(item=item, qty=5, reservation=reservation["id"])]), ADMIN)
    act(s, "deliverSale", dict(order=order1["id"], lines=[dict(item=item, qty=80, reservation=reservation["id"])]), ADMIN)
    assert get(s, "reservations", reservation["id"])["status"] == "Consumed"
    assert get(s, "items", item)["stock"] == 20


def test_stock_count_requires_fresh_snapshot_and_second_approver(s):
    item = prepare(s)
    pos = next(p for p in s["stockPositions"] if p["item"] == item)
    count = act(s, "stockCount", dict(position=pos["id"], counted=98, reason="Cycle count"), ADMIN)
    act(s, "stockIssue", dict(item=item, qty=1, reason="Dispatch"), ADMIN)
    with pytest.raises(RuleError, match="stale"):
        act(s, "approveStockCount", dict(id=count["id"]), ADMIN)
    s["settings"]["separation"] = True
    count = act(s, "stockCount", dict(position=pos["id"], counted=97, reason="Recount"), ADMIN)
    with pytest.raises(RuleError, match="different user"):
        act(s, "approveStockCount", dict(id=count["id"]), ADMIN)
    act(s, "approveStockCount", dict(id=count["id"]), dict(id="checker", role="approver"))
    assert get(s, "items", item)["stock"] == 97
    with pytest.raises(RuleError):
        act(s, "approveStockCount", dict(id=count["id"]), ADMIN)


def test_landed_cost_allocates_once_and_blocks_after_consumption(s):
    prepare(s)
    po = order(s)
    issue(s, po)
    grn = receipt(s, po)
    before = inventory_report(s)["value"]
    cost = act(s, "landedCost", dict(receipt=grn, amount=12.35, reference="FREIGHT-1"), ADMIN)
    assert sum(a["allocatedCost"] for a in cost["allocations"]) == 12.35
    assert inventory_report(s)["value"] == before + 12.35
    with pytest.raises(RuleError):
        act(s, "landedCost", dict(receipt=grn, amount=12.35, reference="FREIGHT-1"), ADMIN)
    act(s, "stockIssue", dict(item=s["items"][0]["id"], lot="BATCH-001", qty=1, reason="Use receipt"), ADMIN)
    with pytest.raises(RuleError, match="issued"):
        act(s, "landedCost", dict(receipt=grn, amount=2, reference="LATE-FREIGHT"), ADMIN)


def test_serial_receipt_uniqueness_and_locked_stock_period(s):
    item = act(s, "item", dict(name="Machine", unit="ea", supplier=s["suppliers"][0]["id"], price=100, target=10), ADMIN)["id"]
    act(s, "itemTracking", dict(item=item, tracking="serial", barcode="MACHINE-001"), ADMIN)
    po = act(s, "order", dict(supplier=s["suppliers"][0]["id"], lines=[dict(item=item, qty=2, price=100)]), ADMIN)["id"]
    issue(s, po)
    act(s, "receipt", dict(po=po, lines=[dict(item=item, qty=1, serial="SER-1")]), ADMIN)
    before = deepcopy(s)
    with pytest.raises(RuleError, match="already in stock"):
        act(s, "receipt", dict(po=po, lines=[dict(item=item, qty=1, serial="SER-1")]), ADMIN)
    assert s == before
    s["settings"]["lockedThrough"] = today()
    with pytest.raises(RuleError, match="locked"):
        act(s, "stockIssue", dict(item=item, serial="SER-1", qty=1, reason="Ship"), ADMIN)


def test_quarantine_opening_value_and_bin_history_controls(s):
    item = prepare(s)
    pos = next(p for p in s["stockPositions"] if p["item"] == item)
    act(s, "confirmOpeningCost", dict(position=pos["id"], value=625, reason="Signed opening valuation"), ADMIN)
    assert inventory_report(s)["value"] == 1125
    with pytest.raises(RuleError):
        act(s, "confirmOpeningCost", dict(position=pos["id"], value=1, reason="Do not rewrite"), ADMIN)
    act(s, "stockDisposition", dict(position=pos["id"], status="Quarantined", reason="Recall investigation"), dict(id="quality-user", role="quality"))
    assert next(p for p in inventory_report(s)["positions"] if p["item"] == item)["available"] == 0
    with pytest.raises(RuleError, match="unreserved"):
        act(s, "stockIssue", dict(item=item, qty=1, reason="Blocked issue"), ADMIN)
    act(s, "stockDisposition", dict(position=pos["id"], status="Available", reason="Inspection passed"), ADMIN)
    bin_record = act(s, "master", dict(collection="bins", name="Controlled", warehouse="WH-MAIN"), ADMIN)
    act(s, "relocateStock", dict(item=item, qty=5, toBin=bin_record["id"], reason="Put away"), ADMIN)
    other = act(s, "master", dict(collection="warehouses", name="Branch"), ADMIN)
    with pytest.raises(RuleError, match="used bin"):
        act(s, "master", dict(collection="bins", id=bin_record["id"], name="Controlled", warehouse=other["id"]), ADMIN)


def test_sales_quote_delivery_return_credit_and_payment(s):
    item = prepare(s)
    c = customer(s)
    quote = act(s, "salesQuote", dict(customer=c, validUntil=today(), lines=[dict(item=item, qty=4, price=20)], tax=5), ADMIN)
    sales = act(s, "convertSalesQuote", dict(id=quote["id"]), ADMIN)
    with pytest.raises(RuleError):
        act(s, "convertSalesQuote", dict(id=quote["id"]), ADMIN)
    delivery = act(s, "deliverSale", dict(order=sales["id"], lines=[dict(item=item, qty=4, price=999)]), ADMIN)
    assert delivery["lines"][0]["price"] == 20 and delivery["cost"] == 20
    invoice = act(s, "salesInvoice", dict(order=sales["id"], number="SALE-01", lines=[dict(item=item, qty=4, price=999)]), ADMIN)
    assert receivable(s, invoice) == 84
    movement = get(s, "stockMoves", delivery["movements"][0])
    returned = act(s, "salesReturn", dict(delivery=delivery["id"], item=item, position=movement["allocations"][0]["position"], qty=1, reason="Inspected unopened return"), ADMIN)
    act(s, "customerCredit", {"invoice": invoice["id"], "return": returned["id"], "qty": 1, "reason": "Returned goods"}, ADMIN)
    assert receivable(s, invoice) == 63
    act(s, "customerPayment", dict(invoice=invoice["id"], amount=63, reference="BANK-RECEIPT"), ADMIN)
    assert receivable(s, invoice) == 0
    with pytest.raises(RuleError):
        act(s, "customerPayment", dict(invoice=invoice["id"], amount=1, reference="EXCESS"), ADMIN)


def test_production_consumption_output_cost_genealogy_and_rollback(s):
    prepare(s)
    s["settings"]["modules"]["manufacturing"] = True
    parts = s["items"][:2]
    output = act(s, "item", dict(name="Finished assembly", unit="ea", supplier=s["suppliers"][0]["id"], target=10, price=0), ADMIN)["id"]
    act(s, "itemTracking", dict(item=output, tracking="lot", barcode="FIN-1"), ADMIN)
    bom = act(s, "bom", dict(name="Assembly v1", output=output, outputQty=1, lines=[dict(item=parts[0]["id"], qty=2), dict(item=parts[1]["id"], qty=3)]), ADMIN)
    production = act(s, "productionOrder", dict(bom=bom["id"], qty=4), ADMIN)
    act(s, "releaseProduction", dict(id=production["id"]), ADMIN)
    component_position = next(p for p in s["stockPositions"] if p["item"] == parts[0]["id"])
    reservation = act(s, "reserveStock", dict(position=component_position["id"], source=production["id"], sourceKind="productionOrders", qty=8), dict(id="planner", role="production"))
    required = deepcopy(production["lines"])
    required[0]["reservation"] = reservation["id"]
    with pytest.raises(RuleError, match="Consume all"):
        act(s, "finishProduction", dict(id=production["id"], outputQty=4, lot="OUTPUT-1"), ADMIN)
    before = deepcopy(s)
    with pytest.raises(RuleError):
        act(s, "consumeProduction", dict(id=production["id"], lines=[dict(item=parts[0]["id"], qty=8), dict(item=parts[1]["id"], qty=999)]), ADMIN)
    assert s == before
    act(s, "consumeProduction", dict(id=production["id"], lines=required), ADMIN)
    assert get(s, "reservations", reservation["id"])["status"] == "Consumed"
    completed = act(s, "finishProduction", dict(id=production["id"], outputQty=4, conversionCost=20, lot="OUTPUT-1"), ADMIN)
    assert completed["materialCost"] == 100 and completed["totalCost"] == 120
    assert get(s, "items", output)["stock"] == 4
    assert get(s, "stockMoves", completed["outputMovement"])["allocations"][0]["lot"] == "OUTPUT-1"
    assert len(completed["consumption"]) == 2
    with pytest.raises(RuleError):
        act(s, "finishProduction", dict(id=production["id"], outputQty=4, lot="DUPLICATE"), ADMIN)


def test_real_database_positions_barcode_and_production_persist(client):
    supplier, item, po = setup_order(client)
    assert mutation(client, "itemTracking", dict(item=item, tracking="lot", barcode="SCAN-01")).status_code == 200
    for action in ("submit", "approve", "dispatch"):
        assert mutation(client, action, dict(id=po)).status_code == 200
    response = mutation(client, "receipt", dict(po=po, lines=[dict(item=item, qty=10, lot="INPUT-LOT")]))
    assert response.status_code == 200, response.text
    barcode = client.get("/api/barcode?code=SCAN-01").json()
    assert barcode["positions"][0]["qty"] == 10
    assert client.get("/api/inventory-report").json()["value"] == 50
    trace = client.get("/api/stock-trace", params=dict(item=item, lot="INPUT-LOT")).json()
    assert trace["movements"][0]["reference"] == response.json()["result"]["id"]
    assert client.get("/api/barcode?code=NOT-FOUND").status_code == 400
    assert mutation(client, "settings", dict(modules=dict(manufacturing=True))).status_code == 200
    output = mutation(client, "item", dict(name="Finished item", unit="ea", supplier=supplier, price=0, target=10)).json()["result"]["id"]
    bom = mutation(client, "bom", dict(name="Build v1", output=output, outputQty=1, lines=[dict(item=item, qty=2)])).json()["result"]["id"]
    production = mutation(client, "productionOrder", dict(bom=bom, qty=2)).json()["result"]["id"]
    assert mutation(client, "releaseProduction", dict(id=production)).status_code == 200
    response = mutation(client, "consumeProduction", dict(id=production, lines=[dict(item=item, qty=4, lot="INPUT-LOT")]))
    assert response.status_code == 200, response.text
    response = mutation(client, "finishProduction", dict(id=production, outputQty=2, conversionCost=5))
    assert response.status_code == 200, response.text
    assert response.json()["result"]["totalCost"] == 25
    assert len(client.get("/api/stock-trace", params=dict(item=output)).json()["genealogy"]) == 2


def test_expired_stock_block_and_fefo_selection(s):
    from datetime import timedelta, date
    from lubriflow.inventory import move
    item = prepare(s)
    soon = (date.fromisoformat(today()) + timedelta(days=2)).isoformat()
    later = (date.fromisoformat(today()) + timedelta(days=10)).isoformat()
    move(s, ADMIN, item, 2, "TEST-SOON", "Receipt", lot="SOON", expiry=soon, unit_cost=7)
    move(s, ADMIN, item, 2, "TEST-LATER", "Receipt", lot="LATER", expiry=later, unit_cost=9)
    act(s, "stockIssue", dict(item=item, qty=3, reason="FEFO issue"), ADMIN)
    allocations = s["stockMoves"][0]["allocations"]
    assert [(a["lot"], a["qty"]) for a in allocations] == [("SOON", 2), ("LATER", 1)]
    assert s["stockMoves"][0]["value"] == 23
    expired = next(p for p in s["stockPositions"] if p["lot"] == "LATER")
    expired["expiry"] = "2000-01-01"
    before = deepcopy(s)
    with pytest.raises(RuleError, match="unexpired"):
        act(s, "stockIssue", dict(item=item, lot="LATER", qty=1, reason="Cannot ship expired"), ADMIN)
    assert s == before
