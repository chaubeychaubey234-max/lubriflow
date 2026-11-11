from .domain import (
    require,
    text,
    get,
    dec,
    money,
    amount,
    voucher_date,
    identifier,
    journal,
    totals,
    valid_date,
    today,
)


def chart(s):
    from .accounting import ACCOUNTS

    return (
        [
            dict(id="SYS-AP", name="Accounts payable", type="liability"),
            dict(id="SYS-AR", name="Accounts receivable", type="asset"),
            dict(id="SYS-REV", name="Sales revenue", type="revenue"),
            dict(id="SYS-OUT-TAX", name="Output tax", type="liability"),
            dict(id="SYS-TAX", name="Input tax", type="asset"),
            dict(id="SYS-FREIGHT", name="Freight", type="expense"),
            dict(id="SYS-ROUNDING", name="Rounding", type="expense"),
            dict(id="SYS-FA", name="Fixed assets", type="asset"),
            dict(id="SYS-ACCDEP", name="Accumulated depreciation", type="asset"),
            dict(id="SYS-DEP", name="Depreciation expense", type="expense"),
            dict(id="SYS-RE", name="Retained earnings", type="equity"),
        ]
        + [
            dict(id=l["id"], name=l["name"], type="expense" if l["type"] == "purchase" else "asset")
            for l in s["ledgers"]
        ]
        + [dict(id=i, name=n, type=t) for i, n, t in ACCOUNTS]
        + s["accounts"]
    )


def active_ledger(s, key):
    ledger = get(s, "ledgers", key)
    require(
        ledger.get("active", True) and ledger["type"] in {"bank", "cash"},
        "Choose an active bank or cash ledger.",
    )
    return ledger


def account_name(s, key):
    """Resolve either a chart ID, an account name, or a bank/cash ledger ID."""
    ledger = next((x for x in s["ledgers"] if x["id"] == key), None)
    if ledger:
        return ledger["name"]
    account = next((x for x in chart(s) if x["id"] == key or x["name"] == key), None)
    require(account is not None, "Unknown account.")
    return account["name"]


def account_balances(s, end):
    balances = {}
    for entry in s["journal"]:
        if entry["date"] <= end:
            for line in entry["entries"]:
                balances[line["account"]] = (
                    balances.get(line["account"], dec(0))
                    + dec(line.get("debit", 0))
                    - dec(line.get("credit", 0))
                )
    return balances


def finance_action(s, action, d, actor):
    require(actor["role"] in {"admin", "finance"}, "Finance access required.")
    if action == "account":
        name = text(d.get("name"), "Account name", True)
        require(
            d.get("type") in {"asset", "liability", "equity", "revenue", "expense"},
            "Invalid account classification.",
        )
        require(not any(a["name"].casefold() == name.casefold() for a in chart(s)), "Account already exists.")
        r = dict(id=identifier(s, "ACC"), name=name, type=d["type"])
        s["accounts"].append(r)
        return r
    if action == "exchangeRate":
        source = text(d.get("fromCurrency"), "Source currency", True).upper()
        target = text(d.get("toCurrency", s["settings"]["currency"]), "Target currency", True).upper()
        require(
            len(source) == len(target) == 3 and source.isalpha() and target.isalpha() and source != target,
            "Use two different ISO currency codes.",
        )
        entry_date = valid_date(d.get("date") or today())
        rate = amount(d.get("rate"), True)
        require(
            not any(
                x["fromCurrency"] == source and x["toCurrency"] == target and x["date"] == entry_date
                for x in s["exchangeRates"]
            ),
            "An exchange rate already exists for this date.",
        )
        r = dict(
            id=identifier(s, "FX"),
            fromCurrency=source,
            toCurrency=target,
            date=entry_date,
            rate=rate,
            source=text(d.get("source", "Manual")),
            status="Active",
        )
        s["exchangeRates"].insert(0, r)
        return r
    if action == "bankStatement":
        ledger = active_ledger(s, d.get("bankLedger", "LED-BANK"))
        direction = d.get("direction")
        require(direction in {"debit", "credit"}, "Statement direction must be debit or credit.")
        entry_date = voucher_date(s, d.get("date"))
        reference = text(d.get("reference"), "Bank reference", True)
        require(
            not any(
                x["bankLedger"] == ledger["id"] and x["reference"].casefold() == reference.casefold()
                for x in s["bankStatements"]
            ),
            "Duplicate bank statement reference.",
        )
        r = dict(
            id=identifier(s, "BST"),
            bankLedger=ledger["id"],
            date=entry_date,
            reference=reference,
            amount=amount(d.get("amount"), True),
            direction=direction,
            description=text(d.get("description", "")),
            status="Unreconciled",
        )
        s["bankStatements"].insert(0, r)
        return r
    if action == 'reconcileBankSplit':
        ids = d.get('statements')
        require(isinstance(ids, list) and 2 <= len(ids) <= 100 and all(isinstance(i, str) for i in ids),
                'Choose 2–100 statement lines.')
        require(len(set(ids)) == len(ids), 'Choose each statement once.')
        collection = d.get('collection')
        require(collection in {'payments', 'customerPayments', 'partyFunds', 'fundRefunds'}, 'Invalid payment type.')
        transaction = get(s, collection, d.get('transaction'))
        require(not transaction.get('reconciledStatement'), 'Transaction has already been reconciled.')
        require(transaction.get('status') != 'Reversed', 'Cannot reconcile a reversed transaction.')
        expected = ('credit' if transaction['side'] == 'supplier' else 'debit') if collection == 'partyFunds' else (
            ('debit' if transaction['side'] == 'supplier' else 'credit') if collection == 'fundRefunds' else
            ('credit' if collection == 'payments' else 'debit'))
        statements = [get(s, 'bankStatements', key) for key in ids]
        for statement in statements:
            voucher_date(s, statement['date'])
            require(statement['status'] == 'Unreconciled', 'Statement line has already been reconciled.')
            require(statement['bankLedger'] == transaction['bankLedger'], 'Bank ledger does not match.')
            require(statement['direction'] == expected, 'Statement direction does not match.')
        require(sum((dec(row['amount']) for row in statements), dec(0)) == dec(transaction['amount']),
                'Statement amounts must equal the recorded transaction exactly.')
        for statement in statements:
            statement.update(status='Reconciled', collection=collection, transaction=transaction['id'],
                             reconciledBy=actor['id'], splitStatements=list(ids),
                             matches=[dict(collection=collection, transaction=transaction['id'], amount=statement['amount'])])
        transaction['reconciledStatement'] = ids[0]
        transaction['reconciledStatements'] = list(ids)
        return dict(id=ids[0], statements=list(ids), transaction=transaction['id'])
    if action == "reconcileBankGroup":
        statement = get(s, "bankStatements", d.get("statement"))
        voucher_date(s, statement["date"])
        require(statement["status"] == "Unreconciled", "Statement line has already been reconciled.")
        matches = d.get("matches")
        require(isinstance(matches, list) and 1 <= len(matches) <= 100,
                "Choose 1–100 recorded transactions.")
        allowed_collections = {"payments", "customerPayments", "partyFunds", "fundRefunds"}
        seen, selected = set(), []
        for match in matches:
            require(isinstance(match, dict) and set(match) == {"collection", "transaction"},
                    "Each bank match requires a transaction type and ID.")
            collection, transaction_id = match["collection"], match["transaction"]
            require(collection in allowed_collections, "Choose a supplier payment or customer receipt.")
            require((collection, transaction_id) not in seen, "Choose each transaction once.")
            seen.add((collection, transaction_id))
            transaction = get(s, collection, transaction_id)
            require(not transaction.get("reconciledStatement"), "A selected transaction is already reconciled.")
            require(transaction.get("status") != "Reversed", "Cannot reconcile a reversed transaction.")
            require(transaction.get("bankLedger") == statement["bankLedger"],
                    "A selected transaction uses a different bank ledger.")
            if collection == "partyFunds":
                expected = "credit" if transaction["side"] == "supplier" else "debit"
            elif collection == "fundRefunds":
                expected = "debit" if transaction["side"] == "supplier" else "credit"
            else:
                expected = "credit" if collection == "payments" else "debit"
            require(statement["direction"] == expected,
                    "A selected transaction has the wrong direction for this statement line.")
            selected.append((collection, transaction))
        require(sum((dec(transaction["amount"]) for _, transaction in selected), dec(0))
                == dec(statement["amount"]), "Selected transaction amounts must equal the statement amount exactly.")
        reconciliation = [dict(collection=collection, transaction=transaction["id"],
                               amount=transaction["amount"]) for collection, transaction in selected]
        statement.update(status="Reconciled", matches=reconciliation, reconciledBy=actor["id"])
        if len(reconciliation) == 1:
            statement.update(collection=reconciliation[0]["collection"],
                             transaction=reconciliation[0]["transaction"])
        for _, transaction in selected:
            transaction["reconciledStatement"] = statement["id"]
        return statement
    if action == "reconcileBank":
        statement = get(s, "bankStatements", d.get("statement"))
        voucher_date(s,statement["date"])
        require(statement["status"] == "Unreconciled", "Statement line has already been reconciled.")
        collection = d.get("collection")
        require(
            collection in {"payments", "customerPayments", "partyFunds", "fundRefunds"},
            "Choose a supplier payment or customer receipt.",
        )
        transaction = get(s, collection, d.get("transaction"))
        require(not transaction.get("reconciledStatement"), "Transaction has already been reconciled.")
        require(
            transaction.get("bankLedger") == statement["bankLedger"]
            and transaction["amount"] == statement["amount"],
            "Bank ledger or amount does not match the statement.",
        )
        require(transaction.get("status") != "Reversed", "Cannot reconcile a reversed transaction.")
        if collection == "partyFunds":
            expected = "credit" if transaction["side"] == "supplier" else "debit"
        elif collection == "fundRefunds":
            expected = "debit" if transaction["side"] == "supplier" else "credit"
        else:
            expected = "credit" if collection == "payments" else "debit"
        require(statement["direction"] == expected, "Statement direction does not match the transaction.")
        statement.update(
            status="Reconciled",
            transaction=transaction["id"],
            collection=collection,
            reconciledBy=actor["id"],
        )
        transaction["reconciledStatement"] = statement["id"]
        return statement
    if action == "asset":
        entry_date = voucher_date(s, d.get("date"))
        life = int(amount(d.get("lifeMonths"), True))
        require(1 <= life <= 1200, "Useful life must be 1–1200 months.")
        cost, residual = amount(d.get("cost"), True), amount(d.get("residual", 0))
        require(residual < cost, "Residual value must be below asset cost.")
        debit_name = account_name(s, d.get("assetAccount", "SYS-FA"))
        credit_name = account_name(s, d.get("creditAccount", "LED-BANK"))
        require(debit_name != credit_name, "Asset and funding accounts must differ.")
        r = dict(
            id=identifier(s, "AST"),
            name=text(d.get("name"), "Asset name", True),
            date=entry_date,
            cost=cost,
            residual=residual,
            lifeMonths=life,
            assetAccount=debit_name,
            accumulatedAccount=account_name(s, d.get("accumulatedAccount", "SYS-ACCDEP")),
            expenseAccount=account_name(s, d.get("expenseAccount", "SYS-DEP")),
            creditAccount=credit_name,
            accumulated=0,
            status="Active",
        )
        journal(
            s,
            r["id"],
            "Capitalised asset",
            [dict(account=debit_name, debit=cost), dict(account=credit_name, credit=cost)],
            entry_date,
        )
        from .accounting import add_months

        available = valid_date(d.get("availableDate") or entry_date)
        require(available >= entry_date, "Available-for-use date precedes acquisition.")
        r.update(
            depreciationPolicy="daily-straight-line",
            scheduleStart=available,
            scheduleEnd=add_months(available, life),
            scheduleBase=cost,
            scheduleAccumulated=0,
        )
        s["assets"].insert(0, r)
        return r
    if action == "depreciate":
        from .accounting import depreciate_asset

        period = voucher_date(s, d.get("periodEnd"))
        require(period <= today(), "Cannot depreciate into the future.")
        processed = []
        for asset in s["assets"]:
            if asset["status"] != "Active":
                continue
            require(
                asset.get("depreciationPolicy") == "daily-straight-line",
                "Reconcile legacy asset schedules before running depreciation.",
            )
            charge = depreciate_asset(s, asset, period)
            if charge:
                processed.append(dict(asset=asset["id"], amount=money(charge)))
        r = dict(
            id=identifier(s, "DPR"),
            periodEnd=period,
            date=period,
            charges=processed,
            amount=money(sum((dec(x["amount"]) for x in processed), dec(0))),
            status="Posted",
        )
        if processed:
            s["depreciationRuns"].insert(0, r)
        return r
    if action == "taxWorkpaper":
        start, end = valid_date(d.get("start")), valid_date(d.get("end"))
        require(start <= end <= today(), "Invalid tax period.")
        require(
            not any(x["start"] == start and x["end"] == end for x in s["taxReturns"]),
            "Tax workpaper already exists for this period.",
        )
        from .accounting_reports import tax_summary

        summary = tax_summary(s, start, end)
        output, input_tax = dec(summary["customer"]), dec(summary["supplier"])
        r = dict(
            id=identifier(s, "TAX"),
            start=start,
            end=end,
            date=end,
            outputTax=money(output),
            inputTax=money(input_tax),
            netTax=money(output - input_tax),
            status="Draft",
            regime=s["settings"]["taxRegime"],
        )
        s["taxReturns"].insert(0, r)
        return r
    if action == "closePeriod":
        through = valid_date(d.get("through"))
        require(
            through <= today()
            and (not s["settings"]["lockedThrough"] or through >= s["settings"]["lockedThrough"]),
            "Period close cannot move backwards or into the future.",
        )
        s["settings"]["lockedThrough"] = through
        return dict(id="PERIOD-" + through, through=through, status="Closed")
    if action == "closeYear":
        end = valid_date(d.get("end"))
        require(
            end <= today() and end <= s["settings"].get("lockedThrough", ""),
            "Close and lock the financial year first.",
        )
        from datetime import date, timedelta

        next_day = date.fromisoformat(end) + timedelta(days=1)
        boundary = next_day.strftime("%m-%d") == s["settings"].get("fiscalYearStart", "01-01")
        short_reason = text(d.get("shortYearReason", ""))
        require(
            boundary or short_reason,
            "Choose the configured year end, or give an explicit short-year justification.",
        )
        closes = s["settings"].setdefault("financialYearCloses", [])
        require(end not in closes, "Financial year has already been closed.")
        balances = account_balances(s, end)
        entries, net = [], dec(0)
        require(not closes or end > max(closes), "Year closes must be chronological.")
        for account in chart(s):
            value = balances.get(account["name"], dec(0))
            if account["type"] in {"revenue", "expense"} and value:
                entries.append(
                    dict(
                        account=account["name"],
                        debit=money(max(-value, dec(0))),
                        credit=money(max(value, dec(0))),
                    )
                )
                net -= value
        if net:
            entries.append(
                dict(
                    account="Retained earnings",
                    debit=money(max(-net, dec(0))),
                    credit=money(max(net, dec(0))),
                )
            )
        r = journal(s, "YEAR-" + end, "Financial year close", entries, end)
        r["manual"] = False
        r["yearClose"] = True
        r["shortYearReason"] = short_reason
        closes.append(end)
        return r
    if action in {"journal", "reverseJournal"}:
        entry_date = voucher_date(s, d.get("date"))
        reason = text(d.get("reason"), "Narration", True)
        if action == "reverseJournal":
            old = get(s, "journal", d["id"])
            require(
                old.get("manual") and not any(j.get("reversalOf") == old["id"] for j in s["journal"]),
                "Journal is not reversible.",
            )
            require(entry_date >= old["date"], "Reversal cannot precede original journal.")
            entries = [
                dict(account=e["account"], debit=e.get("credit", 0), credit=e.get("debit", 0))
                for e in old["entries"]
            ]
        else:
            require(
                isinstance(d.get("entries"), list) and 2 <= len(d["entries"]) <= 100,
                "Provide 2–100 journal lines.",
            )
            entries = []
            for line in d["entries"]:
                account = next((a for a in chart(s) if a["id"] == line.get("account")), None)
                require(account is not None, "Unknown account.")
                require(
                    not any(
                        l["name"] == account["name"]
                        and l.get("currency", s["settings"]["currency"]) != s["settings"]["currency"]
                        for l in s["ledgers"]
                    ),
                    "Use the foreign bank transaction workflow.",
                )
                require(
                    account["name"]
                    not in {
                        "Accounts payable",
                        "Accounts receivable",
                        "Supplier advances",
                        "Customer advances",
                        "Inventory asset",
                        "Goods received not invoiced",
                        "Work in progress",
                        "Delivered goods awaiting invoicing",
                    },
                    "Use the linked source workflow for control accounts.",
                )
                debit, credit = amount(line.get("debit") or 0), amount(line.get("credit") or 0)
                require((debit > 0) != (credit > 0), "Each line must contain one debit or credit.")
                require(
                    dec(debit) == dec(line.get("debit") or 0) and dec(credit) == dec(line.get("credit") or 0),
                    "Journal amounts support two decimals.",
                )
                entries.append(dict(account=account["name"], debit=debit, credit=credit))
        r = journal(s, text(d.get("reference", "Manual journal")), reason, entries, entry_date)
        r["manual"] = True
        if action == "reverseJournal":
            r["reversalOf"] = d["id"]
        return r
    if action in {"linkSubmission", "rejectSubmission"}:
        r = get(s, "portalSubmissions", d["id"])
        require(r["status"] == "Awaiting finance review", "Submission has already been reviewed.")
        if action == "rejectSubmission":
            r.update(status="Rejected", reviewNote=text(d.get("reason"), "Reason", True))
        else:
            invoice = get(s, "invoices", d["invoice"])
            require(
                invoice["status"] != "Void"
                and invoice["po"] == r["po"]
                and invoice["supplier"] == r["supplier"]
                and invoice["number"].casefold() == r["number"].casefold()
                and invoice["amount"] == r["amount"],
                "Voucher must match supplier, PO, reference and amount.",
            )
            r.update(status="Entered for matching", invoice=invoice["id"])
        r["reviewedBy"] = actor["id"]
        return r
    raise ValueError("Unknown action: " + action)


def reports(s, start, end):
    from .domain import valid_date

    require(valid_date(start) <= valid_date(end), "Invalid reporting period.")
    accounts = {a["name"]: dict(**a, opening=dec(0), debit=dec(0), credit=dec(0)) for a in chart(s)}
    for entry in s["journal"]:
        if entry["date"] > end:
            continue
        for line in entry["entries"]:
            a = accounts.setdefault(
                line["account"],
                dict(
                    id=line["account"],
                    name=line["account"],
                    type="unclassified",
                    opening=dec(0),
                    debit=dec(0),
                    credit=dec(0),
                ),
            )
            if entry["date"] < start:
                a["opening"] += dec(line.get("debit", 0)) - dec(line.get("credit", 0))
            else:
                a["debit"] += dec(line.get("debit", 0))
                a["credit"] += dec(line.get("credit", 0))
    trial = [
        dict(
            **{k: money(v) if k in {"opening", "debit", "credit"} else v for k, v in a.items()},
            closing=money(a["opening"] + a["debit"] - a["credit"]),
        )
        for a in accounts.values()
    ]
    total = lambda kind: money(sum(dec(a["closing"]) for a in trial if a["type"] == kind))
    account_types = {a["name"]: a["type"] for a in chart(s)}
    period = lambda kind: money(
        sum(
            (
                dec(l.get("debit", 0)) - dec(l.get("credit", 0))
                for j in s["journal"]
                if start <= j["date"] <= end and not j.get("yearClose")
                for l in j["entries"]
                if account_types.get(l["account"]) == kind
            ),
            dec(0),
        )
    )
    statement_lines = [x for x in s["bankStatements"] if start <= x["date"] <= end]
    assets = []
    for asset in s["assets"]:
        if asset["date"] > end:
            continue
        copy = dict(asset)
        if asset.get("depreciationPolicy") == "daily-straight-line":
            copy["accumulated"] = money(
                sum(
                    (
                        dec(l.get("credit", 0)) - dec(l.get("debit", 0))
                        for j in s["journal"]
                        if j["date"] <= end and j["reference"] == asset["id"]
                        for l in j["entries"]
                        if l["account"] == asset["accumulatedAccount"]
                    ),
                    dec(0),
                )
            )
            if asset.get("disposalDate") and asset["disposalDate"] <= end:
                copy["cost"] = 0
                copy["status"] = "Disposed"
            else:
                copy["status"] = (
                    "Fully depreciated"
                    if copy["accumulated"] >= copy["cost"] - copy["residual"]
                    else "Active"
                )
        assets.append(copy)
    from .accounting_reports import extended_reports, open_as_of

    return dict(
        **extended_reports(s, start, end),
        trial=trial,
        balanceDifference=money(sum(dec(a["closing"]) for a in trial)),
        profitAndLoss=dict(
            revenue=-period("revenue"),
            expenses=period("expense"),
            netProfit=money(-period("revenue") - period("expense")),
        ),
        balanceSheet=dict(
            assets=total("asset"),
            liabilities=-total("liability"),
            equity=-total("equity"),
            accumulatedResult=money(-total("revenue") - total("expense")),
        ),
        payables=[
            dict(
                id=i["id"],
                supplier=i["supplier"],
                due=i["due"],
                amount=i["amount"],
                balance=money(open_as_of(s, i, "supplier", end)),
            )
            for i in s["invoices"] + [i for i in s["accountingDocuments"] if i["side"] == "supplier"]
            if i["status"] in {"Posted", "Part paid", "Paid"} and i["date"] <= end
        ],
        receivables=[
            dict(
                id=i["id"],
                customer=i["customer"],
                due=i["due"],
                amount=i["amount"] if i.get("accountingDocument") else totals(i)["total"],
                balance=money(open_as_of(s, i, "customer", end)),
            )
            for i in s["salesInvoices"] + [i for i in s["accountingDocuments"] if i["side"] == "customer"]
            if i["status"] == "Posted" and i["date"] <= end
        ],
        bankReconciliation=dict(
            statementDebits=money(
                sum((dec(x["amount"]) for x in statement_lines if x["direction"] == "debit"), dec(0))
            ),
            statementCredits=money(
                sum((dec(x["amount"]) for x in statement_lines if x["direction"] == "credit"), dec(0))
            ),
            unreconciled=[
                dict(
                    id=x["id"],
                    date=x["date"],
                    reference=x["reference"],
                    amount=x["amount"],
                    direction=x["direction"],
                )
                for x in statement_lines
                if x["status"] == "Unreconciled"
            ],
        ),
        fixedAssets=[
            dict(
                id=x["id"],
                name=x["name"],
                cost=x["cost"],
                accumulated=x["accumulated"],
                netBookValue=money(dec(x["cost"]) - dec(x["accumulated"])),
                status=x["status"],
            )
            for x in assets
        ],
        taxWorkpapers=[x for x in s["taxReturns"] if start <= x["end"] <= end],
        commitments=[
            dict(
                id=o["id"],
                supplier=o["supplier"],
                due=o["due"],
                status=o["status"],
                amount=totals(o)["total"],
            )
            for o in s["orders"]
            if o["status"] not in {"Cancelled", "Closed"}
        ],
    )
