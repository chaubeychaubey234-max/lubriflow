"""Explainable purchasing recommendations; no autonomous commercial commitments."""
from datetime import date, timedelta
from decimal import ROUND_CEILING
from .domain import dec, get, money, quantity, require, today, totals, effective, received, qualified


def insights(s, lookback_days=90):
    lookback_days = int(lookback_days)
    require(30 <= lookback_days <= 365, 'Lookback must be 30–365 days.')
    end = today()
    cutoff = (date.fromisoformat(end) - timedelta(days=lookback_days - 1)).isoformat()
    by_item, baskets = {}, {}
    for quote in s['quotes']:
        if quote['status'] != 'Received' or quote['valid'] < end:
            continue
        supplier = get(s, 'suppliers', quote['supplier'])
        rate = dec(quote.get('rate', 1))
        total = totals(quote)['total']
        offer = dict(quote=quote['id'], supplier=supplier['id'], qualified=qualified(supplier),
                     leadDays=quote['leadDays'], currency=quote.get('currency', s['settings']['currency']),
                     rate=str(rate), total=total, baseTotal=money(dec(total) * rate),
                     freight=quote.get('freight', 0), paymentDays=quote.get('paymentDays', 30), valid=quote['valid'])
        # Only identical item/quantity baskets are ranked against each other.
        key = tuple(sorted((l['item'], format(dec(l['qty']).normalize(), 'f')) for l in quote['lines']))
        baskets.setdefault(key, []).append(offer)
        for line in quote['lines']:
            unit = dec(line['price']) * (1 - dec(line.get('discount', 0)) / 100)
            by_item.setdefault(line['item'], []).append(dict(offer, price=line['price'], qty=line['qty'],
                discount=line.get('discount', 0), baseUnitPrice=money(unit * rate)))
    comparisons = [dict(item=item, offers=sorted(offers, key=lambda x: (not x['qualified'], x['baseUnitPrice'], x['leadDays'])))
                   for item, offers in by_item.items()]
    basket_comparisons = [dict(lines=[dict(item=i, qty=q) for i, q in key],
        offers=sorted(offers, key=lambda x: (not x['qualified'], x['baseTotal'], x['leadDays'])))
        for key, offers in baskets.items()]
    scorecards = []
    for supplier in s['suppliers']:
        orders = {o['id']: o for o in s['orders'] if o['supplier'] == supplier['id']}
        receipts = [r for r in s['receipts'] if r['po'] in orders and cutoff <= r['date'] <= end]
        decided = [r for r in receipts if r['status'] in {'Accepted', 'Rejected'}]
        accepted = [r for r in decided if r['status'] == 'Accepted']
        on_time = sum(r['date'] <= orders[r['po']]['due'] for r in accepted)
        scorecards.append(dict(supplier=supplier['id'], receipts=len(receipts), evaluatedReceipts=len(decided),
            pendingInspection=len(receipts)-len(decided), qualified=qualified(supplier),
            qualificationUntil=supplier.get('qualificationUntil', ''),
            acceptanceRate=money(100 * dec(len(accepted)) / dec(len(decided))) if decided else None,
            onTimeRate=money(100 * dec(on_time) / dec(len(accepted))) if accepted else None))
    forecast = []
    for item in s['items']:
        demand = [m for m in s['stockMoves'] if m['item'] == item['id'] and dec(m['qty']) < 0
                  and (m.get('demand') is True or m.get('type') in {'Customer delivery', 'Production consumption'})
                  and cutoff <= (m.get('date') or m['at'][:10]) <= end]
        issued = -sum((dec(m['qty']) for m in demand), dec(0))
        daily = issued / dec(lookback_days)
        if not daily:
            continue
        positions = [p for p in s['stockPositions'] if p['item'] == item['id']]
        if item.get('positionsInitialized'):
            available = sum((dec(p['qty']) for p in positions if p['status'] == 'Available'
                and (not p.get('expiry') or p['expiry'] > end)), dec(0))
        else:
            available = dec(item['stock'])
        available_ids = {p['id'] for p in positions if p['status'] == 'Available'
            and (not p.get('expiry') or p['expiry'] > end)}
        reserved = sum((dec(r['remaining']) for r in s['reservations']
            if r['status'] == 'Active' and r['position'] in available_ids), dec(0))
        available = max(dec(0), available - reserved)
        incoming = sum((max(dec(0), dec(effective(l)) - dec(received(s, o['id'], item['id'], True)))
            for o in s['orders'] if o['status'] in {'Issued', 'Acknowledged', 'Part received'}
            and end <= o['due'] <= (date.fromisoformat(end) + timedelta(days=item['leadDays'] + 7)).isoformat()
            for l in o['lines'] if l['item'] == item['id']), dec(0))
        pending = any(any(l['item'] == item['id'] for l in r['lines'])
            for r in s['requisitions'] + s['orders']
            if r['status'] in {'Pending', 'Approved', 'Draft', 'Pending approval'})
        projected = available + incoming
        if projected > daily * dec(item['leadDays'] + 7):
            continue
        target = max(dec(item['target']), daily * dec(item['leadDays'] + 14))
        needed = max(target - projected, dec(item['minOrder']))
        pack = dec(item['packSize'])
        rounded = (needed / pack).to_integral_value(rounding=ROUND_CEILING) * pack
        supplier = get(s, 'suppliers', item['supplier'])
        forecast.append(dict(item=item['id'], supplier=item['supplier'], averageDailyDemand=float(daily),
            observedDemand=float(issued), demandMovements=len(demand), lookbackDays=lookback_days,
            available=float(available), reserved=float(reserved), incoming=float(incoming),
            daysOfCover=money(available / daily), suggestedQty=quantity(rounded),
            blockedReason='Existing requisition or draft/approved order' if pending else
                'Supplier qualification expired or missing' if not qualified(supplier) else '',
            method='Trailing daily average; lead time plus 7-day trigger / 14-day target buffer'))
    return dict(quoteComparisons=comparisons, basketComparisons=basket_comparisons,
        supplierScorecards=scorecards, forecastPurchaseRecommendations=forecast, baseCurrency=s['settings']['currency'],
        period=dict(start=cutoff, end=end, days=lookback_days),
        demandBasis='Customer deliveries, production consumption and explicitly classified stock issues. Transfers, counts, returns and unclassified legacy issues are excluded.')
