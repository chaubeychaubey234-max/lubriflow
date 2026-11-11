"""Sales documents share stock availability and post balanced receivable journals."""
from copy import deepcopy
from .domain import (get, active, require, text, lines, quantity, identifier, totals, dec, amount, money,
                     voucher_date, valid_date, add_days, today, journal, sum_qty)
from .inventory import move, tracking

SALES_ACTIONS = {"salesQuote", "convertSalesQuote", "salesOrder", "deliverSale", "salesInvoice",
                 "customerPayment", "salesReturn", "customerCredit", "closeSalesOrder"}


def receivable(s, invoice):
    from .accounting import allocated
    return money(dec(totals(invoice)["total"])
        - allocated(s,invoice["id"],"customer")
        - sum((dec(p["amount"]) for p in s["customerPayments"] if p["invoice"] == invoice["id"] and p["status"] == "Recorded"), dec(0))
        - sum((dec(c.get("appliedAmount",c["amount"])) for c in s["customerCredits"] if c["invoice"] == invoice["id"]), dec(0)))


def enforce_credit(s, customer, extra):
    if customer.get("creditLimit", 0):
        current = sum((dec(receivable(s, i)) for i in s["salesInvoices"] if i["customer"] == customer["id"] and i["status"] == "Posted"), dec(0))
        require(current + dec(extra) <= dec(customer["creditLimit"]), "Customer credit limit exceeded.")


def sales_action(s, action, d, actor):
    if action in {"salesQuote", "salesOrder"}:
        customer = active(s, "customers", d["customer"])
        date = voucher_date(s, d.get("date"))
        r = dict(id=identifier(s, "SQ" if action == "salesQuote" else "SO"), customer=customer["id"], date=date,
                 due=valid_date(d.get("due") or date), lines=lines(s, d["lines"]), tax=amount(d.get("tax", s["settings"]["defaultTax"])),
                 warehouse=active(s, "warehouses", d.get("warehouse", "WH-MAIN"))["id"], note=text(d.get("note", "")),
                 status="Open", createdBy=actor["id"])
        require(r["tax"] <= 100 and r["due"] >= date, "Check sales date and tax rate.")
        if action == "salesQuote":
            r["validUntil"] = valid_date(d.get("validUntil"))
            require(r["validUntil"] >= date, "Quotation validity cannot precede its date.")
        else:
            enforce_credit(s, customer, totals(r)["total"])
        s["salesQuotes" if action == "salesQuote" else "salesOrders"].insert(0, r)
        return r
    if action == "convertSalesQuote":
        quote = get(s, "salesQuotes", d["id"])
        require(quote["status"] == "Open" and quote["validUntil"] >= today(), "Quotation is expired or already converted.")
        order = sales_action(s, "salesOrder", {**deepcopy(quote), "date": today(), "due": max(today(), quote["due"])}, actor)
        order["quote"] = quote["id"]
        quote.update(status="Converted", order=order["id"])
        return order
    if action == "closeSalesOrder":
        order = get(s, "salesOrders", d["id"])
        require(order["status"] == "Open", "Order is already closed.")
        order.update(status="Closed", closeReason=text(d.get("reason"), "Closure reason", True))
        for r in s["reservations"]:
            if r["source"] == order["id"] and r["status"] == "Active":
                r["status"] = "Released"
                get(s, "stockPositions", r["position"])["version"] += 1
        return order
    if action == "deliverSale":
        order = get(s, "salesOrders", d["order"])
        require(order["status"] == "Open", "Sales order is not open.")
        date = voucher_date(s, d.get("date"))
        require(date >= order["date"], "Delivery cannot precede order.")
        ls = lines(s, d["lines"])
        r = dict(id=identifier(s, "DN"), order=order["id"], customer=order["customer"], date=date,
                 warehouse=order["warehouse"], lines=ls, status="Delivered", movements=[])
        for line in ls:
            original = next((l for l in order["lines"] if l["item"] == line["item"]), None)
            delivered = sum_qty([doc for doc in s["deliveries"] if doc["order"] == order["id"]], line["item"])
            require(original and dec(delivered) + dec(line["qty"]) <= dec(original["qty"]), "Delivery exceeds ordered quantity.")
            for key in ("price", "discount", "taxRate"):
                if key in original:
                    line[key] = original[key]
            movement = move(s, actor, line["item"], -dec(line["qty"]), r["id"], "Customer delivery", order["warehouse"],
                            **tracking(line), reservation_source=order["id"], entry_date=date)
            r["movements"].append(movement["id"])
        r["cost"] = money(sum((dec(get(s, "stockMoves", m)["value"]) for m in r["movements"]), dec(0)))
        s["deliveries"].insert(0, r)
        return r
    if action == "salesInvoice":
        order = get(s, "salesOrders", d["order"])
        date = voucher_date(s, d.get("date"))
        require(date >= order["date"], "Invoice cannot precede its order.")
        ls = lines(s, d["lines"])
        for line in ls:
            original = next((l for l in order["lines"] if l["item"] == line["item"]), None)
            delivered = sum_qty([doc for doc in s["deliveries"] if doc["order"] == order["id"] and doc["date"] <= date], line["item"])
            billed = sum_qty([doc for doc in s["salesInvoices"] if doc["order"] == order["id"] and doc["status"] != "Void"], line["item"])
            require(original and dec(delivered) >= dec(billed) + dec(line["qty"]), "Invoice exceeds delivered quantity at the invoice date.")
            for key in ("price", "discount", "taxRate"):
                if key in original:
                    line[key] = original[key]
        customer = get(s, "customers", order["customer"])
        r = dict(id=identifier(s, "SI"), order=order["id"], customer=order["customer"], number=text(d.get("number"), "Invoice reference", True),
                 date=date, due=valid_date(d.get("due") or add_days(date, customer.get("creditDays", 0))), lines=ls, tax=order["tax"], status="Posted")
        require(r["due"] >= date, "Due date cannot precede invoice.")
        require(not any(i["customer"] == r["customer"] and i["number"].casefold() == r["number"].casefold() for i in s["salesInvoices"]), "Duplicate invoice reference.")
        t = totals(r)
        enforce_credit(s, customer, t["total"])
        journal(s, r["id"], "Customer invoice", [dict(account="Accounts receivable", debit=t["total"]),
                dict(account="Sales revenue", credit=t["subtotal"]), dict(account="Output tax", credit=t["tax"])], date)
        s["salesInvoices"].insert(0, r)
        return r
    if action == "customerPayment":
        invoice = get(s, "salesInvoices", d["invoice"])
        value = amount(d.get("amount"), True)
        require(invoice["status"] == "Posted" and value <= receivable(s, invoice), "Payment exceeds the outstanding customer balance.")
        bank = active(s, "ledgers", d.get("bankLedger", "LED-BANK"))
        require(bank["type"] in {"bank", "cash"}, "Choose bank or cash.")
        reference = text(d.get("reference"), "Receipt reference", True)
        require(not any(p["reference"].casefold() == reference.casefold() for p in s["customerPayments"]), "Customer receipt reference already exists.")
        date = voucher_date(s, d.get("date"))
        require(date >= invoice["date"], "Receipt cannot precede invoice.")
        r = dict(id=identifier(s, "RCP"), invoice=invoice["id"], customer=invoice["customer"], amount=value,
                 date=date, reference=reference, bankLedger=bank["id"], status="Recorded")
        journal(s, r["id"], "Customer receipt", [dict(account=bank["name"], debit=value), dict(account="Accounts receivable", credit=value)], date)
        s["customerPayments"].insert(0, r)
        return r
    if action == "salesReturn":
        delivery = get(s, "deliveries", d["delivery"])
        date = voucher_date(s, d.get("date"))
        require(date >= delivery["date"], "Return cannot precede delivery.")
        position_id = text(d.get("position"), "Original delivery position", True)
        item = get(s, "items", d["item"])
        qty = quantity(d["qty"])
        allocations = [a for mid in delivery.get("movements", []) for a in get(s, "stockMoves", mid)["allocations"] if get(s, "stockMoves", mid)["item"] == item["id"] and a["position"] == position_id]
        supplied = sum((dec(a["qty"]) for a in allocations), dec(0))
        previous = sum((dec(r["qty"]) for r in s["salesReturns"] if r["delivery"] == delivery["id"] and r["position"] == position_id), dec(0))
        require(allocations and previous + dec(qty) <= supplied, "Return exceeds the traced delivery quantity.")
        a = allocations[0]
        unit_cost = sum((dec(x["value"]) for x in allocations), dec(0)) / supplied
        r = dict(id=identifier(s, "SRET"), delivery=delivery["id"], order=delivery["order"], item=item["id"], position=position_id,
                 qty=qty, date=date, reason=text(d.get("reason"), "Return inspection / reason", True), status="Received")
        movement = move(s, actor, item["id"], qty, r["id"], "Inspected customer return", delivery["warehouse"],
                        bin=d.get("bin", a["bin"]), lot=a["lot"], serial=a["serial"], expiry=a["expiry"], unit_cost=unit_cost, entry_date=date)
        r["movement"] = movement["id"]
        s["salesReturns"].insert(0, r)
        return r
    if action == "customerCredit":
        invoice = get(s, "salesInvoices", d["invoice"])
        returned = get(s, "salesReturns", d["return"])
        require(invoice["status"] == "Posted" and returned["order"] == invoice["order"], "Return must belong to this invoice's sales order.")
        qty = quantity(d["qty"])
        line = next((l for l in invoice["lines"] if l["item"] == returned["item"]), None)
        credited = sum((dec(c["lines"][0]["qty"]) for c in s["customerCredits"] if c["invoice"] == invoice["id"] and c["lines"][0]["item"] == returned["item"]), dec(0))
        return_credited = sum((dec(c["lines"][0]["qty"]) for c in s["customerCredits"] if c["return"] == returned["id"]), dec(0))
        require(line and credited + dec(qty) <= dec(line["qty"]) and return_credited + dec(qty) <= dec(returned["qty"]), "Credit exceeds invoiced or returned quantity.")
        date = voucher_date(s, d.get("date"))
        require(date >= max(invoice["date"], returned["date"]), "Credit cannot precede invoice or return.")
        r = dict(id=identifier(s, "SCN"), invoice=invoice["id"], customer=invoice["customer"], returnId=returned["id"],
                 date=date, lines=[{**deepcopy(line), "qty": qty}], tax=invoice["tax"], status="Posted", reason=text(d.get("reason"), "Credit reason", True))
        r["return"] = returned["id"]
        t = totals(r)

        r["amount"] = t["total"]
        journal(s, r["id"], "Customer return credit", [dict(account="Sales revenue", debit=t["subtotal"]), dict(account="Output tax", debit=t["tax"]), dict(account="Accounts receivable", credit=t["total"])], date)
        s["customerCredits"].insert(0, r)
        return r
    raise ValueError("Unknown sales command.")
