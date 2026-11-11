"""Multilevel on-hand material planning with explicit BOM choices and reviewed execution."""
from copy import deepcopy
from decimal import ROUND_CEILING
import hashlib
import json
from .domain import (get, active, require, quantity, dec, today, text, suggest, voucher_date)
from .inventory import ensure_positions, held


def plan(state, data):
    require(state['settings']['modules'].get('manufacturing'), 'Enable the manufacturing module first.')
    s = deepcopy(state)
    planning_date = voucher_date(s)
    root = get(s, 'boms', data.get('bom'))
    require(root['status'] == 'Active', 'Choose an active root BOM.')
    qty = quantity(data.get('qty'))
    warehouse = active(s, 'warehouses', data.get('warehouse', 'WH-MAIN'))['id']
    reference = text(data.get('reference', ''), 'Planning reference', True)
    require(len(reference) <= 100, 'Planning reference must fit 100 characters.')
    require(not any(o.get('planningReference', '').casefold() == reference.casefold()
                    for o in s['productionOrders']), 'This planning reference has already been created.')
    choices = data.get('bomSelections', {})
    require(isinstance(choices, dict) and len(choices) <= 200, 'Choose BOM versions by item.')
    require(all(isinstance(k, str) and isinstance(v, str) for k, v in choices.items()), 'Invalid BOM selections.')
    create_requests = data.get('createPurchaseRequests', False)
    require(isinstance(create_requests, bool), 'Purchase request option must be yes or no.')
    selected, children, finished, visiting = {}, {}, [], set()

    def visit(item_id, depth=0):
        require(depth <= 30, 'BOM nesting exceeds 30 levels.')
        require(item_id not in visiting, 'Cyclic BOM detected. Review the selected component versions.')
        if item_id in children:
            return
        require(len(children) < 200, 'Plan up to 200 distinct items at a time.')
        get(s, 'items', item_id)
        candidates = [b for b in s['boms'] if b['output'] == item_id and b['status'] == 'Active']
        choice = root['id'] if item_id == root['output'] else choices.get(item_id)
        if choice:
            bom = get(s, 'boms', choice)
            require(bom in candidates, 'Selected BOM must be active and produce the selected item.')
        else:
            require(len(candidates) <= 1, 'Multiple active BOM versions for ' + item_id + '. Select a version explicitly.')
            bom = candidates[0] if candidates else None
        children[item_id] = bom['lines'] if bom else []
        if bom:
            selected[item_id] = bom
        visiting.add(item_id)
        for line in children[item_id]:
            visit(line['item'], depth + 1)
        visiting.remove(item_id)
        finished.append(item_id)

    visit(root['output'])
    gross = {root['output']: dec(qty)}
    rows, production, purchases = [], [], []
    for item_id in reversed(finished):
        item = get(s, 'items', item_id)
        ensure_positions(s, item)
        required = gross.get(item_id, dec(0))
        if not required:
            continue
        positions = [p for p in s['stockPositions'] if p['item'] == item_id and p['warehouse'] == warehouse
            and p['status'] == 'Available' and (not p['expiry'] or p['expiry'] >= today())
            and (not p['bin'] or get(s, 'bins', p['bin']).get('active', True))]
        reserved = sum((held(s, p['id']) for p in positions), dec(0))
        available = sum((max(dec(0), dec(p['qty']) - held(s, p['id'])) for p in positions), dec(0))
        # Root quantity is an explicit instruction to produce, not a stock target.
        used = dec(0) if item_id == root['output'] else min(required, available)
        shortage = required - used
        row = dict(item=item_id, grossQty=float(required), availableQty=float(available), reservedQty=float(reserved),
                   stockUsed=float(used), shortageQty=float(shortage), bom=selected.get(item_id, {}).get('id'))
        rows.append(row)
        if not shortage:
            continue
        if item_id in selected:
            bom = selected[item_id]
            require(item.get('tracking') != 'serial' or shortage == 1,
                    'Serial-tracked output requires a one-unit production order. Split this plan.')
            production.append(dict(item=item_id, bom=bom['id'], qty=quantity(shortage)))
            for line in bom['lines']:
                scaled = dec(line['qty']) * shortage / dec(bom['outputQty'])
                require(scaled <= dec('1000000000'), 'Component requirement exceeds the supported quantity. Split the plan.')
                need = scaled.quantize(dec('.000001'), rounding=ROUND_CEILING)
                quantity(need)
                gross[line['item']] = gross.get(line['item'], dec(0)) + need
                quantity(gross[line['item']])
        else:
            pack = dec(item['packSize'])
            buy = (max(shortage, dec(item['minOrder'])) / pack).to_integral_value(rounding=ROUND_CEILING) * pack
            pending = any(any(l['item'] == item_id for l in r['lines'])
                for r in s['requisitions'] + s['orders']
                if r['status'] in {'Pending', 'Approved', 'Draft', 'Pending approval', 'Issued', 'Acknowledged', 'Part received'})
            rate = suggest(s, item['supplier'], item_id)
            purchases.append(dict(item=item_id, qty=quantity(buy), shortageQty=float(shortage), supplier=item['supplier'],
                price=rate['price'], discount=rate.get('discount', 0), taxRate=rate.get('taxRate', item['taxRate']),
                blockedReason='Existing purchasing document requires review' if pending else ''))
    # Children first makes execution dependencies explicit; all jobs remain drafts.
    production.reverse()
    require(not create_requests or len(purchases) <= 100, 'Split plans requiring more than 100 purchase items.')
    result = dict(reference=reference, warehouse=warehouse, date=planning_date, rootItem=root['output'], rows=rows,
        production=production, purchases=purchases, createPurchaseRequests=create_requests,
        basis='Current unreserved usable stock in the selected warehouse. Future receipts and unfinished production are excluded.')
    result['previewHash'] = hashlib.sha256(json.dumps(result, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return result


def create_plan(s, data, actor):
    require(actor['role'] in {'admin', 'production'}, 'Manufacturing planning requires production access.')
    preview = plan(s, data)
    require(data.get('previewHash') == preview['previewHash'], 'The plan changed. Preview and review it again.')
    if preview['createPurchaseRequests']:
        require(not any(p['blockedReason'] for p in preview['purchases']),
                'Review existing purchasing documents or create production drafts without new purchase requests.')
    from .manufacturing import production_action
    orders = {}
    for planned in preview['production']:
        record = production_action(s, 'productionOrder', dict(bom=planned['bom'], qty=planned['qty'],
            warehouse=preview['warehouse'], date=preview['date'], note='Material plan ' + preview['reference']), actor)
        record.update(planningReference=preview['reference'], planningDependencies=[orders[l['item']]['id']
            for l in record['lines'] if l['item'] in orders])
        orders[planned['item']] = record
    root = orders[preview['rootItem']]
    root['planningEvidence'] = preview
    root['plannedOrders'] = [r['id'] for r in orders.values()]
    root['purchaseRequests'] = []
    if preview['createPurchaseRequests'] and preview['purchases']:
        # Explicit production authority permits requests for review, never purchase approval.
        from .domain import identifier, voucher_date, lines
        request = dict(id=identifier(s, 'PR'), date=voucher_date(s), status='Pending', department='Production',
            note='Material plan ' + preview['reference'], createdBy=actor['id'], planningReference=preview['reference'],
            warehouse=preview['warehouse'], lines=lines(s, [{k: p[k] for k in ('item', 'qty', 'price', 'discount', 'taxRate')}
                for p in preview['purchases']]))
        s['requisitions'].insert(0, request)
        root['purchaseRequests'].append(request['id'])
    return root
