from copy import deepcopy
import pytest
from test_domain import ADMIN
from lubriflow.domain import act, get, RuleError, today
from lubriflow.finance import account_balances

pytest_plugins = ["test_domain"]


def test_partial_output_costs_and_final_completion(s):
    s["settings"]["modules"]["manufacturing"] = True
    part = s["items"][0]["id"]
    output = act(
        s, "item", dict(name="Assembly", supplier=s["suppliers"][0]["id"], unit="EA", price=0), ADMIN
    )
    bom = act(s, "bom", dict(name="Assembly BOM", output=output["id"], lines=[dict(item=part, qty=2)]), ADMIN)
    production = act(s, "productionOrder", dict(bom=bom["id"], qty=10), ADMIN)
    pid = production["id"]
    act(s, "releaseProduction", dict(id=pid), ADMIN)
    act(s, "consumeProduction", dict(id=pid, lines=[dict(item=part, qty=12)]), ADMIN)
    before = deepcopy(s)
    with pytest.raises(RuleError, match="proportion"):
        act(s, "finishProduction", dict(id=pid, outputQty=7, partial=True), ADMIN)
    assert s == before
    first = act(s, "finishProduction", dict(id=pid, outputQty=6, partial=True, conversionCost=3), ADMIN)
    assert first["status"] == "In progress" and "completedDate" not in first
    assert first["outputs"][0]["materialCost"] == 60 and first["totalCost"] == 63
    before = deepcopy(s)
    with pytest.raises(RuleError):
        act(s, "finishProduction", dict(id=pid, outputQty=1, partial=True), ADMIN)
    assert s == before
    act(s, "consumeProduction", dict(id=pid, lines=[dict(item=part, qty=8)]), ADMIN)
    final = act(s, "finishProduction", dict(id=pid, outputQty=4, conversionCost=2), ADMIN)
    assert final["status"] == "Completed" and final["outputQty"] == 10
    assert final["totalCost"] == 105 and final["conversionCost"] == 5
    assert final["outputs"][1]["materialCost"] == 40
    assert len({o["movement"] for o in final["outputs"]}) == 2
    assert get(s, "items", output["id"])["stock"] == 10
    with pytest.raises(RuleError):
        act(s, "finishProduction", dict(id=pid, outputQty=1), ADMIN)


def test_partial_output_perpetual_conversion_is_not_reposted():
    from lubriflow.domain import empty

    s = empty("Partial accounting")
    s["settings"]["separation"] = False
    act(s, "settings", dict(modules={"manufacturing": True}), ADMIN)
    act(s, "enablePerpetual", dict(date=today()), ADMIN)
    vendor = act(s, "supplier", dict(name="Vendor", email="vendor@example.test"), ADMIN)
    part = act(s, "item", dict(name="Part", supplier=vendor["id"], unit="EA", price=5), ADMIN)
    output = act(s, "item", dict(name="Output", supplier=vendor["id"], unit="EA", price=0), ADMIN)
    from test_domain import order, issue, receipt

    act(s, "approveSupplier", dict(id=vendor["id"], approved=True), ADMIN)
    po = order(s, qty=20)
    issue(s, po)
    receipt(s, po, qty=20)
    bom = act(s, "bom", dict(name="BOM", output=output["id"], lines=[dict(item=part["id"], qty=2)]), ADMIN)
    p = act(s, "productionOrder", dict(bom=bom["id"], qty=10), ADMIN)
    act(s, "releaseProduction", dict(id=p["id"]), ADMIN)
    for qty, partial, conversion in [(12, True, 3), (8, False, 2)]:
        act(s, "consumeProduction", dict(id=p["id"], lines=[dict(item=part["id"], qty=qty)]), ADMIN)
        act(
            s,
            "finishProduction",
            dict(id=p["id"], outputQty=qty // 2, partial=partial, conversionCost=conversion),
            ADMIN,
        )
        assert account_balances(s, today())["Work in progress"] == 0
    assert account_balances(s, today())["Production conversion clearing"] == -5
