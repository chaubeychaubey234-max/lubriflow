"""Position-based perpetual stock subledger with moving-average position costs."""
from copy import deepcopy
from datetime import datetime, timezone
from .domain import (get, active, require, dec, money, amount, quantity, text, identifier,
                     today, voucher_date, valid_date)

INVENTORY_ACTIONS = {"itemTracking", "stockCount", "approveStockCount", "reserveStock",
                     "releaseReservation", "relocateStock", "stockIssue", "stockTransfer", "landedCost",
                     "stockDisposition", "confirmOpeningCost"}


def tracking(line):
    return {k: line[k] for k in ("bin", "lot", "serial", "expiry", "reservation") if line.get(k)}


def receipt_tracking(receipt, line, s):
    from .accounting import fx
    po=get(s,"orders",receipt["po"])
    rate=fx(s,po.get("currency",s["settings"]["currency"]),receipt["date"])
    return dict(bin=line.get("bin", ""), lot=line.get("lot") or receipt.get("batch", ""),
                serial=line.get("serial", ""), expiry=line.get("expiry") or receipt.get("expiry", ""),
                unit_cost=dec(line["price"]) * rate * (1 - dec(line.get("discount", 0)) / 100), entry_date=receipt["date"])


def ensure_positions(s, item):
    if item.get("positionsInitialized"):
        return
    # Existing balances have no historical cost layers. Mark their provisional cost explicitly.
    for warehouse, qty in item["stockByWarehouse"].items():
        if qty:
            s["stockPositions"].append(dict(id=identifier(s, "POS"), item=item["id"], warehouse=warehouse,
                bin="", lot="", serial="", expiry="", qty=qty, value=money(dec(qty) * dec(item["price"])),
                version=0, costBasis="Provisional opening item price", status="Available"))
    item["positionsInitialized"] = True


def held(s, position, exclude=""):
    return sum((dec(r["remaining"]) for r in s["reservations"]
                if r["position"] == position and r["status"] == "Active" and r["id"] != exclude), dec(0))


def validate_location(s, warehouse, bin_id):
    active(s, "warehouses", warehouse)
    if bin_id:
        require(active(s, "bins", bin_id)["warehouse"] == warehouse, "Bin belongs to a different warehouse.")


def move(s, actor, item_id, delta, reference, kind, warehouse="WH-MAIN", **options):
    item = get(s, "items", item_id)
    ensure_positions(s, item)
    delta = dec(delta)
    quantity(abs(delta))
    date = voucher_date(s, options.get("entry_date"))
    require(not any(m["item"] == item_id and m.get("date", m["at"][:10]) > date for m in s["stockMoves"]), "Stock movements cannot be backdated before later item movements.")
    bin_id, lot, serial, expiry = (text(options.get(k, ""), k) for k in ("bin", "lot", "serial", "expiry"))
    validate_location(s, warehouse, bin_id)
    if expiry:
        valid_date(expiry)
    mode = item.get("tracking", "none")
    require(mode != "lot" or lot, "Choose a lot for this item.")
    require(mode != "serial" or (serial and abs(delta) == 1), "Serial-tracked movements require one unit and a serial number.")
    allocations = []
    if delta > 0:
        require(not expiry or expiry >= date or options.get("allow_expired"), "Cannot receive expired stock.")
        if serial:
            require(delta == 1 and not any(p["item"] == item_id and p["serial"] == serial and dec(p["qty"]) > 0 for p in s["stockPositions"]), "Serial number is already in stock or quantity is not one.")
        p = next((p for p in s["stockPositions"] if (p["item"], p["warehouse"], p["bin"], p["lot"], p["serial"]) == (item_id, warehouse, bin_id, lot, serial)), None)
        if p is None:
            p = dict(id=identifier(s, "POS"), item=item_id, warehouse=warehouse, bin=bin_id, lot=lot,
                     serial=serial, expiry=expiry, qty=0, value=0, version=0, costBasis="Recorded movements", status="Available")
            s["stockPositions"].append(p)
        require(not p["expiry"] or not expiry or p["expiry"] == expiry, "Lot expiry conflicts with existing stock.")
        p["expiry"] = p["expiry"] or expiry
        cost = dec(options.get("unit_cost", item["price"]))
        amount(cost)
        value = amount(options["total_cost"]) if "total_cost" in options else money(delta * dec(cost))
        p.update(qty=float(dec(p["qty"]) + delta), value=money(dec(p["value"]) + dec(value)), version=p["version"] + 1)
        allocations.append(dict(position=p["id"], qty=float(delta), value=value, lot=lot, serial=serial, bin=bin_id, expiry=p["expiry"]))
    else:
        reservation_id = options.get("reservation", "")
        reservation = get(s, "reservations", reservation_id) if reservation_id else None
        if reservation:
            require(reservation["status"] == "Active" and reservation["item"] == item_id and dec(reservation["remaining"]) >= -delta, "Reservation does not cover this movement.")
            require(options.get("reservation_source") == reservation["source"], "Reservation belongs to a different source document.")
        candidates = [p for p in s["stockPositions"] if p["item"] == item_id and p["warehouse"] == warehouse
            and p["status"] == "Available"
            and (not p["bin"] or get(s, "bins", p["bin"]).get("active", True))
            and (not bin_id or p["bin"] == bin_id) and (not lot or p["lot"] == lot) and (not serial or p["serial"] == serial)
            and (not options.get("position") or p["id"] == options["position"])
            and (not reservation or p["id"] == reservation["position"])
            and (not p["expiry"] or p["expiry"] >= date or options.get("allow_expired"))]
        candidates.sort(key=lambda p: (p["expiry"] or "9999-12-31", p["id"]))
        available = sum((max(dec(0), dec(p["qty"]) - held(s, p["id"], reservation_id)) for p in candidates), dec(0))
        require(available >= -delta, "Insufficient unreserved, unexpired stock at the selected location.")
        needed = -delta
        for p in candidates:
            take = min(needed, max(dec(0), dec(p["qty"]) - held(s, p["id"], reservation_id)))
            if take <= 0:
                continue
            value = p["value"] if take == dec(p["qty"]) else money(dec(p["value"]) * take / dec(p["qty"]))
            p.update(qty=float(dec(p["qty"]) - take), value=money(dec(p["value"]) - dec(value)), version=p["version"] + 1)
            allocations.append(dict(position=p["id"], qty=float(take), value=value,
                                    **{k: p[k] for k in ("bin", "lot", "serial", "expiry")}))
            needed -= take
            if not needed:
                break
        if reservation:
            reservation["remaining"] = float(dec(reservation["remaining"]) + delta)
            if reservation["remaining"] == 0:
                reservation["status"] = "Consumed"
    balances = {}
    for p in s["stockPositions"]:
        if p["item"] == item_id:
            balances[p["warehouse"]] = balances.get(p["warehouse"], dec(0)) + dec(p["qty"])
    item["stockByWarehouse"] = {k: float(v) for k, v in balances.items()}
    item["stock"] = float(sum(balances.values(), dec(0)))
    result = dict(id=identifier(s, "MOV"), item=item_id, warehouse=warehouse, qty=float(delta), balance=item["stock"],
                  reference=reference, type=kind, actor=actor["id"], date=date, at=datetime.now(timezone.utc).isoformat(),
                  value=money(sum((dec(a["value"]) for a in allocations), dec(0))), allocations=allocations)
    s["stockMoves"].insert(0, result)
    return result


def inventory_action(s, action, d, actor):
    if action == "stockDisposition":
        p = get(s, "stockPositions", d["position"])
        require(d.get("status") in {"Available", "Quarantined"}, "Choose available or quarantined.")
        p.update(status=d["status"], dispositionReason=text(d.get("reason"), "Inspection or recall reason", True),
                 dispositionBy=actor["id"], dispositionAt=datetime.now(timezone.utc).isoformat(), version=p["version"] + 1)
        return p
    if action == "confirmOpeningCost":
        p = get(s, "stockPositions", d["position"])
        require(p["costBasis"] == "Provisional opening item price" and p["version"] == 0,
                "Opening cost can be confirmed only before position activity.")
        value = amount(d["value"])
        require(p["qty"] > 0 or value == 0, "Zero stock cannot carry a value.")
        p.update(value=value, costBasis="Finance-confirmed opening value", costEvidence=text(d.get("reason"), "Opening cost evidence", True),
                 costConfirmedBy=actor["id"], costConfirmedDate=voucher_date(s, d.get("date")), version=p["version"] + 1)
        return p
    if action == "itemTracking":
        item = get(s, "items", d["item"])
        mode = d.get("tracking", "none")
        require(mode in {"none", "lot", "serial"}, "Choose none, lot or serial tracking.")
        require(mode == item.get("tracking", "none") or not item["stock"], "Tracking mode can change only with zero stock.")
        barcode = text(d.get("barcode", ""))
        require(not barcode or not any(i["id"] != item["id"] and (i.get("barcode") == barcode or i.get("sku") == barcode) for i in s["items"]), "Barcode is already assigned.")
        item.update(tracking=mode, barcode=barcode)
        return item
    if action == "reserveStock":
        p = get(s, "stockPositions", d["position"])
        require(p["status"] == "Available", "Quarantined stock cannot be reserved.")
        validate_location(s, p["warehouse"], p["bin"])
        qty = quantity(d["qty"])
        require(not p["expiry"] or p["expiry"] >= today(), "Expired stock cannot be reserved.")
        require(dec(p["qty"]) - held(s, p["id"]) >= dec(qty), "Not enough unreserved stock.")
        source_kind = d.get("sourceKind", "salesOrders")
        require(source_kind in {"salesOrders", "productionOrders"}, "Choose a sales or production order.")
        require(source_kind != "productionOrders" or actor["role"] in {"admin", "stores", "production"}, "Production reservations require stores or production access.")
        source = get(s, source_kind, d["source"])
        statuses = {"Open"} if source_kind == "salesOrders" else {"Released", "In progress"}
        require(source["status"] in statuses and source["warehouse"] == p["warehouse"], "Choose an active source order in this warehouse.")
        line = next((l for l in source["lines"] if l["item"] == p["item"]), None)
        reserved = sum((dec(r["remaining"]) for r in s["reservations"] if r["source"] == source["id"] and r["item"] == p["item"] and r["status"] == "Active"), dec(0))
        delivered = (sum((dec(l["qty"]) for doc in s["deliveries"] if doc["order"] == source["id"] for l in doc["lines"] if l["item"] == p["item"]), dec(0))
                     if source_kind == "salesOrders" else sum((dec(c["qty"]) for c in source["consumption"] if c["item"] == p["item"]), dec(0)))
        require(line and reserved + delivered + dec(qty) <= dec(line["qty"]), "Reservation exceeds remaining order demand.")
        r = dict(id=identifier(s, "RES"), position=p["id"], item=p["item"], source=source["id"], qty=qty, remaining=qty, date=today(), status="Active")
        s["reservations"].insert(0, r)
        r["sourceKind"] = source_kind
        p["version"] += 1
        return r
    if action == "releaseReservation":
        r = get(s, "reservations", d["id"])
        require(r["status"] == "Active", "Reservation is not active.")
        r.update(status="Released", reason=text(d.get("reason"), "Reason", True))
        get(s, "stockPositions", r["position"])["version"] += 1
        return r
    if action in {"stockIssue", "stockTransfer", "relocateStock"}:
        qty = quantity(d.get("qty"))
        reason = text(d.get("reason"), "Reason", True)
        source = d.get("fromWarehouse", d.get("warehouse", "WH-MAIN"))
        r = dict(id=identifier(s, "STK"))
        kind = 'Stock issue' if action == 'stockIssue' else 'Stock transfer'
        out = move(s, actor, d["item"], -qty, r["id"], kind, source,
                   **tracking(d), entry_date=d.get("date"))
        out['reason'] = reason
        out["demand"] = action == "stockIssue"
        if action != "stockIssue":
            target = d.get("toWarehouse", source)
            target_bin = d.get("toBin", "")
            require(source != target or any(a["bin"] != target_bin for a in out["allocations"]), "Choose a different warehouse or bin.")
            for a in out["allocations"]:
                move(s, actor, d["item"], a["qty"], r["id"], "Transfer receipt", target, bin=target_bin,
                     lot=a["lot"], serial=a["serial"], expiry=a["expiry"], total_cost=a["value"], entry_date=d.get("date"))
        return r
    if action == "stockCount":
        p = get(s, "stockPositions", d["position"])
        counted = dec(d.get("counted"))
        require(counted <= dec("1000000000"), "Count exceeds the supported quantity.")
        require(counted >= 0 and counted == counted.quantize(dec(".000001")), "Count must be nonnegative with up to six decimals.")
        r = dict(id=identifier(s, "COUNT"), position=p["id"], expected=p["qty"], counted=float(counted),
                 positionVersion=p["version"], date=voucher_date(s, d.get("date")), reason=text(d.get("reason"), "Count reason", True), status="Pending", createdBy=actor["id"])
        s["stockCounts"].insert(0, r)
        return r
    if action == "approveStockCount":
        r = get(s, "stockCounts", d["id"])
        p = get(s, "stockPositions", r["position"])
        require(r["status"] == "Pending" and p["version"] == r["positionVersion"], "Count is stale or already posted. Recount after stock changes.")
        require(not s["settings"]["separation"] or actor["id"] != r["createdBy"], "A different user must approve the count.")
        voucher_date(s, r["date"])
        delta = dec(r["counted"]) - dec(p["qty"])
        if delta:
            require(p["status"] == "Available", "Release quarantine before posting a quantity adjustment.")
            move(s, actor, p["item"], delta, r["id"], "Approved stock count", p["warehouse"],
                 **{k: p[k] for k in ("bin", "lot", "serial", "expiry")}, position=p["id"],
                 unit_cost=dec(p["value"]) / dec(p["qty"]) if p["qty"] else get(s, "items", p["item"])["price"],
                 allow_expired=True, entry_date=r["date"])
        r.update(status="Posted", approvedBy=actor["id"], variance=float(delta))
        return r
    if action == "landedCost":
        receipt = get(s, "receipts", d["receipt"])
        require(receipt["status"] == "Accepted", "Landed cost requires an accepted receipt.")
        ref = text(d.get("reference"), "Cost invoice/reference", True)
        require(not any(c["reference"].casefold() == ref.casefold() for c in s["landedCosts"]), "Landed cost reference already recorded.")
        charges = amount(d.get("amount"), True)
        allocations = [dict(a) for m in s["stockMoves"] if m["reference"] == receipt["id"] and m["qty"] > 0 for a in m.get("allocations", [])]
        require(allocations, "Receipt predates inventory costing. Reconcile opening values first.")
        for a in allocations:
            p = get(s, "stockPositions", a["position"])
            require(not any(m["qty"] < 0 and any(x["position"] == p["id"] for x in m.get("allocations", [])) for m in s["stockMoves"]), "Stock has been issued from this position. Retrospective landed cost requires a finance adjustment.")
        basis = sum((dec(a["value"]) for a in allocations), dec(0))
        require(basis > 0, "Value-based landed cost requires positive receipt values.")
        remaining = dec(charges)
        for i, a in enumerate(allocations):
            share = remaining if i == len(allocations) - 1 else min(remaining, dec(money(dec(charges) * dec(a["value"]) / basis)))
            remaining -= share
            p = get(s, "stockPositions", a["position"])
            p["value"] = money(dec(p["value"]) + share)
            p["version"] += 1
            a["allocatedCost"] = money(share)
        r = dict(id=identifier(s, "LC"), receipt=receipt["id"], reference=ref, amount=charges,
                 date=voucher_date(s, d.get("date")), allocations=allocations, status="Allocated")
        s["landedCosts"].insert(0, r)
        return r
    raise ValueError("Unknown inventory command.")


def inventory_report(s):
    copy = deepcopy(s)
    for item in copy["items"]:
        ensure_positions(copy, item)
    return dict(method="Moving average per warehouse/bin/lot/serial position", positions=[
        dict(p, reserved=float(held(copy, p["id"])), available=float(dec(p["qty"]) - held(copy, p["id"]))
             if p["status"] == "Available" and (not p["expiry"] or p["expiry"] >= today())
             and get(copy, "warehouses", p["warehouse"]).get("active", True)
             and (not p["bin"] or get(copy, "bins", p["bin"]).get("active", True)) else 0)
        for p in copy["stockPositions"]], value=money(sum((dec(p["value"]) for p in copy["stockPositions"]), dec(0))))
