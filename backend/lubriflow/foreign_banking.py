"""Foreign bank units and base carrying values, with settlement/revaluation differences."""

from .domain import require, dec, money, amount, identifier, voucher_date, text


def balance(s, bank, day):
    units = sum(
        (dec(m["units"]) for m in s["bankFxMovements"] if m["bank"] == bank["id"] and m["date"] <= day),
        dec(0),
    )
    base = sum(
        (
            dec(l.get("debit", 0)) - dec(l.get("credit", 0))
            for j in s["journal"]
            if j["date"] <= day
            for l in j["entries"]
            if l["account"] == bank["name"]
        ),
        dec(0),
    )
    return units, base


def adjust(s, entries, bank, currency, units, spot, day, reference):
    """Replace the spot bank leg with its carrying value for an outgoing foreign payment."""
    if bank.get("currency", s["settings"]["currency"]) == s["settings"]["currency"]:
        return
    require(bank["currency"] == currency, "Transaction currency must match the foreign bank account.")
    require(
        not any(m["bank"] == bank["id"] and m["date"] > day for m in s["bankFxMovements"]),
        "Foreign bank transactions must be chronological.",
    )
    require(
        not any(
            r["date"] > day and any(x["bank"] == bank["id"] for x in r.get("banks", []))
            for r in s["fxRevaluations"]
        ),
        "Cannot post before a later bank revaluation.",
    )
    units = dec(units)
    spot = dec(spot)
    current, carrying = balance(s, bank, day)
    value = spot
    if units < 0:
        require(
            current >= -units, "Insufficient foreign currency units; overdrafts require a separate facility."
        )
        value = carrying if -units == current else dec(money(carrying * (-units) / current))
        line = next(l for l in entries if l["account"] == bank["name"])
        line["credit"] = money(value)
        difference = value - spot
        if difference:
            entries.append(
                dict(
                    account="Foreign exchange differences",
                    debit=money(max(difference, dec(0))),
                    credit=money(max(-difference, dec(0))),
                )
            )
    s["bankFxMovements"].append(
        dict(
            id=identifier(s, "BFX"),
            bank=bank["id"],
            date=day,
            currency=currency,
            units=float(units),
            baseValue=money(value if units > 0 else -value),
            spotBase=money(spot if units > 0 else -spot),
            reference=reference,
        )
    )


def action(s, command, d, actor):
    from .finance import active_ledger
    from .accounting import fx, post

    require(actor["role"] in {"admin", "finance"}, "Finance access required.")
    if command == "bankCurrency":
        bank = active_ledger(s, d["bankLedger"])
        currency = text(d["currency"]).upper()
        require(len(currency) == 3 and currency.isalpha(), "Use a three-letter currency code.")
        require(
            not any(l["account"] == bank["name"] for j in s["journal"] for l in j["entries"]),
            "Set bank currency before its first posting.",
        )
        bank["currency"] = currency
        return bank
    day = voucher_date(s, d.get("date"))
    source = active_ledger(s, d["fromBank"])
    target = active_ledger(s, d["toBank"])
    require(source["id"] != target["id"], "Choose different bank accounts.")
    source_currency = source.get("currency", s["settings"]["currency"])
    target_currency = target.get("currency", s["settings"]["currency"])
    outgoing = amount(d["fromAmount"], True)
    incoming = amount(d["toAmount"], True)
    source_rate = fx(s, source_currency, day, d.get("fromRate"))
    target_rate = fx(s, target_currency, day, d.get("toRate"))
    base = money(dec(outgoing) * source_rate)
    require(
        base == money(dec(incoming) * target_rate),
        "Transfer sides must have the same base value; record bank fees separately.",
    )
    ref = text(d.get("reference"), "Bank reference", True)
    require(not any(j["reference"] == ref for j in s["journal"]), "Bank transfer reference already used.")
    entries = [dict(account=source["name"], credit=base), dict(account=target["name"], debit=base)]
    adjust(s, entries, source, source_currency, -dec(outgoing), base, day, ref)
    adjust(s, entries, target, target_currency, dec(incoming), base, day, ref)
    return post(s, ref, "Currency bank transfer", entries, day, cashFlowClass="Operating")


def revalue(s, day):
    from .accounting import fx

    entries = []
    banks = []
    for bank in s["ledgers"]:
        currency = bank.get("currency", s["settings"]["currency"])
        if bank["type"] not in {"bank", "cash"} or currency == s["settings"]["currency"]:
            continue
        require(
            not any(m["bank"] == bank["id"] and m["date"] > day for m in s["bankFxMovements"]),
            "Revalue before later foreign bank movements.",
        )
        units, carrying = balance(s, bank, day)
        rate = fx(s, currency, day)
        difference = dec(money(units * rate)) - carrying
        banks.append(
            dict(
                bank=bank["id"],
                currency=currency,
                units=float(units),
                rate=str(rate),
                difference=money(difference),
            )
        )
        if difference:
            entries.extend(
                [
                    dict(
                        account=bank["name"],
                        debit=money(max(difference, dec(0))),
                        credit=money(max(-difference, dec(0))),
                    ),
                    dict(
                        account="Foreign exchange differences",
                        debit=money(max(-difference, dec(0))),
                        credit=money(max(difference, dec(0))),
                    ),
                ]
            )
    return entries, banks
