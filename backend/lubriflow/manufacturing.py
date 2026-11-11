"""Frozen production BOMs, material planning and input-to-output cost genealogy."""
from copy import deepcopy
from decimal import ROUND_CEILING
from .domain import get, active, require, quantity, amount, text, lines, identifier, dec, money, voucher_date, today
from .inventory import move, tracking

PRODUCTION_ACTIONS = {"bom", "productionOrder", "createMaterialPlan", "releaseProduction", "consumeProduction", "finishProduction", "cancelProduction"}


def allocate_material(order, cumulative, partial):
    """Allocate consumed inputs FIFO by recorded issue, leaving unused issued cost in WIP."""
    consumed = {c['movement']: c for c in order['consumption']}
    allocated = {}
    for output in order.get('outputs', []):
        if 'materialAllocations' not in output:
            # Previous releases required exact proportional consumption at every output;
            # therefore each previously unallocated issue was fully capitalised then.
            output['materialAllocations'] = [dict(movement=key, item=consumed[key]['item'],
                qty=consumed[key]['qty'], cost=consumed[key]['cost'])
                for key in output['consumptionMovements'] if key not in allocated]
        for entry in output['materialAllocations']:
            q, value = allocated.get(entry['movement'], (dec(0), dec(0)))
            allocated[entry['movement']] = (q + dec(entry['qty']), value + dec(entry['cost']))
    result = []
    for line in order['lines']:
        required = dec(line['qty'])
        if partial:
            required = (required * cumulative / dec(order['qty'])).quantize(dec('.000001'), rounding=ROUND_CEILING)
        already = sum((q for key, (q, _) in allocated.items() if consumed[key]['item'] == line['item']), dec(0))
        needed = required - already
        require(needed >= 0, 'Prior material allocation exceeds the current output requirement.')
        for entry in order['consumption']:
            if entry['item'] != line['item'] or needed == 0:
                continue
            used, cost_used = allocated.get(entry['movement'], (dec(0), dec(0)))
            remaining = dec(entry['qty']) - used
            take = min(needed, remaining)
            if take <= 0:
                continue
            # Final allocation takes the exact remaining cost, absorbing cent rounding.
            cost = dec(entry['cost']) - cost_used if take == remaining else dec(money(dec(entry['cost']) * (used + take) / dec(entry['qty']))) - cost_used
            result.append(dict(movement=entry['movement'], item=entry['item'], qty=float(take), cost=float(cost)))
            needed -= take
        require(needed == 0, 'Consumption must cover the frozen BOM proportion for cumulative output.')
    return result


def production_action(s, action, d, actor):
    require(s["settings"]["modules"].get("manufacturing"), "Enable the manufacturing module in company settings.")
    if action == 'createMaterialPlan':
        from .material_planning import create_plan
        return create_plan(s, d, actor)
    if action == "bom":
        output = get(s, "items", d["output"])
        components = lines(s, d["lines"])
        require(all(l["item"] != output["id"] for l in components), "A BOM cannot consume its own output.")
        # A BOM version is immutable; create another version for engineering changes.
        r = dict(id=identifier(s, "BOM"), name=text(d.get("name"), "BOM name", True), output=output["id"],
                 outputQty=quantity(d.get("outputQty", 1)), lines=components, date=today(), status="Active")
        s["boms"].insert(0, r)
        return r
    if action == "productionOrder":
        bom = get(s, "boms", d["bom"])
        require(bom["status"] == "Active", "Choose an active BOM.")
        qty = quantity(d["qty"])
        warehouse = active(s, "warehouses", d.get("warehouse", "WH-MAIN"))["id"]
        factor = dec(qty) / dec(bom["outputQty"])
        components = deepcopy(bom["lines"])
        for line in components:
            scaled = dec(line['qty']) * factor
            require(scaled <= dec('1000000000'), 'Component requirement exceeds the supported quantity. Split the order.')
            line["qty"] = quantity(scaled.quantize(dec(".000001"), rounding=ROUND_CEILING))
        r = dict(id=identifier(s, "PROD"), bom=bom["id"], output=bom["output"], qty=qty, warehouse=warehouse,
                 lines=components, date=voucher_date(s, d.get("date")), consumption=[], materialCost=0,
                 status="Draft", createdBy=actor["id"], note=text(d.get("note", "")))
        s["productionOrders"].insert(0, r)
        return r
    r = get(s, "productionOrders", d["id"])
    if action == "releaseProduction":
        require(r["status"] == "Draft", "Only draft production can be released.")
        r.update(status="Released", releasedBy=actor["id"])
        return r
    if action == "cancelProduction":
        require(r["status"] in {"Draft", "Released"} and not r["consumption"], "Cannot cancel after materials have been consumed.")
        r.update(status="Cancelled", reason=text(d.get("reason"), "Reason", True))
        for reservation in s["reservations"]:
            if reservation["source"] == r["id"] and reservation["status"] == "Active":
                reservation["status"] = "Released"
                get(s, "stockPositions", reservation["position"])["version"] += 1
        return r
    require(r["status"] in {"Released", "In progress"}, "Production must be released and not completed.")
    date = voucher_date(s, d.get("date"))
    require(date >= r["date"], "Production transaction cannot precede the order.")
    if action == "consumeProduction":
        for line in lines(s, d["lines"]):
            planned = next((l for l in r["lines"] if l["item"] == line["item"]), None)
            used = sum((dec(m["qty"]) for m in r["consumption"] if m["item"] == line["item"]), dec(0))
            require(planned and used + dec(line["qty"]) <= dec(planned["qty"]), "Consumption exceeds the frozen BOM requirement.")
            movement = move(s, actor, line["item"], -dec(line["qty"]), r["id"], "Production consumption", r["warehouse"], entry_date=date, reservation_source=r["id"], **tracking(line))
            r["consumption"].append(dict(item=line["item"], qty=line["qty"], movement=movement["id"], cost=movement["value"]))
        r["materialCost"] = money(sum((dec(c["cost"]) for c in r["consumption"]), dec(0)))
        r["status"] = "In progress"
        return r
    require(action == "finishProduction", "Unknown production action.")
    partial = d.get("partial", False)
    require(isinstance(partial, bool), "Partial output must be a boolean.")
    previous = dec(r.get("outputQty", 0))
    output = quantity(d.get("outputQty", dec(r["qty"]) - previous))
    cumulative = previous + dec(output)
    require(cumulative <= dec(r["qty"]), "Output cannot exceed remaining planned quantity.")
    require(not partial or cumulative < dec(r["qty"]), "Use final completion for the remaining output.")
    for line in r["lines"]:
        used = sum((dec(c["qty"]) for c in r["consumption"] if c["item"] == line["item"]), dec(0))
        required = dec(line["qty"])
        if partial:
            required = (required * cumulative / dec(r["qty"])).quantize(dec(".000001"), rounding=ROUND_CEILING)
        require(used >= required if partial else used == required, "Consume all planned components before completion." if not partial else
                "For partial output, consumption must cover the frozen BOM proportion for cumulative output.")
    require(all(get(s, "stockMoves", c["movement"])["date"] <= date for c in r["consumption"]), "Output cannot precede material consumption.")
    require(all(o["date"] <= date for o in r.get("outputs", [])), "Output cannot precede an earlier output posting.")
    reason = text(d.get("reason", ""))
    require(partial or cumulative == dec(r["qty"]) or reason, "Record a yield-loss reason when output is below plan.")
    conversion = amount(d.get("conversionCost", 0))
    allocations = allocate_material(r, cumulative, partial)
    material = money(sum((dec(a['cost']) for a in allocations), dec(0)))
    cost = money(dec(material) + dec(conversion))
    movement = move(s, actor, r["output"], output, r["id"], "Production output", r["warehouse"],
                    **tracking(d), total_cost=cost, entry_date=date)
    r.setdefault("outputs", []).append(dict(movement=movement["id"], qty=output, date=date,
        materialCost=material, conversionCost=conversion, totalCost=cost, postedBy=actor["id"],
        consumptionMovements=list(dict.fromkeys(a['movement'] for a in allocations)), materialAllocations=allocations,
        final=not partial, reason=reason))
    total = money(dec(r.get("totalCost", 0)) + dec(cost))
    r.update(status="In progress" if partial else "Completed", outputQty=quantity(cumulative),
             conversionCost=money(dec(r.get("conversionCost", 0)) + dec(conversion)), totalCost=total,
             allocatedMaterialCost=money(dec(r.get('allocatedMaterialCost', 0)) + dec(material)), unitCost=money(dec(total) / cumulative),
             outputMovement=movement["id"], yieldNote=reason)
    if not partial:
        r["completedDate"] = date
    return r
