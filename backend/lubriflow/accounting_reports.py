"""Date-aware ledger drilldown, ageing, cash movement and dimension budgets."""

from datetime import date
from .domain import dec, money, totals
from .accounting import allocated, remaining_funds, invoice_carrying_base


def open_as_of(s, inv, side, end):
    value = dec(
        inv["amount"] if side == "supplier" or inv.get("accountingDocument") else totals(inv)["total"]
    )
    payments = s["payments" if side == "supplier" else "customerPayments"]
    value -= sum(
        (
            dec(p["amount"])
            for p in payments
            if p["invoice"] == inv["id"]
            and p["date"] <= end
            and (p["status"] != "Reversed" or p.get("reversalDate", "") > end)
        ),
        dec(0),
    )
    value -= sum(
        (
            dec(c.get("appliedAmount", c["amount"]))
            for c in s["credits" if side == "supplier" else "customerCredits"]
            if c["invoice"] == inv["id"] and c["date"] <= end
        ),
        dec(0),
    )
    return value - allocated(s, inv["id"], side, end)


def extended_reports(s, start, end):
    ageing = []
    for side, collection in [("supplier", "invoices"), ("customer", "salesInvoices")]:
        for inv in s[collection] + [i for i in s["accountingDocuments"] if i["side"] == side]:
            if inv["date"] > end or inv["status"] not in {"Posted", "Part paid", "Paid"}:
                continue
            outstanding = open_as_of(s, inv, side, end)
            days = (date.fromisoformat(end) - date.fromisoformat(inv["due"])).days
            bucket = (
                "Current"
                if days <= 0
                else "1–30"
                if days <= 30
                else "31–60"
                if days <= 60
                else "61–90"
                if days <= 90
                else "90+"
            )
            ageing.append(
                dict(
                    id=inv["id"],
                    side=side,
                    party=inv[side],
                    due=inv["due"],
                    currency=inv.get("currency", s["settings"]["currency"]),
                    balance=money(outstanding),
                    baseBalance=money(invoice_carrying_base(s, inv, side, end)),
                    daysOverdue=max(days, 0),
                    bucket=bucket,
                )
            )
    ledger = []
    for j in sorted(s["journal"], key=lambda j: (j["date"], j["id"])):
        if start <= j["date"] <= end:
            for i, line in enumerate(j["entries"]):
                ledger.append(
                    dict(
                        id=j["id"] + "/" + str(i),
                        journal=j["id"],
                        date=j["date"],
                        reference=j["reference"],
                        description=j["description"],
                        **line,
                    )
                )
    budgets = []
    for b in s["financeBudgets"]:
        actual = sum(
            (
                dec(l.get("debit", 0)) - dec(l.get("credit", 0))
                for j in s["journal"]
                if b["start"] <= j["date"] <= min(b["end"], end) and not j.get("yearClose")
                for l in j["entries"]
                if l["account"] == b["account"]
                and all(not b.get(k) or l.get(k) == b[k] for k in ("costCentre", "project"))
            ),
            dec(0),
        )
        budgets.append(
            dict(
                **b,
                actual=money(actual),
                remaining=money(dec(b["amount"]) - actual),
                variance=money(actual - dec(b["amount"])),
            )
        )
    banks = {l["name"] for l in s["ledgers"] if l["type"] in {"bank", "cash"}}
    opening = sum(
        (
            dec(l.get("debit", 0)) - dec(l.get("credit", 0))
            for j in s["journal"]
            if j["date"] < start
            for l in j["entries"]
            if l["account"] in banks
        ),
        dec(0),
    )
    flow = []
    exchange_effect = dec(0)
    for j in s["journal"]:
        if not start <= j["date"] <= end:
            continue
        cash = sum(
            (dec(l.get("debit", 0)) - dec(l.get("credit", 0)) for l in j["entries"] if l["account"] in banks),
            dec(0),
        )
        if j["description"] == "Period-end FX revaluation":
            exchange_effect += cash
            continue
        effect = sum(
            (
                dec(m["baseValue"]) - dec(m.get("spotBase", m["baseValue"]))
                for m in s["bankFxMovements"]
                if m["reference"] == j["reference"] and m["date"] == j["date"]
            ),
            dec(0),
        )
        exchange_effect += effect
        cash -= effect
        if cash:
            flow.append(
                dict(
                    id=j["id"],
                    date=j["date"],
                    reference=j["reference"],
                    amount=money(cash),
                    classification=j.get("cashFlowClass", "Unclassified"),
                )
            )
    categories = {
        k: money(sum((dec(r["amount"]) for r in flow if r["classification"] == k), dec(0)))
        for k in ["Operating", "Investing", "Financing", "Unclassified"]
    }
    net = sum((dec(r["amount"]) for r in flow), dec(0))
    gl = {}
    for j in s["journal"]:
        if j["date"] > end:
            continue
        for line in j["entries"]:
            gl[line["account"]] = (
                gl.get(line["account"], dec(0)) + dec(line.get("debit", 0)) - dec(line.get("credit", 0))
            )
    reconciliation = []
    for side, account, sign in [("supplier", "Accounts payable", -1), ("customer", "Accounts receivable", 1)]:
        subledger = sum((dec(r["baseBalance"]) for r in ageing if r["side"] == side), dec(0))
        ledger = gl.get(account, dec(0)) * sign
        reconciliation.append(
            dict(
                account=account,
                ledger=money(ledger),
                subledger=money(subledger),
                difference=money(ledger - subledger),
            )
        )
    from .accounting import fund_carrying_base

    for side, account, sign in [("supplier", "Supplier advances", 1), ("customer", "Customer advances", -1)]:
        subledger = sum(
            (
                fund_carrying_base(s, f, end)
                for f in s["partyFunds"]
                if f["side"] == side and f["date"] <= end
            ),
            dec(0),
        )
        ledger = gl.get(account, dec(0)) * sign
        reconciliation.append(
            dict(
                account=account,
                ledger=money(ledger),
                subledger=money(subledger),
                difference=money(ledger - subledger),
            )
        )
    if s["settings"].get("perpetualAccounting"):
        opening = sum(
            (
                dec(l.get("debit", 0)) - dec(l.get("credit", 0))
                for j in s["journal"]
                if j["reference"] == "OPEN-INVENTORY" and j["date"] <= end
                for l in j["entries"]
                if l["account"] == "Inventory asset"
            ),
            dec(0),
        )
        subledger = (
            opening
            + sum(
                (dec(m["value"]) * (1 if m["qty"] > 0 else -1) for m in s["stockMoves"] if m["date"] <= end),
                dec(0),
            )
            + sum((dec(c["amount"]) for c in s["landedCosts"] if c["date"] <= end), dec(0))
        )
        ledger = gl.get("Inventory asset", dec(0))
        reconciliation.append(
            dict(
                account="Inventory asset",
                ledger=money(ledger),
                subledger=money(subledger),
                difference=money(ledger - subledger),
            )
        )
    return dict(
        reconciliation=reconciliation,
        ageing=ageing,
        ledgerDrilldown=ledger,
        budgetPerformance=budgets,
        cashFlow=dict(
            opening=money(opening),
            netMovement=money(net),
            closing=money(opening + net + exchange_effect),
            exchangeEffect=money(exchange_effect),
            categories=categories,
            entries=flow,
        ),
        advances=[
            dict(**f, unallocated=money(remaining_funds(s, f, end)))
            for f in s["partyFunds"]
            if f["date"] <= end
        ],
    )


def tax_summary(s, start, end):
    result = {}
    for side, collection, credits in [
        ("supplier", "invoices", "credits"),
        ("customer", "salesInvoices", "customerCredits"),
    ]:
        value = sum(
            (
                dec(totals(i)["tax"]) * dec(i.get("rate", 1))
                for i in s[collection]
                if i["status"] in {"Posted", "Part paid", "Paid"} and start <= i["date"] <= end
            ),
            dec(0),
        )
        value += sum(
            (
                dec(i["taxAmount"]) * dec(i["rate"])
                for i in s["accountingDocuments"]
                if i["side"] == side and start <= i["date"] <= end
            ),
            dec(0),
        )
        value -= sum(
            (dec(totals(c)["tax"]) * dec(c.get("rate", 1)) for c in s[credits] if start <= c["date"] <= end),
            dec(0),
        )
        value -= sum(
            (
                dec(f.get("taxAmount", 0)) * dec(f["rate"])
                for f in s["partyFunds"]
                if f.get("onAccountCredit") and f["side"] == side and start <= f["date"] <= end
            ),
            dec(0),
        )
        result[side] = money(value)
    return result
