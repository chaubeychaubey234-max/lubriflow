"""Deterministic procurement rules shared by manual commands and automation.

All money calculations use Decimal; a failed command leaves the supplied state unchanged.
"""

from copy import deepcopy
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from math import ceil
from uuid import uuid4
from zoneinfo import ZoneInfo
import re

COLLECTIONS = (
    "accountingDocuments bankFxMovements voucherTypes projects financeBudgets partyFunds fundAllocations fundRefunds financeSchedules fxRevaluations settingsChangeRequests stockPositions stockCounts reservations landedCosts salesQuotes salesReturns customerCredits boms productionOrders "
    "suppliers items requisitions quotes orders receipts returns invoices credits payments "
    "stockMoves journal comments warehouses costCentres ledgers prices drafts attachments rfqs communications "
    "accounts portalSubmissions branches bins taxProfiles customers contracts approvalPolicies automationRules salesOrders deliveries salesInvoices customerPayments bankStatements assets depreciationRuns exchangeRates taxReturns audit"
).split()
PERMISSIONS = {
    "requester": {"requisition", "comment"},
    "buyer": set(
        "requisition forecastRequisition supplier item editSupplier editItem quote award order editOrder submit convert "
        "dispatch ack cancel close preclose priceAgreement comment createRFQ closeRFQ queueSupplierMessage cancelSupplierMessage".split()
    ),
    "approver": set("approvePR rejectPR approve reject comment approveStockCount".split()),
    "stores": set("receipt return stockIssue stockTransfer comment stockCount reserveStock releaseReservation relocateStock consumeProduction finishProduction".split()),
    "production": set("bom productionOrder createMaterialPlan releaseProduction consumeProduction finishProduction cancelProduction reserveStock releaseReservation comment".split()),
    "quality": {"accept", "rejectReceipt", "comment", "stockDisposition"},
    "sales": set("salesOrder deliverSale salesInvoice customerPayment comment salesQuote convertSalesQuote salesReturn customerCredit reserveStock releaseReservation closeSalesOrder".split()),
    "finance": set(
        "approve invoice editInvoice voidInvoice match post pay reversePayment credit comment "
        "account journal reverseJournal linkSubmission rejectSubmission bankStatement bankStatementImport bankImportMapping reconcileBank reconcileBankGroup reconcileBankSplit "
        "asset depreciate exchangeRate taxWorkpaper closePeriod closeYear landedCost customerCredit confirmOpeningCost requestSettingsChange approveSettingsChange".split()
    ),
    "viewer": set(),
    "system": {"requisition", "forecastRequisition", "convert", "order", "submit", "approve", "match", "escalateApproval"},
}
ACTIVE_PO = {"Issued", "Acknowledged", "Part received", "Received"}
POSTED = {"Posted", "Part paid", "Paid"}


class RuleError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise RuleError(message)


def qualified(supplier):
    """Qualification remains valid through its expiry date; blank means no expiry."""
    return bool(supplier.get("approved") and (not supplier.get("qualificationUntil")
                or supplier["qualificationUntil"] >= today()))


def dec(value):
    try:
        result = Decimal(str(value))
        require(result.is_finite(), "Enter a finite number.")
        return result
    except (InvalidOperation, TypeError):
        raise RuleError("Enter a valid number.") from None


def money(value):
    return float(dec(value).quantize(Decimal(".01"), rounding=ROUND_HALF_UP))


def amount(value=0, positive=False):
    number = dec(value)
    require(
        0 <= number <= Decimal("10000000000") and (not positive or number > 0),
        "Amount is outside the supported range.",
    )
    return money(number)


def quantity(value):
    number = dec(value)
    require(
        0 < number <= Decimal("1000000000") and number == number.quantize(Decimal(".000001")),
        "Quantity must be positive with up to six decimal places.",
    )
    return float(number)


def text(value, label="Value", required=False):
    require(isinstance(value, str) and len(value) <= 5000, label + " must be text of up to 5000 characters.")
    result = value.strip()
    require(not required or bool(result), label + " is required.")
    return result


def today():
    """Use a neutral operational date; deployments may supply their local business date at the edge."""
    return datetime.now(ZoneInfo("UTC")).date().isoformat()


def valid_date(value):
    try:
        require(isinstance(value, str) and date.fromisoformat(value).isoformat() == value, "Invalid date.")
        return value
    except (TypeError, ValueError):
        raise RuleError("Enter a valid ISO date.") from None


def add_days(value, days):
    require(0 <= days <= 3650, "Days must be between 0 and 3650.")
    return (date.fromisoformat(valid_date(value)) + timedelta(days=days)).isoformat()


def voucher_date(s, value=None):
    value = valid_date(value or today())
    require(value <= today(), "Voucher date cannot be in the future.")
    require(
        not s["settings"]["lockedThrough"] or value > s["settings"]["lockedThrough"],
        "Accounting period is locked.",
    )
    return value


def get(s, collection, key):
    record = next((x for x in s[collection] if x["id"] == key), None)
    require(record is not None, "Record not found: " + str(key))
    return record


def active(s, collection, key):
    record = get(s, collection, key)
    require(record.get("active", True), "Choose an active master.")
    return record


def identifier(s, prefix):
    s["series"][prefix] = s["series"].get(prefix, 0) + 1
    return f"{prefix}-{s['series'][prefix]:06d}"


def empty(company="Your company"):
    s = {key: [] for key in COLLECTIONS}
    s.update(
        version=4,
        series={},
        settings=dict(
            company=company,
            address="",
            phone="",
            email="",
            taxId="",
            country="",
            legalEntityType="",
            industryTemplate="",
            taxRegistrationStatus="",
            currency="USD",
            timezone="UTC",
            fiscalYearStart="01-01",
            taxRegime="standard",
            mode="manual",
            autoPO=False,
            autoApprove=False,
            autoMatch=True,
            autoReorder=False,
            limit=10000,
            financeThreshold=50000,
            budgetMonthly=1000000,
            priceTolerance=0,
            invoiceTolerance=0.01,
            separation=True,
            defaultTax=0,
            paymentDays=30,
            lockedThrough="",
            onboardingCompleted=False,
            onboardingVersion=1,
            bankImportMappings=[],
            modules=dict(
                procurement=True,
                inventory=True,
                accounting=True,
                sales=False,
                manufacturing=False,
                projects=False,
                healthcare=False,
                foodSafety=False,
                chemicalCompliance=False,
            ),
        ),
    )
    s["warehouses"] = [dict(id="WH-MAIN", name="Main warehouse", address="", active=True)]
    s["costCentres"] = [dict(id="CC-OPS", name="Operations", active=True)]
    s["ledgers"] = [
        dict(id="LED-PUR", name="Purchases", type="purchase", active=True),
        dict(id="LED-BANK", name="Bank clearing", type="bank", active=True),
        dict(id="LED-CASH", name="Cash", type="cash", active=True),
    ]
    return s


def lines(s, values):
    require(isinstance(values, list) and 1 <= len(values) <= 100, "Add 1–100 item lines.")
    seen, result = set(), []
    for value in values:
        item = get(s, "items", value.get("item"))
        require(item["id"] not in seen, "Combine duplicate items into one line.")
        seen.add(item["id"])
        line = dict(
            item=item["id"],
            qty=quantity(value.get("qty")),
            price=amount(value.get("price", 0)),
            discount=amount(value.get("discount", 0)),
            description=text(value.get("description", item["specification"])),
        )
        if value.get("taxRate") not in (None, ""):
            line["taxRate"] = amount(value["taxRate"])
        for key in ("bin", "lot", "serial", "expiry", "reservation"):
            if value.get(key):
                line[key] = text(value[key], key)
        require(line["discount"] <= 100 and line.get("taxRate", 0) <= 100, "Tax and discount must be 0–100%.")
        result.append(line)
    return result


def totals(record):
    gross = discount = net = tax = Decimal(0)
    for line in record["lines"]:
        g = dec(money(dec(line["qty"]) * dec(line["price"])))
        d = dec(money(g * dec(line.get("discount", 0)) / 100))
        gross += g
        discount += d
        net += g - d
        tax += dec(money((g - d) * dec(line.get("taxRate", record.get("tax", 0))) / 100))
    freight = dec(record.get("freight", 0))
    return dict(
        gross=money(gross),
        discount=money(discount),
        subtotal=money(net),
        tax=money(tax),
        freight=money(freight),
        total=money(net + tax + freight),
    )


def effective(line):
    return float(dec(line["qty"]) - dec(line.get("closedQty", 0)))


def sum_qty(records, item):
    return float(sum((dec(l["qty"]) for r in records for l in r["lines"] if l["item"] == item), Decimal(0)))


def received(s, po, item, reserved=False):
    receipts = [
        r
        for r in s["receipts"]
        if r["po"] == po and (r["status"] != "Rejected" if reserved else r["status"] == "Accepted")
    ]
    return sum_qty(receipts, item) - sum_qty([r for r in s["returns"] if r["po"] == po], item)


def billed(s, po, item, exclude=None, posted=False):
    return sum_qty(
        [
            r
            for r in s["invoices"]
            if r["po"] == po
            and r["id"] != exclude
            and r["status"] != "Void"
            and (not posted or r["status"] in POSTED)
        ],
        item,
    )


def credited(s, po, item):
    return sum_qty([r for r in s["credits"] if r["po"] == po], item)


def balance(s, invoice):
    from .accounting import allocated
    return money(
        dec(invoice["amount"])
        - allocated(s,invoice["id"],"supplier")
        - sum(
            (
                dec(p["amount"])
                for p in s["payments"]
                if p["invoice"] == invoice["id"] and p["status"] != "Reversed"
            ),
            Decimal(0),
        )
        - sum((dec(c.get("appliedAmount",c["amount"])) for c in s["credits"] if c["invoice"] == invoice["id"]), Decimal(0))
    )


def match(s, invoice):
    po = get(s, "orders", invoice["po"])
    errors = []
    if po["status"] not in ACTIVE_PO:
        errors.append("PO must be issued and active")
    if abs(dec(invoice["amount"]) - dec(totals(invoice)["total"])) > dec(s["settings"]["invoiceTolerance"]):
        errors.append("Declared invoice total differs from line calculation")
    for line in invoice["lines"]:
        pl = next((x for x in po["lines"] if x["item"] == line["item"]), None)
        if pl is None:
            errors.append("Item is not on the PO")
            continue
        rate = lambda x: dec(x["price"]) * (1 - dec(x.get("discount", 0)) / 100)
        if abs(rate(line) - rate(pl)) > rate(pl) * dec(s["settings"]["priceTolerance"]) / 100:
            errors.append("Price differs from PO")
        if line.get("taxRate", invoice["tax"]) != pl.get("taxRate", po["tax"]):
            errors.append("Tax differs from PO")
        if (
            billed(s, po["id"], line["item"], invoice["id"], True)
            - credited(s, po["id"], line["item"])
            + line["qty"]
            > received(s, po["id"], line["item"]) + 0.000001
        ):
            errors.append("Accepted receipt quantity is insufficient")
    freight = sum(
        dec(i.get("freight", 0)) for i in s["invoices"] if i["po"] == po["id"] and i["status"] != "Void"
    )
    if freight > dec(po["freight"]):
        errors.append("Cumulative freight exceeds approved PO freight")
    return "; ".join(dict.fromkeys(errors))


def stock(s, actor, item_id, delta, reference, kind, warehouse="WH-MAIN", **tracking):
    from .inventory import move
    return move(s, actor, item_id, delta, reference, kind, warehouse, **tracking)


def journal(s, reference, description, entries, entry_date):
    require(
        sum((dec(e.get("debit", 0)) - dec(e.get("credit", 0)) for e in entries), Decimal(0)) == 0,
        "Journal debits and credits must balance exactly.",
    )
    result = dict(
        id=identifier(s, "JV"), date=entry_date, reference=reference, description=description, entries=entries
    )
    s["journal"].insert(0, result)
    return result


def receipt_status(s, po):
    po["status"] = (
        "Received"
        if all(received(s, po["id"], l["item"]) + 0.000001 >= effective(l) for l in po["lines"])
        else "Part received"
    )


def invoice_status(s, invoice):
    invoice["status"] = (
        "Paid"
        if balance(s, invoice) == 0
        else "Part paid"
        if balance(s, invoice) < invoice["amount"]
        else "Posted"
    )


def suggest(s, supplier, item, entry_date=None):
    entry_date = entry_date or today()
    it = get(s, "items", item)
    agreements = [
        p
        for p in s["prices"]
        if p["supplier"] == supplier and p["item"] == item and p["validFrom"] <= entry_date <= p["validUntil"]
    ]
    if agreements:
        return {**sorted(agreements, key=lambda p: p["validFrom"])[-1], "source": "Supplier agreement"}
    for po in sorted(s["orders"], key=lambda o: o["date"], reverse=True):
        if po["supplier"] == supplier and po["status"] in ACTIVE_PO | {"Approved", "Closed"}:
            for line in po["lines"]:
                if line["item"] == item:
                    return {**line, "source": "Last approved order"}
    return dict(price=it["price"], discount=0, taxRate=it["taxRate"], source="Item master")


def allowed(actor, action):
    from .accounting import ACTIONS
    return actor["role"] == "admin" or action in PERMISSIONS.get(actor["role"], set()) or (actor["role"] == "finance" and action in ACTIONS)


def act(state, action, data, actor):
    working = deepcopy(state)
    from .accounting import before_command, after_command
    require(allowed(actor,action) or action in {"saveDraft","deleteDraft"},"Your role cannot perform this action.")
    before_command(working, action, data)
    result = perform(working, action, data, actor)
    after_command(working, state, action, data, result)
    from .accounting import dimensions
    source_dimensions=dimensions(working,{k:result.get(k,data.get(k,"")) for k in ("costCentre","project")})
    prior_journals={j["id"] for j in state["journal"]}
    for entry in working["journal"]:
        if entry["id"] in prior_journals:continue
        for line in entry["entries"]:
            for key,value in source_dimensions.items():line.setdefault(key,value)
        require(sum((dec(l.get("debit",0))-dec(l.get("credit",0)) for l in entry["entries"]),dec(0))==0,"Generated journal does not balance.")
        require(all(dec(l.get("debit",0))>=0 and dec(l.get("credit",0))>=0 for l in entry["entries"]),"Generated journal contains a negative amount.")
    working["audit"].insert(
        0,
        dict(
            id="EV-" + str(uuid4()),
            at=datetime.now(ZoneInfo("UTC")).isoformat(),
            actor=actor.get("name", actor["id"]),
            actorId=actor["id"],
            action=action,
            detail=result.get("id", ""),
        ),
    )
    state.clear()
    state.update(working)
    return result


def perform(s, action, d, actor):
    require(
        allowed(actor, action) or action in {"saveDraft", "deleteDraft"},
        "Your role cannot perform this action.",
    )
    if action == "forecastRequisition":
        recommendation = next((r for r in procurement_insights(s)['forecastPurchaseRecommendations']
                               if r['item'] == d.get('item')), None)
        require(recommendation and not recommendation['blockedReason'],
                'No unblocked current recommendation. Refresh purchasing insights.')
        item = get(s, 'items', recommendation['item'])
        rate = suggest(s, item['supplier'], item['id'])
        record = perform(s, 'requisition', dict(department='Inventory', note='Demand-based replenishment recommendation',
            lines=[dict(item=item['id'], qty=recommendation['suggestedQty'], price=rate['price'],
                        discount=rate.get('discount', 0), taxRate=rate.get('taxRate', item['taxRate']))]), actor)
        record['planningEvidence'] = recommendation
        return record
    r = {}
    if action == 'requestSettingsChange':
        require(actor['role'] in {'admin', 'finance'}, 'Finance or administrator access required.')
        changes = d.get('changes')
        require(isinstance(changes, dict) and changes, 'Provide sensitive setting changes.')
        allowed_changes = {'taxId', 'country', 'currency', 'taxRegime', 'defaultTax', 'lockedThrough'}
        require(set(changes).issubset(allowed_changes), 'This request contains unsupported settings.')
        # Validate on a copy; no setting takes effect until a different person approves.
        candidate = deepcopy(s)
        from .accounting import before_command
        before_command(candidate, 'settings', changes)
        # A finance requester may propose a change even though direct settings
        # edits are administrator-only.  Validate through the same controlled
        # handler without granting a direct edit to the requester.
        perform(candidate, 'settings', changes, {**actor, 'role': 'admin'})
        r = dict(id=identifier(s, 'SCH'), changes=deepcopy(changes), reason=text(d.get('reason'), 'Reason', True),
                 requestedBy=actor['id'], requestedAt=datetime.now(ZoneInfo('UTC')).isoformat(), status='Pending')
        s['settingsChangeRequests'].insert(0, r)
        return r
    if action == 'approveSettingsChange':
        require(actor['role'] in {'admin', 'finance'}, 'Finance or administrator access required.')
        request = get(s, 'settingsChangeRequests', d.get('id'))
        require(request['status'] == 'Pending', 'Setting request is no longer pending.')
        require(request['requestedBy'] != actor['id'], 'A different person must approve this sensitive change.')
        from .accounting import before_command
        before_command(s, 'settings', request['changes'])
        # Approval authorizes the controlled settings handler; the outer command retains the reviewer audit actor.
        perform(s, 'settings', request['changes'], {**actor, 'role': 'admin'})
        request.update(status='Approved', approvedBy=actor['id'], approvedAt=datetime.now(ZoneInfo('UTC')).isoformat(),
                       approvalReason=text(d.get('reason'), 'Approval reason', True))
        return request
    if action == 'configureCompany':
        require(actor['role'] == 'admin', 'Administrator access required.')
        templates = {'general': [], 'trading': ['sales'], 'manufacturing': ['sales', 'manufacturing'],
                     'services': ['sales'], 'construction': ['projects'], 'healthcare': [], 'food': [], 'chemicals': []}
        require(d.get('industryTemplate') in templates, 'Choose a supported industry template.')
        require(d.get('legalEntityType') in {'company', 'partnership', 'sole-proprietor', 'non-profit', 'government'},
                'Choose a legal entity type.')
        require(d.get('taxRegistrationStatus') in {'registered', 'not-registered', 'exempt', 'pending'},
                'Choose a tax registration status.')
        require(isinstance(d.get('country'), str) and re.fullmatch('[A-Z]{2}', d['country']),
                'Country must be a two-letter code.')
        for key in ('company', 'currency', 'timezone', 'fiscalYearStart', 'taxRegime'):
            text(d.get(key), key, True)
        from .accounting import before_command
        before_command(s, 'settings', d)
        fields = ('company', 'country', 'legalEntityType', 'industryTemplate', 'taxRegistrationStatus',
                  'currency', 'timezone', 'fiscalYearStart', 'taxRegime')
        config = {key: d[key] for key in fields}
        config['modules'] = {key: True for key in ['procurement', 'inventory', 'accounting'] + templates[d['industryTemplate']]}
        perform(s, 'settings', config, actor)
        s['settings']['onboardingReviewedBy'] = actor['id']
        s['settings']['onboardingReviewedAt'] = datetime.now(ZoneInfo('UTC')).isoformat()
        return {'id': 'COMPANY-SETUP', 'enabledModules': list(config['modules'])}
    if action == "bankStatementImport":
        from .bank_import import import_statement
        return import_statement(s, d, actor)
    if action == "bankImportMapping":
        from .bank_import import save_mapping
        return save_mapping(s, d, actor)
    if action in {"delegateApproval", "revokeApprovalDelegation", "escalateApproval"}:
        from .approval_policy import approval_action
        return approval_action(s, action, d, actor)
    from .accounting import ACTIONS, action as accounting_action
    if action in ACTIONS:
        return accounting_action(s, action, d, actor)
    from .inventory import INVENTORY_ACTIONS, inventory_action
    from .manufacturing import PRODUCTION_ACTIONS, production_action
    from .sales import SALES_ACTIONS, sales_action
    if action in INVENTORY_ACTIONS:
        return inventory_action(s, action, d, actor)
    if action in PRODUCTION_ACTIONS:
        return production_action(s, action, d, actor)
    if action in SALES_ACTIONS:
        return sales_action(s, action, d, actor)
    if action in {"createRFQ", "closeRFQ", "supplierMessaging", "messagingPolicy", "queueSupplierMessage", "cancelSupplierMessage"}:
        from .messaging import message_action
        return message_action(s, action, d, actor)
    if action in {"supplier", "editSupplier"}:
        email = text(d.get("email", ""))
        require(not email or re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email), "Enter a valid email.")
        values = dict(
            name=text(d.get("name"), "Supplier name", True),
            email=email,
            approved=False,
            terms=text(d.get("terms", "Net 30")),
            creditDays=int(amount(d.get("creditDays", 30))),
            leadDays=int(amount(d.get("leadDays", 7))),
            currency=s["settings"]["currency"],
            **{k: text(d.get(k, "")) for k in ["address", "phone", "contact", "taxId", "country"]},
        )
        if action == "editSupplier":
            r = get(s, "suppliers", d["id"])
            values["approved"] = r["approved"]
            r.update(values)
        else:
            r = dict(id=identifier(s, "SUP"), **values)
            s["suppliers"].append(r)
    elif action == "approveSupplier":
        r = get(s, "suppliers", d["id"])
        require(isinstance(d.get("approved"), bool), "Qualification must be yes or no.")
        r["approved"] = d["approved"]
        expiry = valid_date(d["qualificationUntil"]) if d.get("qualificationUntil") else ""
        require(not d["approved"] or not expiry or expiry >= today(), "Qualification expiry cannot be in the past.")
        r.update(qualificationUntil=expiry, qualificationBy=actor["id"], qualificationDate=today(),
                 qualificationNote=text(d.get("reason", "")))
        r.setdefault("qualificationHistory", []).append(dict(approved=r["approved"], until=expiry,
            actor=actor["id"], at=datetime.now(ZoneInfo("UTC")).isoformat(), reason=r["qualificationNote"]))
    elif action in {"item", "editItem"}:
        get(s, "suppliers", d["supplier"])
        values = dict(
            name=text(d.get("name"), "Item name", True),
            unit=text(d.get("unit"), "Unit", True),
            supplier=d["supplier"],
            price=amount(d.get("price", 0)),
            reorder=amount(d.get("reorder", 0)),
            target=amount(d.get("target", 1)),
            taxRate=amount(d.get("taxRate", s["settings"]["defaultTax"])),
            packSize=quantity(d.get("packSize", 1)),
            minOrder=quantity(d.get("minOrder", 1)),
            leadDays=int(amount(d.get("leadDays", 7))),
            inspectionRequired=d.get("inspectionRequired", d.get("quality")) is True,
            **{k: text(d.get(k, "")) for k in ["sku", "category", "specification", "grade"]},
        )
        require(
            values["target"] > values["reorder"] and values["taxRate"] <= 100,
            "Check target stock and tax rate.",
        )
        require(
            not values["sku"]
            or not any(
                i["id"] != d.get("id") and i["sku"].lower() == values["sku"].lower() for i in s["items"]
            ),
            "SKU already exists.",
        )
        if action == "editItem":
            r = get(s, "items", d["id"])
            require(
                r["unit"] == values["unit"]
                or not (any(any(l["item"] == r["id"] for l in o["lines"]) for o in s["orders"])
                        or any(m["item"] == r["id"] for m in s["stockMoves"])),
                "Unit cannot change after use.",
            )
            r.update(values)
        else:
            r = dict(id=identifier(s, "ITM"), stock=amount(d.get("stock", 0)), **values)
            r["sku"] = r["sku"] or r["id"]
            r["stockByWarehouse"] = {"WH-MAIN": r["stock"]}
            s["items"].append(r)
    elif action in {"requisition", "quote"}:
        r = dict(
            id=identifier(s, "PR" if action == "requisition" else "RFQ"),
            date=voucher_date(s, d.get("date")),
            lines=lines(s, d.get("lines")),
            note=text(d.get("note", "")),
            createdBy=actor["id"],
        )
        if action == "requisition":
            r.update(department=text(d.get("department", "Operations")), status="Pending")
            s["requisitions"].insert(0, r)
        else:
            get(s, "suppliers", d["supplier"])
            from .accounting import fx
            currency = text(d.get("currency") or s["settings"]["currency"], "Currency").upper()
            r.update(
                supplier=d["supplier"],
                valid=valid_date(d["valid"]),
                leadDays=int(amount(d.get("leadDays", 7))),
                status="Received",
                currency=currency, rate=str(fx(s, currency, r["date"], d.get("rate"))),
                tax=amount(d.get("tax", s["settings"]["defaultTax"])), freight=amount(d.get("freight", 0)),
                paymentDays=int(amount(d.get("paymentDays", 30))),
            )
            require(r["tax"] <= 100 and r["valid"] >= r["date"], "Check quotation tax and validity dates.")
            s["quotes"].insert(0, r)
            if d.get("rfq"):
                request = get(s, "rfqs", d["rfq"])
                require(request["supplier"] == d["supplier"] and request["status"] == "Open", "Choose an open RFQ for this supplier.")
                r["rfq"] = request["id"]
                request.update(status="Responded", quote=r["id"])
    elif action in {"approvePR", "rejectPR"}:
        r = get(s, "requisitions", d["id"])
        require(r["status"] == "Pending", "Requisition is not pending.")
        require(
            not s["settings"]["separation"] or actor["id"] != r["createdBy"], "A different user must approve."
        )
        r.update(
            status="Approved" if action == "approvePR" else "Rejected",
            decisionBy=actor["id"],
            decisionNote=text(d.get("reason", "")),
        )
    elif action in {"convert", "award"}:
        r = get(s, "requisitions" if action == "convert" else "quotes", d["id"])
        require(
            r["status"] == ("Approved" if action == "convert" else "Received"),
            "Document is not ready for conversion.",
        )
        groups = {}
        if action == "award":
            require(r["valid"] >= today(), "Quotation expired.")
            require(qualified(get(s, "suppliers", r["supplier"])), "Supplier qualification expired or was revoked.")
            groups[r["supplier"]] = r["lines"]
        else:
            for line in r["lines"]:
                groups.setdefault(get(s, "items", line["item"])["supplier"], []).append(line)
        for supplier, order_lines in groups.items():
            data = dict(supplier=supplier, lines=order_lines, source=r["id"], note=r["note"])
            if action == "award":
                data.update({k: r[k] for k in ("currency", "rate", "tax", "freight", "paymentDays") if k in r})
                data["due"] = add_days(today(), r["leadDays"])
            created = perform(s, "order", data, actor)
            from .accounting import fx
            currency = data.get("currency", s["settings"]["currency"])
            created.update(currency=currency, rate=str(fx(s, currency, created["date"], data.get("rate"))))
        r["status"] = "Converted" if action == "convert" else "Awarded"
    elif action in {"order", "editOrder"}:
        vendor = get(s, "suppliers", d["supplier"])
        entry_date = voucher_date(s, d.get("date"))
        warehouse = active(s, "warehouses", d.get("warehouse", "WH-MAIN"))
        ledger = active(s, "ledgers", d.get("purchaseLedger", "LED-PUR"))
        active(s, "costCentres", d.get("costCentre", "CC-OPS"))
        require(ledger["type"] == "purchase", "Choose a purchase ledger.")
        values = dict(
            supplier=vendor["id"],
            date=entry_date,
            due=valid_date(d.get("due") or add_days(entry_date, vendor["leadDays"])),
            tax=amount(d.get("tax", s["settings"]["defaultTax"])),
            freight=amount(d.get("freight", 0)),
            lines=lines(s, d.get("lines")),
            warehouse=warehouse["id"],
            costCentre=d.get("costCentre", "CC-OPS"),
            purchaseLedger=ledger["id"],
            paymentDays=int(amount(d.get("paymentDays", vendor["creditDays"]))),
            paymentTerms=text(d.get("paymentTerms", vendor["terms"])),
            supplierAddress=vendor["address"],
            supplierTaxId=vendor["taxId"],
            billingAddress=text(d.get("billingAddress", s["settings"]["address"])),
            deliveryAddress=text(d.get("deliveryAddress", warehouse["address"])),
            **{
                k: text(d.get(k, ""))
                for k in ["contact", "reference", "dispatchThrough", "destination", "deliveryTerms", "note"]
            },
        )
        require(values["due"] >= entry_date and values["tax"] <= 100, "Check delivery date and tax rate.")
        if action == "editOrder":
            r = get(s, "orders", d["id"])
            voucher_date(s, r["date"])
            require(
                r["status"] not in {"Cancelled", "Closed"}
                and not any(x["po"] == r["id"] for x in s["receipts"] + s["invoices"]),
                "Order with downstream documents cannot be amended.",
            )
            reason = text(d.get("reason"), "Amendment reason", True)
            r["history"].append(
                {**{k: v for k, v in deepcopy(r).items() if k != "history"}, "reason": reason}
            )
            r.update(values, status="Draft", approvals=[], revision=r["revision"] + 1, createdBy=actor["id"])
        else:
            r = dict(
                id=identifier(s, "PO"),
                status="Draft",
                approvals=[],
                history=[],
                revision=1,
                source=text(d.get("source", "Manual")),
                createdBy=actor["id"],
                **values,
            )
            s["orders"].insert(0, r)
    elif action in {"submit", "approve", "reject", "dispatch", "ack", "cancel", "close", "preclose"}:
        r = get(s, "orders", d["id"])
        if action == "submit":
            require(
                r["status"] == "Draft" and qualified(get(s, "suppliers", r["supplier"])),
                "Submit a draft with a qualified supplier.",
            )
            from .approval_policy import route, begin_stage
            r.update(status="Pending approval", approvals=[], approvalRoute=route(s, r))
            begin_stage(r)
        elif action == "approve":
            require(
                r["status"] == "Pending approval" and qualified(get(s, "suppliers", r["supplier"])),
                "Order must be pending with a qualified supplier.",
            )
            from .approval_policy import route, automatic_allowed, base_value, current_delegate, begin_stage, same_route
            current_route = route(s, r)
            require(same_route(r.get("approvalRoute", current_route), current_route),
                    "Approval policy changed. Reject and resubmit this order for fresh approvals.")
            stages = current_route["stages"]
            require(len(r["approvals"]) < len(stages), "All approval stages are already complete.")
            stage = stages[len(r["approvals"])]
            delegation = current_delegate(r)
            require(not delegation or actor["id"] == delegation["userId"] or actor["role"] == "admin",
                    "This stage is assigned to a named substitute. An administrator can revoke the assignment.")
            require(actor["role"] in {"admin", stage, "system"}, "This step requires the " + stage + " role.")
            if actor["role"] == "system":
                require(
                    automatic_allowed(s, r),
                    "Order exceeds automated approval authority.",
                )
            elif s["settings"]["separation"]:
                require(
                    r["createdBy"] != actor["id"]
                    and not any(a["actor"] == actor["id"] for a in r["approvals"]),
                    "A different user must approve each stage.",
                )
            committed = sum(
                dec(base_value(o))
                for o in s["orders"]
                if o["id"] != r["id"]
                and o["date"][:7] == r["date"][:7]
                and o["status"] in ACTIVE_PO | {"Approved", "Closed"}
            )
            require(
                committed + dec(base_value(r)) <= dec(s["settings"]["budgetMonthly"]),
                "Monthly purchase budget exceeded.",
            )
            r["approvals"].append(dict(role=stage, actor=actor["id"], revision=r["revision"]))
            if len(r["approvals"]) == len(stages):
                r["status"] = "Approved"
                r["approvalDueAt"] = None
                r.pop("approvalDelegate", None)
                r.pop("approvalEscalation", None)
            else:
                begin_stage(r)
        elif action == "reject":
            require(r["status"] == "Pending approval", "Only pending orders can be rejected.")
            r.update(status="Draft", approvals=[], rejection=text(d.get("reason"), "Reason", True))
        elif action in {"dispatch", "ack"}:
            require(action != "dispatch" or qualified(get(s, "suppliers", r["supplier"])),
                    "Supplier qualification expired or was revoked before dispatch.")
            require(
                r["status"] == ("Approved" if action == "dispatch" else "Issued"),
                "Order is not ready for this transition.",
            )
            r["status"] = "Issued" if action == "dispatch" else "Acknowledged"
        elif action == "cancel":
            require(
                r["status"] not in {"Closed", "Cancelled"}
                and not any(
                    x["po"] == r["id"] and x["status"] not in {"Rejected", "Void"}
                    for x in s["receipts"] + s["invoices"]
                ),
                "Resolve downstream documents before cancellation.",
            )
            r.update(status="Cancelled", cancelReason=text(d.get("reason"), "Reason", True))
        elif action == "preclose":
            require(r["status"] in ACTIVE_PO | {"Approved"}, "Order cannot be preclosed.")
            for line in lines(s, d["lines"]):
                pl = next((l for l in r["lines"] if l["item"] == line["item"]), None)
                used = max(
                    received(s, r["id"], line["item"], True),
                    billed(s, r["id"], line["item"]) - credited(s, r["id"], line["item"]),
                )
                require(
                    pl is not None and line["qty"] <= effective(pl) - used + 0.000001,
                    "Preclosure exceeds unused quantity.",
                )
                pl["closedQty"] = pl.get("closedQty", 0) + line["qty"]
            r["precloseReason"] = text(d.get("reason"), "Reason", True)
            if r["status"] != "Approved":
                receipt_status(s, r)
        else:
            require(
                r["status"] == "Received"
                and all(
                    abs(
                        billed(s, r["id"], l["item"], posted=True)
                        - credited(s, r["id"], l["item"])
                        - effective(l)
                    )
                    < 0.000001
                    for l in r["lines"]
                )
                and all(
                    i["status"] in POSTED and balance(s, i) == 0
                    for i in s["invoices"]
                    if i["po"] == r["id"] and i["status"] != "Void"
                ),
                "Close only fully received, billed and settled orders.",
            )
            r["status"] = "Closed"
    elif action == "receipt":
        po = get(s, "orders", d["po"])
        require(po["status"] in ACTIVE_PO, "Receive only issued active orders.")
        ls = lines(s, d["lines"])
        for line in ls:
            pl = next((l for l in po["lines"] if l["item"] == line["item"]), None)
            require(
                pl is not None
                and line["qty"] + received(s, po["id"], line["item"], True) <= effective(pl) + 0.000001,
                "Receipt exceeds remaining quantity.",
            )
            line["price"] = pl["price"]
            line["discount"] = pl.get("discount", 0)
        inspection = any(
            get(s, "items", line["item"]).get("inspectionRequired", get(s, "items", line["item"]).get("quality", False))
            for line in ls
        )
        entry_date = voucher_date(s, d.get("date"))
        require(entry_date >= po["date"], "Receipt cannot precede its order.")
        r = dict(
            id=identifier(s, "GRN"),
            po=po["id"],
            date=entry_date,
            warehouse=po["warehouse"],
            lines=ls,
            status="Inspection hold" if inspection else "Accepted",
            createdBy=actor["id"],
            **{
                k: text(d.get(k, ""))
                for k in [
                    "batch",
                    "certificate",
                    "deliveryNote",
                    "vehicle",
                    "transporter",
                    "manufactured",
                    "expiry",
                ]
            },
        )
        require(not inspection or r["batch"], "Lot reference is required for inspection-controlled material.")
        require(
            not r["expiry"] or valid_date(r["expiry"]) > entry_date, "Expired material cannot be received."
        )
        require(
            not r["manufactured"] or valid_date(r["manufactured"]) <= entry_date,
            "Manufacture date cannot follow receipt date.",
        )
        s["receipts"].insert(0, r)
        if not inspection:
            for line in ls:
                from .inventory import receipt_tracking
                stock(s, actor, line["item"], line["qty"], r["id"], "Receipt", r["warehouse"], **receipt_tracking(r, line, s))
        receipt_status(s, po)
    elif action in {"accept", "rejectReceipt"}:
        r = get(s, "receipts", d["id"])
        require(r["status"] in {"Inspection hold", "Quality hold"}, "Receipt is not awaiting inspection.")
        r.update(
            status="Accepted" if action == "accept" else "Rejected",
            qualityNote=text(d.get("reason"), "Inspection result", True),
            inspectedBy=actor["id"],
        )
        if action == "accept":
            for line in r["lines"]:
                from .inventory import receipt_tracking
                stock(s, actor, line["item"], line["qty"], r["id"], "Inspection release", r["warehouse"], **receipt_tracking(r, line, s))
        receipt_status(s, get(s, "orders", r["po"]))
    elif action in {"invoice", "editInvoice"}:
        po = get(s, "orders", d["po"])
        require(po["status"] in ACTIVE_PO, "Choose an issued active PO.")
        old = get(s, "invoices", d["id"]) if action == "editInvoice" else None
        if old:
            voucher_date(s, old["date"])
            require(
                old["status"] not in POSTED | {"Void"} and old["po"] == po["id"],
                "Posted or void invoices cannot be edited or moved.",
            )
        number = text(d.get("number"), "Supplier invoice reference", True)
        require(
            not any(
                i["id"] != d.get("id")
                and i["supplier"] == po["supplier"]
                and i["number"].casefold() == number.casefold()
                for i in s["invoices"]
            ),
            "Duplicate supplier invoice reference.",
        )
        ls = lines(s, d["lines"])
        for line in ls:
            pl = next((l for l in po["lines"] if l["item"] == line["item"]), None)
            require(
                pl is not None
                and billed(s, po["id"], line["item"], d.get("id"))
                + line["qty"]
                - credited(s, po["id"], line["item"])
                <= effective(pl) + 0.000001,
                "Invoice exceeds unbilled quantity.",
            )
        entry_date = voucher_date(s, d.get("date"))
        supplier_date = valid_date(d.get("supplierDate") or entry_date)
        require(entry_date >= po["date"] and supplier_date <= entry_date, "Check invoice dates.")
        values = dict(
            po=po["id"],
            supplier=po["supplier"],
            number=number,
            date=entry_date,
            supplierDate=supplier_date,
            due=valid_date(d.get("due") or add_days(supplier_date, po["paymentDays"])),
            lines=ls,
            tax=amount(d.get("tax", po["tax"])),
            freight=amount(d.get("freight", 0)),
            amount=amount(d.get("amount"), True),
            purchaseLedger=po["purchaseLedger"],
            costCentre=po["costCentre"],
            status="Pending match",
            reason="",
            note=text(d.get("note", "")),
        )
        require(values["tax"] <= 100 and values["due"] >= supplier_date, "Check tax and due date.")
        r = old if old else dict(id=identifier(s, "BILL"), createdBy=actor["id"])
        r.update(values)
        if not old:
            s["invoices"].insert(0, r)
    elif action in {"match", "post", "voidInvoice"}:
        r = get(s, "invoices", d["id"])
        require(r["status"] not in POSTED | {"Void"}, "Posted or void invoices cannot be changed.")
        if action == "match":
            r["reason"] = match(s, r)
            r["status"] = "Exception" if r["reason"] else "Matched"
        elif action == "voidInvoice":
            r.update(status="Void", reason=text(d.get("reason"), "Reason", True))
        else:
            require(r["status"] == "Matched" and not match(s, r), "A current successful match is required.")
            voucher_date(s, r["date"])
            t = totals(r)
            variance = money(dec(r["amount"]) - dec(t["total"]))
            journal(
                s,
                r["id"],
                "Supplier bill",
                [
                    dict(account=get(s, "ledgers", r["purchaseLedger"])["name"], debit=t["subtotal"]),
                    dict(account="Input tax", debit=t["tax"]),
                    dict(account="Freight", debit=t["freight"]),
                    dict(account="Rounding", debit=max(variance, 0), credit=max(-variance, 0)),
                    dict(account="Accounts payable", credit=r["amount"]),
                ],
                r["date"],
            )
            r["status"] = "Posted"
    elif action == "pay":
        invoice = get(s, "invoices", d["id"])
        value = amount(d.get("amount"), True)
        require(
            invoice["status"] in POSTED and value <= balance(s, invoice),
            "Payment exceeds the unpaid posted balance.",
        )
        reference = text(d.get("reference"), "External payment reference", True)
        require(
            not any(p["reference"].casefold() == reference.casefold() for p in s["payments"]),
            "Payment reference already recorded.",
        )
        entry_date = voucher_date(s, d.get("date"))
        require(entry_date >= invoice["date"], "Payment cannot precede the bill.")
        bank = active(s, "ledgers", d.get("bankLedger", "LED-BANK"))
        require(bank["type"] in {"bank", "cash"}, "Choose a bank or cash ledger.")
        r = dict(
            id=identifier(s, "PAY"),
            invoice=invoice["id"],
            amount=value,
            reference=reference,
            date=entry_date,
            bankLedger=bank["id"],
            status="Recorded",
            method=text(d.get("method", "Bank transfer")),
            note=text(d.get("note", "")),
        )
        s["payments"].insert(0, r)
        journal(
            s,
            r["id"],
            "External payment recorded",
            [dict(account="Accounts payable", debit=value), dict(account=bank["name"], credit=value)],
            entry_date,
        )
        invoice_status(s, invoice)
    elif action == "reversePayment":
        r = get(s, "payments", d["id"])
        invoice = get(s, "invoices", r["invoice"])
        require(
            r["status"] != "Reversed" and get(s, "orders", invoice["po"])["status"] != "Closed",
            "Payment cannot be reversed.",
        )
        voucher_date(s, r["date"])
        entry_date = voucher_date(s, d.get("date"))
        require(entry_date >= r["date"], "Reversal cannot precede payment.")
        r.update(
            status="Reversed", reversalReason=text(d.get("reason"), "Reason", True), reversalDate=entry_date
        )
        journal(
            s,
            r["id"],
            "Payment reversal",
            [
                dict(account=get(s, "ledgers", r["bankLedger"])["name"], debit=r["amount"]),
                dict(account="Accounts payable", credit=r["amount"]),
            ],
            entry_date,
        )
        invoice_status(s, invoice)
    elif action == "credit":
        invoice = get(s, "invoices", d["invoice"])
        require(
            invoice["status"] in POSTED
            and get(s, "orders", invoice["po"])["status"] != "Closed",
            "Credit requires an unpaid posted balance on an open order.",
        )
        number = text(d.get("number"), "Credit reference", True)
        require(
            not any(
                c["supplier"] == invoice["supplier"] and c["number"].casefold() == number.casefold()
                for c in s["credits"]
            ),
            "Duplicate credit reference.",
        )
        ls = lines(s, d["lines"])
        for line in ls:
            il = next((l for l in invoice["lines"] if l["item"] == line["item"]), None)
            used = sum_qty([c for c in s["credits"] if c["invoice"] == invoice["id"]], line["item"])
            require(
                il is not None and line["qty"] + used <= il["qty"],
                "Credit exceeds remaining invoiced quantity.",
            )
            line.update({k: v for k, v in il.items() if k not in {"qty"}})
        t = totals(dict(lines=ls, tax=invoice["tax"]))
        require(t["total"] > 0, "Credit must be positive.")
        entry_date = voucher_date(s, d.get("date"))
        require(entry_date >= invoice["date"], "Credit cannot precede invoice.")
        r = dict(
            id=identifier(s, "CR"),
            invoice=invoice["id"],
            po=invoice["po"],
            supplier=invoice["supplier"],
            number=number,
            lines=ls,
            tax=invoice["tax"],
            amount=t["total"],
            date=entry_date,
            reason=text(d.get("reason"), "Reason", True),
        )
        s["credits"].insert(0, r)
        journal(
            s,
            r["id"],
            "Supplier credit",
            [
                dict(account="Accounts payable", debit=t["total"]),
                dict(account=get(s, "ledgers", invoice["purchaseLedger"])["name"], credit=t["subtotal"]),
                dict(account="Input tax", credit=t["tax"]),
            ],
            entry_date,
        )
        invoice_status(s, invoice)
    elif action == "return":
        receipt = get(s, "receipts", d["receipt"])
        po = get(s, "orders", receipt["po"])
        require(
            receipt["status"] == "Accepted" and po["status"] != "Closed",
            "Return requires an accepted receipt on an open order.",
        )
        ls = lines(s, d["lines"])
        for line in ls:
            original = next((l for l in receipt["lines"] if l["item"] == line["item"]), None)
            previous = sum_qty([r for r in s["returns"] if r["receipt"] == receipt["id"]], line["item"])
            require(
                original is not None and line["qty"] + previous <= original["qty"],
                "Return exceeds receipt quantity.",
            )
            require(
                received(s, po["id"], line["item"]) - line["qty"]
                >= billed(s, po["id"], line["item"], posted=True) - credited(s, po["id"], line["item"]),
                "Credit posted goods before returning.",
            )
            line["price"] = original["price"]
        entry_date = voucher_date(s, d.get("date"))
        require(entry_date >= receipt["date"], "Return cannot precede receipt.")
        r = dict(
            id=identifier(s, "RTN"),
            po=po["id"],
            receipt=receipt["id"],
            lines=ls,
            date=entry_date,
            reason=text(d.get("reason"), "Reason", True),
        )
        s["returns"].insert(0, r)
        for line in ls:
            from .inventory import receipt_tracking
            original = next(l for l in receipt["lines"] if l["item"] == line["item"])
            location = receipt_tracking(receipt, original, s)
            location["entry_date"] = entry_date
            stock(s, actor, line["item"], -line["qty"], r["id"], "Supplier return", receipt["warehouse"], **location)
        receipt_status(s, po)
        for invoice in s["invoices"]:
            if invoice["po"] == po["id"] and invoice["status"] not in POSTED | {"Void"}:
                invoice.update(status="Pending match", reason="Receipt changed after return")
    elif action == "master":
        collection = d.get("collection")
        require(collection in {"warehouses", "costCentres", "ledgers", "branches", "bins", "taxProfiles", "customers", "contracts", "approvalPolicies", "automationRules"}, "Unsupported master.")
        name = text(d.get("name"), "Name", True)
        require(
            not any(
                m["name"].casefold() == name.casefold() and m["id"] != d.get("id") for m in s[collection]
            ),
            "Master name already exists.",
        )
        if collection == "ledgers":
            require(d.get("type") in {"purchase", "bank", "cash"}, "Invalid ledger type.")
            from .finance import chart
            require(not any(a["id"]!=d.get("id") and a["name"].casefold()==name.casefold() for a in chart(s)),"Reserved or existing account name.")
        r = get(s, collection, d["id"]) if d.get("id") else dict(id=identifier(s, "MASTER"))
        require(
            collection != "ledgers"
            or not s["journal"]
            or not d.get("id")
            or (name == r["name"] and d["type"] == r["type"]),
            "Used ledger cannot be renamed or reclassified.",
        )
        r.update(
            name=name,
            address=text(d.get("address", "")),
            active=d.get("active", True),
            type=d.get("type", ""),
        )
        if collection == "bins":
            require(not d.get("id") or not any(p["bin"] == r["id"] for p in s["stockPositions"])
                    or r.get("warehouse") == d.get("warehouse", "WH-MAIN"), "A used bin cannot be moved to another warehouse.")
            r["warehouse"] = active(s, "warehouses", d.get("warehouse", "WH-MAIN"))["id"]
        if collection == "taxProfiles":
            r["rate"] = amount(d.get("rate", 0))
            require(r["rate"] <= 100, "Tax rate cannot exceed 100%.")
        if collection == "customers":
            r.update(
                email=text(d.get("email", "")),
                phone=text(d.get("phone", "")),
                taxId=text(d.get("taxId", "")),
                creditDays=int(amount(d.get("creditDays", 0))),
                creditLimit=amount(d.get("creditLimit", 0)),
            )
        if collection in {"contracts", "approvalPolicies", "automationRules"}:
            r["description"] = text(d.get("description", ""))
        if collection == "approvalPolicies":
            from .approval_policy import configure
            configure(s, r, d)
        if not d.get("id"):
            s[collection].append(r)
    elif action == "priceAgreement":
        get(s, "suppliers", d["supplier"])
        get(s, "items", d["item"])
        start, end = valid_date(d["validFrom"]), valid_date(d["validUntil"])
        require(
            start <= end
            and not any(
                p["supplier"] == d["supplier"]
                and p["item"] == d["item"]
                and p["validFrom"] <= end
                and p["validUntil"] >= start
                for p in s["prices"]
            ),
            "Agreement dates overlap or are invalid.",
        )
        r = dict(
            id=identifier(s, "RATE"),
            supplier=d["supplier"],
            item=d["item"],
            validFrom=start,
            validUntil=end,
            price=amount(d["price"]),
            discount=amount(d.get("discount", 0)),
            taxRate=amount(d.get("taxRate", s["settings"]["defaultTax"])),
            reference=text(d.get("reference"), "Reference", True),
        )
        require(r["discount"] <= 100 and r["taxRate"] <= 100, "Tax or discount exceeds 100%.")
        s["prices"].insert(0, r)
    elif action == "settings":
        if 'reorderMethod' in d:
            require(d['reorderMethod'] in {'threshold', 'forecast'}, 'Choose threshold or forecast replenishment.')
            s['settings']['reorderMethod'] = d['reorderMethod']
        for key in ["company", "address", "phone", "email", "taxId", "country", "legalEntityType", "industryTemplate", "taxRegistrationStatus", "currency", "timezone", "fiscalYearStart", "taxRegime"]:
            if key in d:
                s["settings"][key] = text(d[key], key, key == "company")
        require(re.fullmatch(r"[A-Z]{3}", s["settings"]["currency"]), "Currency must be a three-letter ISO code.")
        try:
            ZoneInfo(s["settings"]["timezone"])
        except Exception:
            raise RuleError("Timezone must be a valid IANA timezone.") from None
        try:
            datetime.strptime("2000-" + s["settings"]["fiscalYearStart"], "%Y-%m-%d")
        except ValueError:
            raise RuleError("Fiscal year start must use MM-DD.") from None
        s["settings"]["onboardingCompleted"] = bool(
            s["settings"]["company"]
            and s["settings"]["country"]
            and s["settings"]["legalEntityType"]
            and s["settings"]["industryTemplate"]
            and s["settings"]["currency"]
            and s["settings"]["taxRegime"]
        )
        for key in ["autoPO", "autoApprove", "autoMatch", "autoReorder", "separation"]:
            if key in d:
                require(isinstance(d[key], bool), "Boolean policy value required.")
                s["settings"][key] = d[key]
        for key in [
            "limit",
            "financeThreshold",
            "budgetMonthly",
            "priceTolerance",
            "invoiceTolerance",
            "defaultTax",
            "paymentDays",
        ]:
            if key in d:
                s["settings"][key] = amount(d[key])
        require(
            s["settings"]["priceTolerance"] <= 25
            and s["settings"]["invoiceTolerance"] <= 1
            and s["settings"]["defaultTax"] <= 100,
            "Policy tolerance exceeds supported limit.",
        )
        if "mode" in d:
            require(d["mode"] in {"manual", "automatic"}, "Invalid processing mode.")
            s["settings"]["mode"] = d["mode"]
        if "modules" in d:
            require(isinstance(d["modules"], dict), "Modules must be an object.")
            known_modules = set(s["settings"]["modules"])
            require(set(d["modules"]).issubset(known_modules), "Unknown industry module.")
            require(all(isinstance(value, bool) for value in d["modules"].values()), "Module values must be true or false.")
            s["settings"]["modules"].update(d["modules"])
        if "lockedThrough" in d:
            require(
                not d["lockedThrough"] or valid_date(d["lockedThrough"]) <= today(),
                "Cannot lock a future period.",
            )
            s["settings"]["lockedThrough"] = d["lockedThrough"]
        r = {"id": "POLICY"}
    elif action in {"saveDraft", "deleteDraft"}:
        require(allowed(actor, d.get("kind")), "Your role cannot save this voucher type.")
        key = actor["id"] + ":" + d["kind"] + ":" + d.get("record", "")
        s["drafts"] = [v for v in s["drafts"] if v["key"] != key]
        r = dict(
            id=identifier(s, "DRF"),
            key=key,
            actor=actor["id"],
            kind=d["kind"],
            record=d.get("record", ""),
            values=d.get("values", {}),
        )
        if action == "saveDraft":
            s["drafts"].append(r)
    elif action == "comment":
        require(
            d["collection"] in {"orders", "requisitions", "receipts", "invoices"}, "Invalid comment target."
        )
        get(s, d["collection"], d["id"])
        r = dict(
            id=identifier(s, "NOTE"),
            target=d["id"],
            collection=d["collection"],
            text=text(d.get("text"), "Comment", True),
            actor=actor["id"],
        )
        s["comments"].insert(0, r)
    else:
        from .finance import finance_action

        r = finance_action(s, action, d, actor)
    return r


def automation_plan(s):
    require(s["settings"]["mode"] == "automatic", "Switch to automatic mode first.")
    commands = []
    if s["settings"]["autoReorder"] and s['settings'].get('reorderMethod', 'threshold') == 'forecast':
        commands.extend(('forecastRequisition', {'item': r['item']})
            for r in procurement_insights(s)['forecastPurchaseRecommendations'] if not r['blockedReason'])
    elif s["settings"]["autoReorder"]:
        for item in s["items"]:
            pending = any(
                any(l["item"] == item["id"] for l in r["lines"])
                for r in s["requisitions"] + s["orders"]
                if r["status"] not in {"Rejected", "Converted", "Cancelled", "Closed", "Received"}
            )
            if (
                item["stock"] < item["reorder"]
                and not pending
                and qualified(get(s, "suppliers", item["supplier"]))
            ):
                qty = (
                    ceil(max(item["target"] - item["stock"], item["minOrder"]) / item["packSize"])
                    * item["packSize"]
                )
                rate = suggest(s, item["supplier"], item["id"])
                commands.append(
                    (
                        "requisition",
                        dict(
                            department="Inventory",
                            note="Reorder rule",
                            lines=[
                                dict(
                                    item=item["id"],
                                    qty=qty,
                                    **{k: rate[k] for k in ["price", "discount", "taxRate"] if k in rate},
                                )
                            ],
                        ),
                    )
                )
    if s["settings"]["autoPO"]:
        commands.extend(("convert", {"id": r["id"]}) for r in s["requisitions"] if r["status"] == "Approved")
    if s["settings"]["autoApprove"]:
        for order in s["orders"]:
            from .approval_policy import automatic_allowed
            if automatic_allowed(s, order):
                if order["status"] == "Draft":
                    commands.extend([("submit", {"id": order["id"]}), ("approve", {"id": order["id"]})])
                elif order["status"] == "Pending approval":
                    commands.append(("approve", {"id": order["id"]}))
    if s["settings"]["autoMatch"]:
        for invoice in s["invoices"]:
            if invoice["status"] in {"Pending match", "Exception", "Matched"} and (
                invoice["status"] == "Pending match" or invoice.get("reason") != match(s, invoice)
            ):
                commands.append(("match", {"id": invoice["id"]}))
    return commands


def procurement_insights(s, lookback_days=90):
    """Read-only recommendations; no purchase order is created without the normal policy path."""
    from .procurement_analysis import insights
    return insights(s, lookback_days)
