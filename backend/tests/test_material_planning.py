from copy import deepcopy
import pytest
from test_domain import ADMIN
from lubriflow.domain import act, get, RuleError
from lubriflow.material_planning import plan
from lubriflow.inventory import ensure_positions

pytest_plugins = ['test_domain']
PRODUCTION = dict(id='planner', role='production')


def fixture(s, raw_stock=5):
    s['settings']['modules']['manufacturing'] = True
    supplier = s['suppliers'][0]['id']
    def item(name, stock=0, pack=1):
        return act(s, 'item', dict(name=name, unit='pcs', supplier=supplier, price=2, stock=stock,
                                  target=100, packSize=pack), ADMIN)['id']
    raw, sub, final = item('Raw', raw_stock, 6), item('Subassembly', 2), item('Final')
    child = act(s, 'bom', dict(name='Sub v1', output=sub, outputQty=1,
        lines=[dict(item=raw, qty=3)]), PRODUCTION)['id']
    root = act(s, 'bom', dict(name='Final v1', output=final, outputQty=1,
        lines=[dict(item=sub, qty=2), dict(item=raw, qty=1)]), PRODUCTION)['id']
    return raw, sub, final, child, dict(bom=root, qty=10, warehouse='WH-MAIN', reference='PLAN-1', createPurchaseRequests=True)


def test_plan_aggregates_shared_inputs_and_nets_stock_once(s):
    raw, sub, final, child, data = fixture(s)
    before = deepcopy(s)
    preview = plan(s, data)
    assert s == before
    by_item = {r['item']:r for r in preview['rows']}
    assert by_item[sub]['grossQty'] == 20 and by_item[sub]['shortageQty'] == 18
    assert by_item[raw]['grossQty'] == 64 and by_item[raw]['shortageQty'] == 59
    assert preview['purchases'][0]['qty'] == 60
    assert [r['item'] for r in preview['production']] == [sub, final]
    root = act(s, 'createMaterialPlan', dict(data, previewHash=preview['previewHash']), PRODUCTION)
    assert len(root['plannedOrders']) == 2
    assert root['planningDependencies'] == [next(o['id'] for o in s['productionOrders'] if o['bom'] == child)]
    assert all(o['status'] == 'Draft' for o in s['productionOrders'])
    assert s['requisitions'][0]['status'] == 'Pending' and s['requisitions'][0]['lines'][0]['qty'] == 60
    assert s['journal'] == before['journal'] and s['stockMoves'] == before['stockMoves']
    with pytest.raises(RuleError, match='already'):
        act(s, 'createMaterialPlan', dict(data, previewHash=preview['previewHash']), PRODUCTION)


def test_stock_change_invalidates_preview_atomically(s):
    raw, _, _, _, data = fixture(s)
    preview = plan(s, data)
    act(s, 'stockIssue', dict(item=raw, qty=1, reason='Use material'), ADMIN)
    before = deepcopy(s)
    with pytest.raises(RuleError, match='plan changed'):
        act(s, 'createMaterialPlan', dict(data, previewHash=preview['previewHash']), PRODUCTION)
    assert s == before


def test_cycles_rejected_even_if_stock_covers_requirement(s):
    raw, _, final, _, data = fixture(s)
    act(s, 'bom', dict(name='Cycle', output=raw, outputQty=1, lines=[dict(item=final,qty=1)]), ADMIN)
    with pytest.raises(RuleError, match='Cyclic'):
        plan(s, data)


def test_ambiguous_bom_requires_explicit_valid_version(s):
    raw, sub, _, child, data = fixture(s)
    act(s, 'bom', dict(name='Sub v2', output=sub, outputQty=1, lines=[dict(item=raw,qty=4)]), ADMIN)
    with pytest.raises(RuleError, match='Multiple'):
        plan(s, data)
    assert plan(s, dict(data,bomSelections={sub:child}))['production'][0]['bom'] == child
    with pytest.raises(RuleError, match='Selected BOM'):
        plan(s, dict(data,bomSelections={sub:data['bom']}))


def test_unusable_stock_and_reservations_are_excluded(s):
    raw, _, _, child, data = fixture(s)
    ensure_positions(s, get(s, 'items', raw))
    position = next(p for p in s['stockPositions'] if p['item'] == raw)
    job = act(s, 'productionOrder', dict(bom=child,qty=1), PRODUCTION)
    act(s, 'releaseProduction', dict(id=job['id']), PRODUCTION)
    act(s, 'reserveStock', dict(position=position['id'], sourceKind='productionOrders', source=job['id'],qty=2), PRODUCTION)
    preview = plan(s, data)
    row = next(r for r in preview['rows'] if r['item'] == raw)
    assert row['availableQty'] == 3 and row['reservedQty'] == 2
    get(s,'stockPositions',position['id'])['status'] = 'Quarantined'
    assert next(r for r in plan(s,data)['rows'] if r['item'] == raw)['availableQty'] == 0


def test_existing_purchase_request_blocks_duplicate_buying_but_drafts_are_optional(s):
    raw, _, _, _, data = fixture(s)
    act(s, 'requisition', dict(lines=[dict(item=raw,qty=5)]), ADMIN)
    preview = plan(s,data)
    before = deepcopy(s)
    with pytest.raises(RuleError, match='existing purchasing'):
        act(s,'createMaterialPlan',dict(data,previewHash=preview['previewHash']),PRODUCTION)
    assert s == before
    data['createPurchaseRequests'] = False
    preview = plan(s,data)
    act(s,'createMaterialPlan',dict(data,previewHash=preview['previewHash']),PRODUCTION)
    assert len(s['requisitions']) == 1


def test_module_role_and_preview_required(s):
    _, _, _, _, data = fixture(s)
    with pytest.raises(RuleError, match='role'):
        act(s,'createMaterialPlan',data,dict(id='buyer',role='buyer'))
    with pytest.raises(RuleError, match='Preview|preview'):
        act(s,'createMaterialPlan',data,PRODUCTION)
    s['settings']['modules']['manufacturing'] = False
    with pytest.raises(RuleError, match='Enable'):
        plan(s,data)


def test_planned_jobs_execute_through_existing_costing_workflow(s):
    raw, sub, final, _, data = fixture(s,raw_stock=100)
    preview = plan(s,data)
    assert not preview['purchases']
    result = act(s,'createMaterialPlan',dict(data,previewHash=preview['previewHash']),PRODUCTION)
    for job_id in result['plannedOrders']:
        job = get(s,'productionOrders',job_id)
        act(s,'releaseProduction',dict(id=job_id),PRODUCTION)
        act(s,'consumeProduction',dict(id=job_id,lines=job['lines']),PRODUCTION)
        act(s,'finishProduction',dict(id=job_id,outputQty=job['qty']),PRODUCTION)
    assert get(s,'items',final)['stock'] == 10
    assert get(s,'items',sub)['stock'] == 0
    assert get(s,'items',raw)['stock'] == 36
    assert all(o['status'] == 'Completed' for o in s['productionOrders'])
