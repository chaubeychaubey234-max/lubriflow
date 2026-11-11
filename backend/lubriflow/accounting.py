"""Accounting extensions: immutable vouchers, schedules and auditable subledger allocations."""

from calendar import monthrange
from datetime import date, timedelta
from copy import deepcopy
from .domain import (
    require,
    dec,
    money,
    amount,
    text,
    get,
    active,
    identifier,
    voucher_date,
    valid_date,
    today,
    journal,
)

ACTIONS = set(
    "voucherType accountingVoucher reverseVoucher financeSchedule runFinanceSchedules cancelFinanceSchedule project financeBudget partyFunds allocateFunds refundFunds revalueFX disposeAsset reviseAsset enablePerpetual classifyCashFlow onAccountCredit resumeFinanceSchedule dubaiAccountingDefaults bankCurrency currencyTransfer accountingInvoice unmatchBank".split()
)
ACTIONS.add('bankAdjustment')
ACCOUNTS = [
    ('SYS-BANK-FEES', 'Bank charges', 'expense'),
    ('SYS-BANK-INTEREST', 'Bank interest income', 'revenue'),
    ('SYS-BANK-SUSPENSE', 'Unidentified bank entries', 'asset'),
    ("SYS-INV", "Inventory asset", "asset"),
    ("SYS-GRNI", "Goods received not invoiced", "liability"),
    ("SYS-COGS", "Cost of sales", "expense"),
    ("SYS-WIP", "Work in progress", "asset"),
    ("SYS-GIT", "Delivered goods awaiting invoicing", "asset"),
    ("SYS-CONV", "Production conversion clearing", "liability"),
    ("SYS-ADJ", "Inventory adjustments", "expense"),
    ("SYS-PPV", "Purchase price variance", "expense"),
    ("SYS-ADV-S", "Supplier advances", "asset"),
    ("SYS-ADV-C", "Customer advances", "liability"),
    ("SYS-FX", "Foreign exchange differences", "expense"),
    ("SYS-DISP", "Asset disposal result", "expense"),
    ("SYS-OPEN", "Opening balance equity", "equity"),
    ("SYS-PREPAID", "Prepayments", "asset"),
    ("SYS-ACCRUAL", "Accrued expenses", "liability"),
]


def add_months(value, months):
    d = date.fromisoformat(value)
    total = d.year * 12 + d.month - 1 + months
    y, m = divmod(total, 12)
    return date(y, m + 1, min(d.day, monthrange(y, m + 1)[1])).isoformat()


def fx(s, currency, day, supplied=None):
    require(isinstance(currency, str), "Currency must be a code.")
    currency = currency.upper()
    if supplied == "":
        supplied = None
    require(len(currency) == 3 and currency.isalpha(), "Use a three-letter currency code.")
    if currency == s["settings"]["currency"]:
        require(supplied is None or dec(supplied) == 1, "Base currency rate must be one.")
        return dec(1)
    if supplied is not None:
        value = dec(supplied)
    else:
        candidates = [
            r
            for r in s["exchangeRates"]
            if r["fromCurrency"] == currency
            and r["toCurrency"] == s["settings"]["currency"]
            and r["date"] <= day
        ]
        require(candidates, "Enter an exchange rate before posting this currency.")
        value = dec(max(candidates, key=lambda r: r["date"])["rate"])
    require(value > 0 and value <= dec("1000000"), "Exchange rate must be positive and bounded.")
    return value


def dimensions(s, line):
    result = {}
    for key, collection in [("costCentre", "costCentres"), ("project", "projects")]:
        if line.get(key):
            result[key] = active(s, collection, line[key])["id"]
    return result


def normalized_entries(s, entries):
    from .finance import account_name

    require(isinstance(entries, list) and 2 <= len(entries) <= 100, "Provide 2–100 lines.")
    out = []
    for line in entries:
        debit, credit = amount(line.get("debit", 0)), amount(line.get("credit", 0))
        require((debit > 0) != (credit > 0), "Each line must have exactly one positive debit or credit.")
        require(
            dec(debit) == dec(line.get("debit", 0)) and dec(credit) == dec(line.get("credit", 0)),
            "Amounts support two decimal places.",
        )
        out.append(
            dict(account=account_name(s, line["account"]), debit=debit, credit=credit, **dimensions(s, line))
        )
    require(sum((dec(x["debit"]) - dec(x["credit"]) for x in out), dec(0)) == 0, "Voucher is not balanced.")
    return out


def translated(entries, rate):
    out = [
        dict(x, debit=money(dec(x.get("debit", 0)) * rate), credit=money(dec(x.get("credit", 0)) * rate))
        for x in entries
    ]
    difference = sum((dec(x["debit"]) - dec(x["credit"]) for x in out), dec(0))
    if difference:
        out.append(
            dict(
                account="Rounding",
                debit=money(max(-difference, dec(0))),
                credit=money(max(difference, dec(0))),
            )
        )
    return out


def post(s, reference, description, entries, day, **meta):
    voucher_date(s, day)
    r = journal(s, reference, description, entries, day)
    r.update(meta)
    return r


def invoice_open(s, side, key):
    from .domain import balance, POSTED
    from .sales import receivable

    collection = "invoices" if side == "supplier" else "salesInvoices"
    inv = next((i for i in s[collection] if i["id"] == key), None)
    if inv is None:
        inv = get(s, "accountingDocuments", key)
        require(inv["side"] == side, "Invoice party type does not match.")
    require(inv["status"] in (POSTED if side == "supplier" else {"Posted"}), "Invoice is not posted.")
    if inv.get("accountingDocument"):
        return inv, dec(inv["amount"]) - allocated(s, inv["id"], side)
    return inv, dec(balance(s, inv) if side == "supplier" else receivable(s, inv))


def allocated(s, invoice, side, end="9999-12-31"):
    return sum(
        (
            dec(a["amount"])
            for a in s["fundAllocations"]
            if a["invoice"] == invoice and a["side"] == side and a["date"] <= end
        ),
        dec(0),
    )


def remaining_funds(s, fund, end="9999-12-31"):
    return (
        dec(fund["amount"])
        - sum(
            (dec(a["amount"]) for a in s["fundAllocations"] if a["fund"] == fund["id"] and a["date"] <= end),
            dec(0),
        )
        - sum(
            (dec(r["amount"]) for r in s["fundRefunds"] if r["fund"] == fund["id"] and r["date"] <= end),
            dec(0),
        )
    )


def action(s, command, d, actor):
    from .finance import account_name, active_ledger

    require(actor["role"] in {"admin", "finance"}, "Finance access required.")
    if command == 'bankAdjustment':
        statement = get(s, 'bankStatements', d.get('statement'))
        require(statement['status'] == 'Unreconciled', 'Unmatch the statement before posting an adjustment.')
        day = voucher_date(s, statement['date'])
        bank = active_ledger(s, statement['bankLedger'])
        require(bank.get('currency', s['settings']['currency']) == s['settings']['currency'],
                'This adjustment workflow currently supports base-currency bank accounts only.')
        kind = d.get('kind')
        require(kind in {'charge', 'interest', 'unidentified'}, 'Choose charge, interest or unidentified.')
        require(kind != 'charge' or statement['direction'] == 'credit', 'A bank charge must be money out.')
        require(kind != 'interest' or statement['direction'] == 'debit', 'Interest income must be money in.')
        prior = statement.get('adjustmentJournal')
        require(not prior or any(j.get('reversalOf') == prior for j in s['journal']),
                'Reverse the existing adjustment before posting a replacement.')
        reason = text(d.get('reason'), 'Posting explanation', True)
        account = account_name(s, {'charge': 'SYS-BANK-FEES', 'interest': 'SYS-BANK-INTEREST',
                                  'unidentified': 'SYS-BANK-SUSPENSE'}[kind])
        value = statement['amount']
        incoming = statement['direction'] == 'debit'
        entry = post(s, statement['id'], reason,
            [dict(account=bank['name'], debit=value if incoming else 0, credit=0 if incoming else value),
             dict(account=account, debit=0 if incoming else value, credit=value if incoming else 0)], day,
            accountingVoucher=True, bankAdjustment=kind, bankStatement=statement['id'])
        entry['reconciledStatement'] = statement['id']
        statement.update(status='Reconciled', collection='journal', transaction=entry['id'],
                         adjustmentJournal=entry['id'], reconciledBy=actor['id'],
                         matches=[dict(collection='journal', transaction=entry['id'], amount=value)])
        return entry
    if command == "unmatchBank":
        statement=get(s,"bankStatements",d["statement"])
        require(statement["status"]=="Reconciled","Statement is not reconciled.")
        voucher_date(s,statement["date"])
        day=voucher_date(s,d.get("date"))
        require(day>=statement["date"],"Unmatch date precedes statement.")
        if statement.get('splitStatements'):
            transaction = get(s, statement['collection'], statement['transaction'])
            ids = statement['splitStatements']
            require(transaction.get('reconciledStatements') == ids, 'Reconciliation links are inconsistent.')
            reason = text(d.get('reason'), 'Unmatch reason', True)
            for key in ids:
                row = get(s, 'bankStatements', key)
                voucher_date(s, row['date'])
                require(day >= row['date'], 'Unmatch date precedes a linked statement.')
                require(row.get('splitStatements') == ids and row.get('transaction') == transaction['id']
                        and row.get('collection') == statement['collection'] and row['status'] == 'Reconciled',
                        'Reconciliation links are inconsistent.')
            for key in ids:
                row = get(s, 'bankStatements', key)
                row.setdefault('matchHistory', []).append(dict(matches=deepcopy(row['matches']),
                    splitStatements=list(ids), matchedBy=row.get('reconciledBy'), unmatchedBy=actor['id'], date=day, reason=reason))
                for field in ('transaction', 'collection', 'matches', 'reconciledBy', 'splitStatements'):
                    row.pop(field, None)
                row['status'] = 'Unreconciled'
            transaction.pop('reconciledStatement', None)
            transaction.pop('reconciledStatements', None)
            return statement
        matches = statement.get("matches") or [dict(collection=statement["collection"],
                                                     transaction=statement["transaction"],
                                                     amount=statement["amount"])]
        transactions=[]
        for match in matches:
            transaction=get(s,match["collection"],match["transaction"])
            require(transaction.get("reconciledStatement")==statement["id"],"Reconciliation links are inconsistent.")
            transactions.append(transaction)
        reason=text(d.get("reason"),"Unmatch reason",True)
        statement.setdefault("matchHistory",[]).append(dict(matches=deepcopy(matches),
            transaction=matches[0]["transaction"] if len(matches)==1 else "", collection=matches[0]["collection"] if len(matches)==1 else "",
            matchedBy=statement.get("reconciledBy"),unmatchedBy=actor["id"],date=day,reason=reason))
        for transaction in transactions:transaction.pop("reconciledStatement")
        for key in ("transaction","collection","matches","reconciledBy"):statement.pop(key,None)
        statement["status"]="Unreconciled"
        return statement
    if command in {"bankCurrency", "currencyTransfer"}:
        from .foreign_banking import action as bank_action

        return bank_action(s, command, d, actor)
    if command == "dubaiAccountingDefaults":
        require(
            not s["journal"]
            and not s["invoices"]
            and not s["salesInvoices"]
            and not s["orders"]
            and not s["stockMoves"],
            "Apply regional defaults before business transactions.",
        )
        s["settings"].update(currency="AED", country="AE", timezone="Asia/Dubai", fiscalYearStart="01-01")
        return dict(id="AE-ACCOUNTING", currency="AED", fiscalYearStart="01-01")
    if command == "classifyCashFlow":
        r = get(s, "journal", d["id"])
        value = d.get("classification")
        require(value in {"Operating", "Investing", "Financing"}, "Choose a cash-flow class.")
        r.setdefault("classificationHistory", []).append(
            dict(
                previous=r.get("cashFlowClass", "Unclassified"),
                classification=value,
                actor=actor["id"],
                reason=text(d.get("reason"), "Classification reason", True),
            )
        )
        r["cashFlowClass"] = value
        return r
    if command == "project":
        r = dict(id=identifier(s, "PRJ"), name=text(d.get("name"), "Project name", True), active=True)
        s["projects"].append(r)
        return r
    if command == "voucherType":
        name = text(d.get("name"), "Voucher type", True)
        require(
            not any(t["name"].casefold() == name.casefold() for t in s["voucherTypes"]),
            "Voucher type already exists.",
        )
        family = d.get("family", "journal")
        require(
            family
            in {"journal", "contra", "payment", "receipt", "sales", "purchase", "credit", "debit", "opening"},
            "Invalid voucher family.",
        )
        r = dict(id=identifier(s, "VT"), name=name, family=family, active=True)
        s["voucherTypes"].append(r)
        return r
    if command in {"accountingVoucher", "reverseVoucher"}:
        day = voucher_date(s, d.get("date"))
        if command == "reverseVoucher":
            old = get(s, "journal", d["id"])
            require(not old.get('reconciledStatement'), 'Unmatch the bank statement before reversing its adjustment.')
            require(
                old.get("accountingVoucher")
                and not any(j.get("reversalOf") == old["id"] for j in s["journal"]),
                "Only unreversed accounting vouchers can be reversed here.",
            )
            require(day >= old["date"], "Reversal precedes voucher.")
            entries = [dict(x, debit=x.get("credit", 0), credit=x.get("debit", 0)) for x in old["entries"]]
            return post(
                s,
                old["reference"],
                text(d.get("reason"), "Reason", True),
                entries,
                day,
                reversalOf=old["id"],
                accountingVoucher=True,
            )
        entries = normalized_entries(s, d.get("entries"))
        kind = (
            active(s, "voucherTypes", d["voucherType"])
            if d.get("voucherType")
            else dict(id="journal", family="journal")
        )
        # Control accounts are maintained by their source workflows; manual postings would orphan balances.
        restricted = {
            "Accounts payable",
            "Accounts receivable",
            "Supplier advances",
            "Customer advances",
            "Inventory asset",
            "Goods received not invoiced",
            "Work in progress",
            "Delivered goods awaiting invoicing",
        }
        require(
            not any(x["account"] in restricted for x in entries),
            "Use the linked invoice, settlement or inventory workflow for control accounts.",
        )
        require(
            not any(
                e["account"] == l["name"]
                for e in entries
                for l in s["ledgers"]
                if l.get("currency", s["settings"]["currency"]) != s["settings"]["currency"]
            ),
            "Use the currency transfer or party funds workflow for foreign banks.",
        )
        banks = {l["name"] for l in s["ledgers"] if l["type"] in {"cash", "bank"}}
        if kind["family"] == "contra":
            require(
                all(x["account"] in banks for x in entries), "Contra vouchers use only cash/bank accounts."
            )
        if kind["family"] == "payment":
            require(
                any(x["account"] in banks and x["credit"] for x in entries),
                "Payment needs a bank/cash credit.",
            )
        if kind["family"] == "receipt":
            require(
                any(x["account"] in banks and x["debit"] for x in entries), "Receipt needs a bank/cash debit."
            )
        currency = text((d.get("currency") or s["settings"]["currency"])).upper()
        rate = fx(s, currency, day, d.get("rate"))
        ref = text(d.get("reference"), "Reference", True)
        require(
            not any(
                j.get("accountingVoucher") and j["reference"].casefold() == ref.casefold()
                for j in s["journal"]
            ),
            "Voucher reference already used.",
        )
        return post(
            s,
            ref,
            text(d.get("reason"), "Narration", True),
            translated(entries, rate),
            day,
            accountingVoucher=True,
            voucherType=kind["id"],
            family=kind["family"],
            currency=currency,
            rate=str(rate),
            foreignEntries=entries,
        )
    if command == "financeBudget":
        start, end = valid_date(d["start"]), valid_date(d["end"])
        require(start <= end, "Invalid budget period.")
        dims = dimensions(s, d)
        require(dims, "Choose a cost centre or project.")
        account = account_name(s, d["account"])
        value = amount(d["amount"])
        require(
            not any(
                b["account"] == account
                and all(b.get(k) == dims.get(k) for k in ("project", "costCentre"))
                and b["start"] <= end
                and b["end"] >= start
                for b in s["financeBudgets"]
            ),
            "Overlapping budget exists.",
        )
        r = dict(id=identifier(s, "BUD"), account=account, start=start, end=end, amount=value, **dims)
        s["financeBudgets"].append(r)
        return r
    if command == "accountingInvoice":
        from .finance import chart

        side = d.get("side")
        require(side in {"supplier", "customer"}, "Choose supplier or customer.")
        party = active(s, "suppliers" if side == "supplier" else "customers", d["party"])
        day = voucher_date(s, d.get("date"))
        due = valid_date(d.get("due") or day)
        require(due >= day, "Due date precedes invoice.")
        reference = text(d.get("reference"), "Invoice reference", True)
        require(
            not any(
                i["side"] == side
                and i[side] == party["id"]
                and i["number"].casefold() == reference.casefold()
                for i in s["accountingDocuments"]
            ),
            "Duplicate accounting invoice reference.",
        )
        net = amount(d["amount"], True)
        tax = amount(d.get("taxAmount", 0))
        total = money(dec(net) + dec(tax))
        currency = (d.get("currency") or s["settings"]["currency"]).upper()
        rate = fx(s, currency, day, d.get("rate"))
        account = account_name(s, d["account"])
        require(
            next(x["type"] for x in chart(s) if x["name"] == account)
            == ("expense" if side == "supplier" else "revenue"),
            "Choose an expense or revenue account.",
        )
        r = dict(
            id=identifier(s, "AINV"),
            side=side,
            **{side: party["id"]},
            accountingDocument=True,
            number=reference,
            date=day,
            due=due,
            amount=total,
            net=net,
            taxAmount=tax,
            currency=currency,
            rate=str(rate),
            status="Posted",
            reason=text(d.get("reason"), "Description", True),
            **dimensions(s, d),
        )
        entries = (
            [
                dict(account=account, debit=net),
                dict(account="Input tax", debit=tax),
                dict(account="Accounts payable", credit=total),
            ]
            if side == "supplier"
            else [
                dict(account="Accounts receivable", debit=total),
                dict(account=account, credit=net),
                dict(account="Output tax", credit=tax),
            ]
        )
        post(s, r["id"], "Service / non-stock invoice", translated(entries, rate), day)
        s["accountingDocuments"].append(r)
        return r
    if command == "onAccountCredit":
        from .finance import chart

        side = d.get("side")
        require(side in {"supplier", "customer"}, "Choose a party type.")
        party = active(s, "suppliers" if side == "supplier" else "customers", d["party"])
        day = voucher_date(s, d.get("date"))
        net = amount(d["amount"], True)
        tax = amount(d.get("taxAmount", 0))
        currency = (d.get("currency") or s["settings"]["currency"]).upper()
        rate = fx(s, currency, day, d.get("rate"))
        ref = text(d.get("reference"), "Credit note reference", True)
        require(
            not any(f["reference"].casefold() == ref.casefold() for f in s["partyFunds"]),
            "Reference already recorded.",
        )
        account = account_name(s, d["account"])
        require(
            next(x["type"] for x in chart(s) if x["name"] == account)
            == ("expense" if side == "supplier" else "revenue"),
            "Choose the relevant expense or revenue account.",
        )
        value = money(dec(net) + dec(tax))
        r = dict(
            id=identifier(s, "FUND"),
            side=side,
            party=party["id"],
            date=day,
            amount=value,
            currency=currency,
            rate=str(rate),
            reference=ref,
            status="Recorded",
            onAccountCredit=True,
            net=net,
            taxAmount=tax,
            reason=text(d.get("reason"), "Credit justification", True),
        )
        entries = (
            [
                dict(account="Supplier advances", debit=value),
                dict(account=account, credit=net),
                dict(account="Input tax", credit=tax),
            ]
            if side == "supplier"
            else [
                dict(account=account, debit=net),
                dict(account="Output tax", debit=tax),
                dict(account="Customer advances", credit=value),
            ]
        )
        post(s, r["id"], "On-account credit", translated(entries, rate), day)
        s["partyFunds"].append(r)
        return r
    if command == "partyFunds":
        side = d.get("side")
        require(side in {"supplier", "customer"}, "Choose supplier or customer.")
        party = active(s, "suppliers" if side == "supplier" else "customers", d["party"])
        day = voucher_date(s, d.get("date"))
        value = amount(d["amount"], True)
        currency = text((d.get("currency") or s["settings"]["currency"])).upper()
        rate = fx(s, currency, day, d.get("rate"))
        bank = active_ledger(s, d.get("bankLedger", "LED-BANK"))
        ref = text(d.get("reference"), "External payment reference", True)
        require(
            not any(f["reference"].casefold() == ref.casefold() for f in s["partyFunds"]),
            "Funds reference already recorded.",
        )
        r = dict(
            id=identifier(s, "FUND"),
            side=side,
            party=party["id"],
            date=day,
            amount=value,
            currency=currency,
            rate=str(rate),
            bankLedger=bank["id"],
            reference=ref,
            status="Recorded",
        )
        base = money(dec(value) * rate)
        advance = "Supplier advances" if side == "supplier" else "Customer advances"
        entries = (
            [dict(account=advance, debit=base), dict(account=bank["name"], credit=base)]
            if side == "supplier"
            else [dict(account=bank["name"], debit=base), dict(account=advance, credit=base)]
        )
        from .foreign_banking import adjust

        adjust(
            s, entries, bank, currency, -dec(value) if side == "supplier" else dec(value), base, day, r["id"]
        )
        post(
            s,
            r["id"],
            "Supplier advance/payment" if side == "supplier" else "Customer advance/receipt",
            entries,
            day,
        )
        s["partyFunds"].append(r)
        return r
    if command == "allocateFunds":
        fund = get(s, "partyFunds", d["fund"])
        day = voucher_date(s, d.get("date"))
        require(day >= fund["date"], "Allocation precedes funds.")
        require(
            not any(
                x["fund"] == fund["id"] and x["date"] > day for x in s["fundAllocations"] + s["fundRefunds"]
            ),
            "Funds transactions must be chronological.",
        )
        allocations = d.get("allocations")
        require(
            isinstance(allocations, list) and 1 <= len(allocations) <= 100, "Provide invoice allocations."
        )
        require(
            len({a["invoice"] for a in allocations}) == len(allocations),
            "Combine duplicate invoice allocations.",
        )
        require(
            sum((dec(a["amount"]) for a in allocations), dec(0)) <= remaining_funds(s, fund),
            "Allocations exceed unallocated funds.",
        )
        result = []
        for a in allocations:
            inv, outstanding = invoice_open(s, fund["side"], a["invoice"])
            value = amount(a["amount"], True)
            require(
                inv[fund["side"]] == fund["party"] and day >= inv["date"],
                "Invoice party/date does not match.",
            )
            require(
                inv.get("currency", s["settings"]["currency"]) == fund["currency"],
                "Funds and invoice currency must match.",
            )
            require(dec(value) <= outstanding, "Allocation exceeds invoice balance.")
            require(
                not any(
                    r["date"] > day and any(x["invoice"] == inv["id"] for x in r["items"])
                    for r in s["fxRevaluations"]
                ),
                "Allocation cannot precede a later FX revaluation.",
            )
            inv_rate = carrying_rate(s, inv, day)
            fund_rate = dec(fund["rate"])
            carrying = (
                money(invoice_carrying_base(s, inv, fund["side"], day))
                if dec(value) == outstanding
                else money(dec(value) * inv_rate)
            )
            funding = (
                money(fund_carrying_base(s, fund, day))
                if dec(value) == remaining_funds(s, fund, day)
                else money(dec(value) * fund_rate)
            )
            debit, credit = (
                ("Accounts payable", "Supplier advances")
                if fund["side"] == "supplier"
                else ("Customer advances", "Accounts receivable")
            )
            dv, cv = (carrying, funding) if fund["side"] == "supplier" else (funding, carrying)
            entries = [dict(account=debit, debit=dv), dict(account=credit, credit=cv)]
            delta = dec(cv) - dec(dv)
            if delta:
                entries.append(
                    dict(
                        account="Foreign exchange differences",
                        debit=money(max(delta, dec(0))),
                        credit=money(max(-delta, dec(0))),
                    )
                )
            r = dict(
                id=identifier(s, "ALLOC"),
                fund=fund["id"],
                invoice=inv["id"],
                side=fund["side"],
                date=day,
                amount=value,
                carryingBase=carrying,
                fundingBase=funding,
            )
            post(s, r["id"], "Invoice allocation", entries, day)
            s["fundAllocations"].append(r)
            result.append(r)
            if fund["side"] == "supplier":
                from .domain import invoice_status

                invoice_status(s, inv)
        return dict(id=fund["id"], allocations=result)
    if command == "refundFunds":
        fund = get(s, "partyFunds", d["fund"])
        day = voucher_date(s, d.get("date"))
        value = amount(d["amount"], True)
        require(
            day >= fund["date"] and dec(value) <= remaining_funds(s, fund),
            "Refund exceeds unallocated funds or precedes receipt.",
        )
        require(
            not any(
                x["fund"] == fund["id"] and x["date"] > day for x in s["fundAllocations"] + s["fundRefunds"]
            ),
            "Funds transactions must be chronological.",
        )
        bank = active_ledger(s, d.get("bankLedger", fund.get("bankLedger", "LED-BANK")))
        rate = fx(s, fund["currency"], day, d.get("rate"))
        reference = text(d.get("reference"), "Refund reference", True)
        require(
            not any(x["reference"].casefold() == reference.casefold() for x in s["fundRefunds"]),
            "Refund reference already recorded.",
        )
        base = (
            money(fund_carrying_base(s, fund, day))
            if dec(value) == remaining_funds(s, fund, day)
            else money(dec(value) * dec(fund["rate"]))
        )
        cash = money(dec(value) * rate)
        advance = "Supplier advances" if fund["side"] == "supplier" else "Customer advances"
        entries = (
            [dict(account=bank["name"], debit=cash), dict(account=advance, credit=base)]
            if fund["side"] == "supplier"
            else [dict(account=advance, debit=base), dict(account=bank["name"], credit=cash)]
        )
        diff = sum((dec(e.get("debit", 0)) - dec(e.get("credit", 0)) for e in entries), dec(0))
        if diff:
            entries.append(
                dict(
                    account="Foreign exchange differences",
                    debit=money(max(-diff, dec(0))),
                    credit=money(max(diff, dec(0))),
                )
            )
        r = dict(
            id=identifier(s, "REFUND"),
            fund=fund["id"],
            date=day,
            amount=value,
            reference=reference,
            reason=text(d.get("reason"), "Reason", True),
            carryingBase=base,
            bankLedger=bank["id"],
            side=fund["side"],
        )
        from .foreign_banking import adjust

        adjust(
            s,
            entries,
            bank,
            fund["currency"],
            dec(value) if fund["side"] == "supplier" else -dec(value),
            cash,
            day,
            r["id"],
        )
        post(s, r["id"], "Advance refund", entries, day)
        s["fundRefunds"].append(r)
        return r
    if command == "financeSchedule":
        kind = d.get("kind", "recurring")
        require(kind in {"recurring", "accrual", "prepayment"}, "Choose a schedule type.")
        start = valid_date(d["start"])
        count = int(d.get("months", 1))
        require(1 <= count <= 120, "Use 1–120 periods.")
        entries = normalized_entries(s, d["entries"])
        # Route through the same restriction checks used for manual vouchers when running.
        r = dict(
            id=identifier(s, "SCH"),
            kind=kind,
            name=text(d.get("name"), "Name", True),
            start=start,
            months=count,
            entries=entries,
            status="Active",
            runs=[],
            currency=s["settings"]["currency"],
            automatic=d.get("executionMode") == "automatic",
            authorisedBy=actor["id"],
        )
        if kind == "accrual":
            r["reverseDate"] = valid_date(d["reverseDate"])
            require(r["reverseDate"] > start, "Reversal must follow accrual.")
            r["months"] = 1
        if kind == "prepayment":
            require(
                any(e["account"] == "Prepayments" and e["credit"] for e in entries),
                "Prepayment schedule must credit the prepaid asset; book the initial payment separately.",
            )
        s["financeSchedules"].append(r)
        return r
    if command == "resumeFinanceSchedule":
        r = get(s, "financeSchedules", d["id"])
        require(r["status"] == "Attention", "Only held schedules can be resumed.")
        r.update(
            status="Active",
            authorisedBy=actor["id"],
            lastError="",
            resumeReason=text(d.get("reason"), "Resolution", True),
        )
        return r
    if command == "cancelFinanceSchedule":
        r = get(s, "financeSchedules", d["id"])
        require(r["status"] == "Active", "Schedule is not active.")
        r.update(status="Cancelled", reason=text(d.get("reason"), "Reason", True))
        return r
    if command == "runFinanceSchedules":
        through = valid_date(d.get("through") or today())
        require(through <= today(), "Cannot post schedules into the future.")
        done = []
        for sch in s["financeSchedules"]:
            if sch["status"] != "Active" or (d.get("id") and sch["id"] != d["id"]):
                continue
            dates = [add_months(sch["start"], i) for i in range(sch["months"])]
            if sch["kind"] == "accrual":
                dates.append(sch["reverseDate"])
            for i, day in enumerate(dates):
                if day > through or any(x["period"] == i for x in sch["runs"]):
                    continue
                entries = deepcopy(sch["entries"])
                if sch["kind"] == "accrual" and i == 1:
                    entries = [dict(e, debit=e["credit"], credit=e["debit"]) for e in entries]
                voucher = action(
                    s,
                    "accountingVoucher",
                    dict(date=day, entries=entries, reference=sch["id"] + "/" + str(i), reason=sch["name"]),
                    actor,
                )
                sch["runs"].append(dict(period=i, date=day, journal=voucher["id"]))
                done.append(voucher["id"])
            if len(sch["runs"]) == len(dates):
                sch["status"] = "Completed"
        return dict(id="SCHEDULE-RUN", journals=done)
    if command == "revalueFX":
        day = voucher_date(s, d.get("date"))
        require(day <= today(), "Cannot revalue into the future.")
        require(
            not any(r["date"] >= day for r in s["fxRevaluations"]),
            "Revaluations must be chronological and unique per date.",
        )
        entries = []
        items = []
        for side, collection in [("supplier", "invoices"), ("customer", "salesInvoices")]:
            for inv in s[collection] + [i for i in s["accountingDocuments"] if i["side"] == side]:
                if inv["date"] > day or inv["status"] not in {"Posted", "Part paid", "Paid"}:
                    continue
                currency = inv.get("currency", s["settings"]["currency"])
                if currency == s["settings"]["currency"]:
                    continue
                # Avoid rewriting a carrying amount after later settlements.
                require(
                    not any(a["invoice"] == inv["id"] and a["date"] > day for a in s["fundAllocations"]),
                    "Revalue before posting later allocations.",
                )
                require(
                    not any(
                        a["invoice"] == inv["id"] and a["date"] > day
                        for a in s["credits" if side == "supplier" else "customerCredits"]
                    ),
                    "Revalue before posting later credits.",
                )
                _, outstanding = invoice_open(s, side, inv["id"])
                new = fx(s, currency, day)
                old = carrying_rate(s, inv, day)
                delta = dec(money(outstanding * new)) - invoice_carrying_base(s, inv, side, day)
                items.append(
                    dict(
                        invoice=inv["id"],
                        side=side,
                        amount=money(outstanding),
                        rate=str(new),
                        previousRate=str(old),
                        difference=money(delta),
                    )
                )
                if not delta:
                    continue
                value = delta if side == "customer" else -delta
                entries.extend(
                    [
                        dict(
                            account="Accounts receivable" if side == "customer" else "Accounts payable",
                            debit=money(max(value, dec(0))),
                            credit=money(max(-value, dec(0))),
                        ),
                        dict(
                            account="Foreign exchange differences",
                            debit=money(max(-value, dec(0))),
                            credit=money(max(value, dec(0))),
                        ),
                    ]
                )
        from .foreign_banking import revalue

        bank_entries, banks = revalue(s, day)
        entries.extend(bank_entries)
        r = dict(id=identifier(s, "FXR"), date=day, items=items, banks=banks)
        if entries:
            post(s, r["id"], "Period-end FX revaluation", entries, day)
        s["fxRevaluations"].append(r)
        return r
    if command in {"disposeAsset", "reviseAsset"}:
        asset = get(s, "assets", d["id"])
        day = voucher_date(s, d.get("date"))
        require(
            asset["status"] in {"Active", "Fully depreciated"} and day >= asset["date"],
            "Asset unavailable or invalid date.",
        )
        require(
            not asset.get("depreciatedThrough") or day >= asset["depreciatedThrough"],
            "Asset action predates depreciation.",
        )
        require(
            asset.get("depreciationPolicy") == "daily-straight-line",
            "Legacy assets need an opening schedule reconciliation before adjustment.",
        )
        depreciate_asset(s, asset, day)
        if command == "reviseAsset":
            residual = amount(d["residual"])
            life = int(d["remainingMonths"])
            net = money(dec(asset["cost"]) - dec(asset["accumulated"]))
            require(1 <= life <= 1200 and residual <= net, "Invalid remaining life or residual.")
            asset.setdefault("revisions", []).append(
                dict(
                    date=day,
                    previousResidual=asset["residual"],
                    previousEnd=asset["scheduleEnd"],
                    reason=text(d.get("reason"), "Reason", True),
                )
            )
            asset.update(
                residual=residual,
                scheduleStart=(date.fromisoformat(day) + timedelta(days=1)).isoformat(),
                scheduleEnd=add_months(day, life),
                scheduleBase=net,
                scheduleAccumulated=asset["accumulated"],
                status="Active",
            )
            return asset
        proceeds = amount(d.get("proceeds", 0))
        bank = active_ledger(s, d.get("bankLedger", "LED-BANK"))
        entries = [
            dict(account=asset["assetAccount"], credit=asset["cost"]),
            dict(account=asset["accumulatedAccount"], debit=asset["accumulated"]),
        ]
        if proceeds:
            entries.append(dict(account=bank["name"], debit=proceeds))
        diff = dec(asset["cost"]) - dec(asset["accumulated"]) - dec(proceeds)
        if diff:
            entries.append(
                dict(
                    account="Asset disposal result",
                    debit=money(max(diff, dec(0))),
                    credit=money(max(-diff, dec(0))),
                )
            )
        post(s, asset["id"], "Asset disposal", entries, day)
        asset.update(
            status="Disposed",
            disposalDate=day,
            proceeds=proceeds,
            disposalReason=text(d.get("reason"), "Reason", True),
        )
        return asset
    if command == "enablePerpetual":
        require(not s["settings"].get("perpetualAccounting"), "Perpetual accounting is already active.")
        require(
            not s["journal"] and not s["stockMoves"] and not s["invoices"] and not s["productionOrders"],
            "Existing companies require reconciled migration before enabling perpetual accounting.",
        )
        from .inventory import ensure_positions

        for item in s["items"]:
            ensure_positions(s, item)
        require(
            not any(p["costBasis"] == "Provisional opening item price" for p in s["stockPositions"]),
            "Confirm all opening stock values first.",
        )
        day = voucher_date(s, d.get("date"))
        value = money(sum((dec(p["value"]) for p in s["stockPositions"]), dec(0)))
        if value:
            post(
                s,
                "OPEN-INVENTORY",
                "Reconciled opening inventory",
                [
                    dict(account="Inventory asset", debit=value),
                    dict(account="Opening balance equity", credit=value),
                ],
                day,
            )
        s["settings"]["perpetualAccounting"] = True
        s["settings"]["perpetualStart"] = day
        return dict(id="PERPETUAL", date=day, value=value)
    raise ValueError("Unknown accounting action.")


def carrying_rate(s, invoice, day):
    candidates = [
        (r["date"], i["rate"])
        for r in s["fxRevaluations"]
        if invoice["date"] <= r["date"] <= day
        for i in r["items"]
        if i["invoice"] == invoice["id"]
    ]
    return dec(max(candidates)[1]) if candidates else dec(invoice.get("rate", 1))


def depreciate_asset(s, asset, through):
    require(
        not asset.get("depreciatedThrough") or through >= asset["depreciatedThrough"],
        "Cannot backdate depreciation.",
    )
    if asset["status"] != "Active" or through < asset["scheduleStart"]:
        return dec(0)
    start = date.fromisoformat(asset["scheduleStart"])
    end = date.fromisoformat(asset["scheduleEnd"])
    elapsed = max(0, min((date.fromisoformat(through) - start).days + 1, (end - start).days))
    target = dec(
        money((dec(asset["scheduleBase"]) - dec(asset["residual"])) * dec(elapsed) / dec((end - start).days))
    )
    charged = dec(asset["accumulated"]) - dec(asset.get("scheduleAccumulated", 0))
    delta = target - charged
    if delta > 0:
        post(
            s,
            asset["id"],
            "Daily straight-line depreciation",
            [
                dict(account=asset["expenseAccount"], debit=money(delta)),
                dict(account=asset["accumulatedAccount"], credit=money(delta)),
            ],
            through,
        )
        asset["accumulated"] = money(dec(asset["accumulated"]) + delta)
    asset["depreciatedThrough"] = through
    if elapsed == (end - start).days:
        asset["status"] = "Fully depreciated"
    return max(delta, dec(0))


def before_command(s, command, d):
    if command in {'reconcileBank', 'reconcileBankGroup', 'reconcileBankSplit'}:
        ids = d.get('statements', []) if command == 'reconcileBankSplit' else [d.get('statement')]
        require(isinstance(ids, list), 'Choose statement lines.')
        for key in ids:
            statement = get(s, 'bankStatements', key)
            prior = statement.get('adjustmentJournal')
            require(not prior or any(j.get('reversalOf') == prior for j in s['journal']),
                    'Reverse the existing bank adjustment before matching a different payment.')
    if command in {"pay", "customerPayment", "asset"}:
        key = d.get("creditAccount", "LED-BANK") if command == "asset" else d.get("bankLedger", "LED-BANK")
        bank = next((l for l in s["ledgers"] if l["id"] == key or l["name"] == key), None)
        require(
            not bank or bank.get("currency", s["settings"]["currency"]) == s["settings"]["currency"],
            "Use party funds or currency transfer for a foreign bank.",
        )
    if command == "settings" and d.get("currency") and d["currency"] != s["settings"]["currency"]:
        require(
            not s["journal"] and not s["invoices"] and not s["salesInvoices"] and not s["partyFunds"],
            "Base currency cannot change after accounting activity.",
        )
    if command in {"pay", "customerPayment", "reversePayment"}:
        if command == "reversePayment":
            require(not get(s,"payments",d["id"]).get("reconciledStatement"),"Unmatch the bank statement before reversing its payment.")
            inv = get(s, "invoices", get(s, "payments", d["id"])["invoice"])
        else:
            inv = get(
                s,
                "salesInvoices" if command in {"customerPayment", "customerCredit"} else "invoices",
                d.get("invoice", d.get("id")),
            )
        require(
            inv.get("currency", s["settings"]["currency"]) == s["settings"]["currency"],
            "Use the foreign-currency settlement workflow; this legacy action is base-currency only.",
        )
    if command == "item" and s["settings"].get("perpetualAccounting"):
        require(
            not d.get("stock", 0), "Use an approved stock count for opening stock after perpetual activation."
        )
    if command == "confirmOpeningCost" and s["settings"].get("perpetualAccounting"):
        require(False, "Opening cost is frozen after perpetual accounting activation.")


def after_command(s, previous, command, d, result):
    """Post source-document effects atomically with the originating command."""
    for key, value in dimensions(s, d).items():
        result.setdefault(key, value)
    previous_journals = {j["id"] for j in previous["journal"]}
    new_journals = [j for j in s["journal"] if j["id"] not in previous_journals]
    if command in {
        "order",
        "editOrder",
        "salesOrder",
        "salesQuote",
        "invoice",
        "editInvoice",
        "salesInvoice",
    }:
        parent = None
        if command in {"invoice", "editInvoice"}:
            parent = get(s, "orders", result["po"])
        if command == "salesInvoice":
            parent = get(s, "salesOrders", result["order"])
        currency = (parent or {}).get(
            "currency", (d.get("currency") or result.get("currency", s["settings"]["currency"]))
        )
        rate = fx(s, currency, result["date"], d.get("rate"))
        result.update(currency=currency, rate=str(rate))
        if parent:
            for key in ("costCentre", "project"):
                if parent.get(key):
                    result.setdefault(key, parent[key])
    if command in {"post", "salesInvoice"}:
        for j in new_journals:
            if j["reference"] == result["id"]:
                j.update(
                    currency=result.get("currency", s["settings"]["currency"]), rate=result.get("rate", "1")
                )
                j["entries"] = translated(j["entries"], dec(result.get("rate", 1)))
    if command in {"credit", "customerCredit"}:
        side = "supplier" if command == "credit" else "customer"
        inv, outstanding = invoice_open(previous, side, result["invoice"])
        require(
            not any(
                r["date"] > result["date"] and any(i["invoice"] == inv["id"] for i in r["items"])
                for r in s["fxRevaluations"]
            ),
            "Credit cannot precede later FX revaluation.",
        )
        applied = min(dec(result["amount"]), outstanding)
        excess = dec(result["amount"]) - applied
        rate = dec(inv.get("rate", 1))
        carrying = (
            invoice_carrying_base(previous, inv, side, result["date"])
            if applied == outstanding
            else dec(money(applied * carrying_rate(previous, inv, result["date"])))
        )
        result.update(
            appliedAmount=money(applied),
            carryingBase=money(carrying),
            currency=inv.get("currency", s["settings"]["currency"]),
            rate=str(rate),
        )
        j = next(j for j in new_journals if j["reference"] == result["id"])
        j["entries"] = translated(j["entries"], rate)
        control = "Accounts payable" if side == "supplier" else "Accounts receivable"
        advance = "Supplier advances" if side == "supplier" else "Customer advances"
        field = "debit" if side == "supplier" else "credit"
        line = next(e for e in j["entries"] if e["account"] == control)
        line[field] = money(carrying)
        if excess:
            j["entries"].append(dict(account=advance, **{field: money(excess * rate)}))
            fund = dict(
                id=identifier(s, "FUND"),
                side=side,
                party=inv[side],
                date=result["date"],
                amount=money(excess),
                currency=result["currency"],
                rate=str(rate),
                reference=result["id"],
                status="Recorded",
                sourceCredit=result["id"],
            )
            s["partyFunds"].append(fund)
            result["creditFund"] = fund["id"]
        difference = sum((dec(e.get("debit", 0)) - dec(e.get("credit", 0)) for e in j["entries"]), dec(0))
        if difference:
            j["entries"].append(
                dict(
                    account="Foreign exchange differences",
                    debit=money(max(-difference, dec(0))),
                    credit=money(max(difference, dec(0))),
                )
            )
        if side == "supplier":
            from .domain import invoice_status

            invoice_status(s, get(s, "invoices", result["invoice"]))
    if not s["settings"].get("perpetualAccounting"):
        return
    old_moves = {m["id"] for m in previous["stockMoves"]}
    for m in s["stockMoves"]:
        if m["id"] in old_moves or not m["value"]:
            continue
        kind = m["type"]
        value = m["value"]
        day = m["date"]
        if kind in {"Receipt", "Inspection release"}:
            debit, credit = "Inventory asset", "Goods received not invoiced"
        elif kind == "Customer delivery":
            debit, credit = "Delivered goods awaiting invoicing", "Inventory asset"
        elif kind == "Inspected customer return":
            debit, credit = "Inventory asset", "Delivered goods awaiting invoicing"
        elif kind == "Production consumption":
            debit, credit = "Work in progress", "Inventory asset"
        elif kind == "Production output":
            debit, credit = "Inventory asset", "Work in progress"
        elif "transfer" in kind.lower() or "relocat" in kind.lower():
            continue
        elif kind == "Supplier return":
            debit, credit = "Goods received not invoiced", "Inventory asset"
        else:
            debit, credit = (
                ("Inventory asset", "Inventory adjustments")
                if m["qty"] > 0
                else ("Inventory adjustments", "Inventory asset")
            )
        post(
            s,
            m["id"],
            kind,
            [dict(account=debit, debit=value), dict(account=credit, credit=value)],
            day,
            source=m["reference"],
        )
    if command == "finishProduction" and result["outputs"][-1]["conversionCost"]:
        value = result["outputs"][-1]["conversionCost"]
        post(
            s,
            result["id"],
            "Production conversion cost",
            [
                dict(account="Work in progress", debit=value),
                dict(account="Production conversion clearing", credit=value),
            ],
            result["outputs"][-1]["date"],
        )
    if command == "landedCost":
        # Capitalize from expense already posted by a separate supplier/service bill.
        expense = d.get("expenseAccount")
        from .finance import account_name

        require(expense, "Choose the already-posted landed-cost expense account.")
        account = account_name(s, expense)
        require(account not in {"Inventory asset", "Accounts payable"}, "Use the source expense account.")
        source = get(s, "journal", d.get("expenseJournal"))
        require(source["date"] <= result["date"], "Expense voucher must precede capitalisation.")
        available = sum(
            (
                dec(e.get("debit", 0)) - dec(e.get("credit", 0))
                for e in source["entries"]
                if e["account"] == account
            ),
            dec(0),
        )
        used = sum(
            (
                dec(c["amount"])
                for c in s["landedCosts"]
                if c["id"] != result["id"]
                and c.get("expenseJournal") == source["id"]
                and c.get("expenseAccount") == account
            ),
            dec(0),
        )
        require(
            dec(result["amount"]) <= available - used, "Landed cost exceeds the uncapitalised source expense."
        )
        result.update(expenseJournal=source["id"], expenseAccount=account)
        post(
            s,
            result["id"],
            "Capitalised landed cost",
            [
                dict(account="Inventory asset", debit=result["amount"]),
                dict(account=account, credit=result["amount"]),
            ],
            result["date"],
        )
    if command == "post":
        allocations = []
        for line in result["lines"]:
            needed = dec(line["qty"])
            receipts = {r["id"] for r in s["receipts"] if r["po"] == result["po"]}
            for m in sorted(s["stockMoves"], key=lambda m: (m["date"], m["id"])):
                if (
                    m["reference"] not in receipts
                    or m["item"] != line["item"]
                    or m["qty"] <= 0
                    or m["date"] > result["date"]
                ):
                    continue
                used = sum(
                    (
                        dec(a["qty"])
                        for inv in s["invoices"]
                        if inv["id"] != result["id"]
                        for a in inv.get("grniAllocations", [])
                        if a["movement"] == m["id"]
                    ),
                    dec(0),
                )
                take = min(needed, max(dec(0), dec(m["qty"]) - used))
                if take:
                    allocations.append(
                        dict(
                            movement=m["id"],
                            item=line["item"],
                            qty=float(take),
                            value=money(dec(m["value"]) * take / dec(m["qty"])),
                        )
                    )
                    needed -= take
                if not needed:
                    break
            require(
                needed == 0,
                "Invoice requires dated receipt cost allocations; reconcile migrated receipts first.",
            )
        base = money(sum((dec(a["value"]) for a in allocations), dec(0)))
        result["grniAllocations"] = allocations
        j = next(j for j in new_journals if j["reference"] == result["id"])
        purchase = get(s, "ledgers", result["purchaseLedger"])["name"]
        line = next(e for e in j["entries"] if e["account"] == purchase)
        difference = dec(line.get("debit", 0)) - dec(base)
        line.update(account="Goods received not invoiced", debit=base)
        if difference:
            j["entries"].append(
                dict(
                    account="Purchase price variance",
                    debit=money(max(difference, dec(0))),
                    credit=money(max(-difference, dec(0))),
                )
            )
    if command == "credit":
        j = next(j for j in new_journals if j["reference"] == result["id"])
        inv = get(s, "invoices", result["invoice"])
        purchase = get(s, "ledgers", inv["purchaseLedger"])["name"]
        for e in j["entries"]:
            if e["account"] == purchase:
                e["account"] = "Goods received not invoiced"
    if command == "salesInvoice":
        costs = []
        for line in result["lines"]:
            remaining = dec(line["qty"])
            deliveries = {x["id"] for x in s["deliveries"] if x["order"] == result["order"]}
            for m in sorted(s["stockMoves"], key=lambda m: (m["date"], m["id"])):
                if (
                    m["reference"] not in deliveries
                    or m["item"] != line["item"]
                    or m["qty"] >= 0
                    or m["date"] > result["date"]
                ):
                    continue
                for position in m["allocations"]:
                    prior = [
                        a
                        for inv in s["salesInvoices"]
                        if inv["id"] != result["id"]
                        for a in inv.get("costAllocations", [])
                        if a["movement"] == m["id"] and a.get("position") == position["position"]
                    ]
                    used = sum((dec(a["qty"]) for a in prior), dec(0))
                    available = dec(position["qty"]) - used
                    take = min(remaining, max(dec(0), available))
                    if take:
                        cost = (
                            dec(position["value"]) - sum((dec(a["value"]) for a in prior), dec(0))
                            if take == available
                            else dec(money(dec(position["value"]) * take / dec(position["qty"])))
                        )
                        costs.append(
                            dict(
                                movement=m["id"],
                                position=position["position"],
                                item=line["item"],
                                qty=float(take),
                                value=money(cost),
                            )
                        )
                        remaining -= take
                    if not remaining:
                        break
                if not remaining:
                    break
            require(not remaining, "Invoice cost allocation is incomplete.")
        result["costAllocations"] = costs
        value = money(sum((dec(c["value"]) for c in costs), dec(0)))
        if value:
            post(
                s,
                result["id"],
                "Invoiced cost of sales",
                [
                    dict(account="Cost of sales", debit=value),
                    dict(account="Delivered goods awaiting invoicing", credit=value),
                ],
                result["date"],
            )
    if command == "customerCredit":
        inv = get(s, "salesInvoices", result["invoice"])
        item = result["lines"][0]["item"]
        qty = dec(result["lines"][0]["qty"])
        returned = get(s, "salesReturns", result["return"])
        delivery = get(s, "deliveries", returned["delivery"])
        costs = [
            a
            for a in inv.get("costAllocations", [])
            if a["movement"] in delivery["movements"]
            and a.get("position") == returned["position"]
            and a["item"] == item
        ]
        original_qty = sum((dec(c["qty"]) for c in costs), dec(0))
        previous_credits = [
            c
            for c in s["customerCredits"]
            if c["id"] != result["id"]
            and c["invoice"] == inv["id"]
            and get(s, "salesReturns", c["return"])["delivery"] == delivery["id"]
            and get(s, "salesReturns", c["return"])["position"] == returned["position"]
        ]
        already = sum((dec(c["lines"][0]["qty"]) for c in previous_credits), dec(0))
        require(
            already + qty <= original_qty,
            "Returned position was not invoiced by this invoice; choose its original invoice.",
        )
        original_value = sum((dec(c["value"]) for c in costs), dec(0))
        value = (
            money(original_value - sum((dec(c.get("returnedCost", 0)) for c in previous_credits), dec(0)))
            if already + qty == original_qty
            else money(original_value * qty / original_qty)
        )
        result["returnedCost"] = value
        if value:
            post(
                s,
                result["id"],
                "Returned cost of sales",
                [
                    dict(account="Delivered goods awaiting invoicing", debit=value),
                    dict(account="Cost of sales", credit=value),
                ],
                result["date"],
            )


def fund_carrying_base(s, fund, day):
    return (
        dec(money(dec(fund["amount"]) * dec(fund["rate"])))
        - sum(
            (
                dec(a["fundingBase"])
                for a in s["fundAllocations"]
                if a["fund"] == fund["id"] and a["date"] <= day
            ),
            dec(0),
        )
        - sum(
            (
                dec(a.get("carryingBase", money(dec(a["amount"]) * dec(fund["rate"]))))
                for a in s["fundRefunds"]
                if a["fund"] == fund["id"] and a["date"] <= day
            ),
            dec(0),
        )
    )


def invoice_carrying_base(s, inv, side, day):
    from .domain import totals

    value = dec(
        money(
            dec(
                inv["amount"] if side == "supplier" or inv.get("accountingDocument") else totals(inv)["total"]
            )
            * dec(inv.get("rate", 1))
        )
    )
    value += sum(
        (
            dec(i["difference"])
            for r in s["fxRevaluations"]
            if r["date"] <= day
            for i in r["items"]
            if i["invoice"] == inv["id"]
        ),
        dec(0),
    )
    value -= sum(
        (
            dec(a["carryingBase"])
            for a in s["fundAllocations"]
            if a["invoice"] == inv["id"] and a["side"] == side and a["date"] <= day
        ),
        dec(0),
    )
    value -= sum(
        (
            dec(a["amount"])
            for a in s["payments" if side == "supplier" else "customerPayments"]
            if a["invoice"] == inv["id"]
            and a["date"] <= day
            and (a["status"] != "Reversed" or a.get("reversalDate", "") > day)
        ),
        dec(0),
    )
    value -= sum(
        (
            dec(c.get("carryingBase", c.get("appliedAmount", c["amount"])))
            for c in s["credits" if side == "supplier" else "customerCredits"]
            if c["invoice"] == inv["id"] and c["date"] <= day
        ),
        dec(0),
    )
    return value


def validate_accounting(s):
    """Validate new subledger references before accepting a portable restore."""
    references = {j.get("reference", "") for j in s["journal"]}
    for doc in s["accountingDocuments"]:
        require(doc["side"] in {"supplier", "customer"}, "Invalid accounting invoice side.")
        get(s, "suppliers" if doc["side"] == "supplier" else "customers", doc[doc["side"]])
        require(
            dec(doc["net"]) > 0
            and dec(doc["taxAmount"]) >= 0
            and dec(doc["amount"]) == dec(doc["net"]) + dec(doc["taxAmount"]),
            "Invalid accounting invoice amounts.",
        )
        require(
            doc["id"] in references and valid_date(doc["due"]) >= valid_date(doc["date"]),
            "Accounting invoice has no journal or invalid dates.",
        )
    for fund in s["partyFunds"]:
        require(
            fund["side"] in {"supplier", "customer"} and dec(fund["amount"]) > 0 and dec(fund["rate"]) > 0,
            "Invalid funds record.",
        )
        get(s, "suppliers" if fund["side"] == "supplier" else "customers", fund["party"])
        require(fund.get("sourceCredit", fund["id"]) in references, "Funds have no source journal.")
        require(remaining_funds(s, fund) >= 0, "Funds are overallocated or overrefunded.")
    for allocation in s["fundAllocations"]:
        fund = get(s, "partyFunds", allocation["fund"])
        inv, outstanding = invoice_open(s, allocation["side"], allocation["invoice"])
        require(
            allocation["side"] == fund["side"] and inv[fund["side"]] == fund["party"],
            "Allocation party mismatch.",
        )
        require(dec(allocation["amount"]) > 0 and outstanding >= 0, "Invalid allocation amount.")
        require(
            allocation["id"] in references and allocation["date"] >= max(fund["date"], inv["date"]),
            "Allocation has no journal or invalid date.",
        )
    for refund in s["fundRefunds"]:
        fund = get(s, "partyFunds", refund["fund"])
        require(
            dec(refund["amount"]) > 0 and refund["date"] >= fund["date"] and refund["id"] in references,
            "Invalid refund.",
        )
    for movement in s["bankFxMovements"]:
        bank = get(s, "ledgers", movement["bank"])
        require(
            bank.get("currency") == movement["currency"]
            and dec(movement["units"]) != 0
            and movement["reference"] in references,
            "Invalid foreign bank movement.",
        )
