from copy import deepcopy
import pytest
from test_domain import ADMIN, order, issue, receipt
from lubriflow.domain import empty, act, get, today, RuleError
from lubriflow.finance import account_balances, reports
from lubriflow.inventory import ensure_positions


def setup():
    s = empty('WIP allocation test')
    s['settings']['separation'] = False
    act(s,'settings',dict(modules={'manufacturing':True}),ADMIN)
    act(s,'enablePerpetual',dict(date=today()),ADMIN)
    supplier = act(s,'supplier',dict(name='Parts supplier'),ADMIN)['id']
    act(s,'approveSupplier',dict(id=supplier,approved=True),ADMIN)
    part = act(s,'item',dict(name='Part',supplier=supplier,unit='pcs',price=5),ADMIN)['id']
    output = act(s,'item',dict(name='Assembly',supplier=supplier,unit='pcs'),ADMIN)['id']
    po = order(s,qty=20)
    issue(s,po)
    receipt(s,po,qty=20)
    bom = act(s,'bom',dict(name='BOM',output=output,lines=[dict(item=part,qty=2)]),ADMIN)['id']
    job = act(s,'productionOrder',dict(bom=bom,qty=10),ADMIN)['id']
    act(s,'releaseProduction',dict(id=job),ADMIN)
    return s,part,output,job


def test_advance_consumption_leaves_remaining_cost_in_wip():
    s,part,output,job = setup()
    act(s,'consumeProduction',dict(id=job,lines=[dict(item=part,qty=20)]),ADMIN)
    assert account_balances(s,today())['Work in progress'] == 100
    first = act(s,'finishProduction',dict(id=job,outputQty=3,partial=True,conversionCost=2),ADMIN)
    assert first['outputs'][0]['materialCost'] == 30
    assert first['outputs'][0]['materialAllocations'][0]['qty'] == 6
    assert first['allocatedMaterialCost'] == 30
    assert account_balances(s,today())['Work in progress'] == 70
    act(s,'finishProduction',dict(id=job,outputQty=4,partial=True),ADMIN)
    assert account_balances(s,today())['Work in progress'] == 30
    final = act(s,'finishProduction',dict(id=job,outputQty=3,conversionCost=1),ADMIN)
    assert final['totalCost'] == 103 and final['allocatedMaterialCost'] == 100
    assert get(s,'items',output)['stock'] == 10
    assert account_balances(s,today())['Work in progress'] == 0
    assert account_balances(s,today())['Production conversion clearing'] == -3
    assert reports(s,'2000-01-01',today())['balanceDifference'] == 0


def test_previous_partial_outputs_without_allocations_can_continue():
    s,part,_,job = setup()
    act(s,'consumeProduction',dict(id=job,lines=[dict(item=part,qty=6)]),ADMIN)
    act(s,'finishProduction',dict(id=job,outputQty=3,partial=True),ADMIN)
    get(s,'productionOrders',job)['outputs'][0].pop('materialAllocations')
    act(s,'consumeProduction',dict(id=job,lines=[dict(item=part,qty=14)]),ADMIN)
    result = act(s,'finishProduction',dict(id=job,outputQty=7),ADMIN)
    assert result['outputs'][0]['materialAllocations'][0]['cost'] == 30
    assert result['outputs'][1]['materialCost'] == 70
    assert result['allocatedMaterialCost'] == 100


def test_final_yield_loss_allocates_remaining_cost_and_requires_reason():
    s,part,_,job = setup()
    act(s,'consumeProduction',dict(id=job,lines=[dict(item=part,qty=20)]),ADMIN)
    act(s,'finishProduction',dict(id=job,outputQty=3,partial=True),ADMIN)
    before = deepcopy(s)
    with pytest.raises(RuleError,match='yield-loss'):
        act(s,'finishProduction',dict(id=job,outputQty=5),ADMIN)
    assert s == before
    result = act(s,'finishProduction',dict(id=job,outputQty=5,reason='Documented process loss'),ADMIN)
    assert result['outputQty'] == 8 and result['outputs'][-1]['materialCost'] == 70
    assert account_balances(s,today())['Work in progress'] == 0


def test_cost_rounding_preserves_every_cent():
    s = empty('Cent allocation')
    s['settings']['modules']['manufacturing'] = True
    supplier = act(s,'supplier',dict(name='Supplier'),ADMIN)['id']
    part = act(s,'item',dict(name='Raw',supplier=supplier,unit='pcs',stock=3),ADMIN)['id']
    output = act(s,'item',dict(name='Output',supplier=supplier,unit='pcs'),ADMIN)['id']
    ensure_positions(s,get(s,'items',part))
    position = next(p for p in s['stockPositions'] if p['item'] == part)
    act(s,'confirmOpeningCost',dict(position=position['id'],value=10,reason='Approved opening value'),ADMIN)
    bom = act(s,'bom',dict(name='BOM',output=output,lines=[dict(item=part,qty=1)]),ADMIN)['id']
    job = act(s,'productionOrder',dict(bom=bom,qty=3),ADMIN)['id']
    act(s,'releaseProduction',dict(id=job),ADMIN)
    act(s,'consumeProduction',dict(id=job,lines=[dict(item=part,qty=3)]),ADMIN)
    for partial in [True,True,False]:
        act(s,'finishProduction',dict(id=job,outputQty=1,partial=partial),ADMIN)
    result = get(s,'productionOrders',job)
    assert [o['materialCost'] for o in result['outputs']] == [3.33,3.34,3.33]
    assert result['totalCost'] == 10


def test_transfer_and_issue_accounting_ignore_free_text_reason():
    s,part,_,_ = setup()
    destination = act(s,'master',dict(collection='warehouses',name='Other warehouse'),ADMIN)['id']
    before = account_balances(s,today())
    act(s,'stockTransfer',dict(item=part,qty=5,fromWarehouse='WH-MAIN',toWarehouse=destination,
        reason='Move goods for shelf space'),ADMIN)
    assert account_balances(s,today()) == before
    act(s,'stockIssue',dict(item=part,qty=2,reason='Transfer to expense'),ADMIN)
    after = account_balances(s,today())
    assert after['Inventory asset'] == before['Inventory asset'] - 10
    assert after['Inventory adjustments'] == before.get('Inventory adjustments',0) + 10
