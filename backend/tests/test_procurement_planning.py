from copy import deepcopy
from datetime import date, timedelta
import pytest
from test_domain import ADMIN, BUYER, order, issue, receipt
from lubriflow.domain import act, today, get, qualified, procurement_insights, automation_plan, RuleError

pytest_plugins = ['test_domain']


def test_qualification_expiry_blocks_commitments_but_preserves_receiving(s, monkeypatch):
    supplier = s['suppliers'][0]['id']
    day = today()
    act(s, 'approveSupplier', dict(id=supplier, approved=True, qualificationUntil=day), ADMIN)
    po = order(s)
    issue(s, po)
    next_day = (date.fromisoformat(day) + timedelta(days=1)).isoformat()
    monkeypatch.setattr('lubriflow.domain.today', lambda: next_day)
    assert not qualified(get(s, 'suppliers', supplier))
    new_po = order(s)
    with pytest.raises(RuleError, match='qualified'):
        act(s, 'submit', dict(id=new_po), ADMIN)
    receipt(s, po)
    with pytest.raises(RuleError, match='past'):
        act(s, 'approveSupplier', dict(id=supplier, approved=True, qualificationUntil=day), ADMIN)
    act(s, 'approveSupplier', dict(id=supplier, approved=True, qualificationUntil=next_day, reason='Renewed'), ADMIN)
    assert qualified(get(s, 'suppliers', supplier))
    act(s, 'submit', dict(id=new_po), ADMIN)
    assert len(get(s, 'suppliers', supplier)['qualificationHistory']) == 3


def test_only_admin_changes_qualification(s):
    with pytest.raises(RuleError, match='role'):
        act(s, 'approveSupplier', dict(id=s['suppliers'][0]['id'], approved=True), BUYER)


def test_expired_supplier_cannot_dispatch_or_queue_message(s):
    supplier = s['suppliers'][0]['id']
    po = order(s)
    act(s, 'submit', dict(id=po), ADMIN)
    act(s, 'approve', dict(id=po), ADMIN)
    vendor = get(s, 'suppliers', supplier)
    vendor['qualificationUntil'] = '2000-01-01'
    with pytest.raises(RuleError, match='qualification'):
        act(s, 'dispatch', dict(id=po), ADMIN)
    with pytest.raises(RuleError, match='qualification'):
        act(s, 'queueSupplierMessage', dict(source=po, purpose='po', channel='email'), ADMIN)
    assert get(s, 'orders', po)['status'] == 'Approved'


def test_forecast_does_not_buy_from_expired_supplier(s):
    item = consume(s)
    get(s, 'suppliers', s['items'][0]['supplier'])['qualificationUntil'] = '2000-01-01'
    recommendation = procurement_insights(s)['forecastPurchaseRecommendations'][0]
    assert 'qualification' in recommendation['blockedReason']
    act(s, 'settings', dict(mode='automatic', autoReorder=True, reorderMethod='forecast'), ADMIN)
    assert automation_plan(s) == []
    with pytest.raises(RuleError, match='No unblocked'):
        act(s, 'forecastRequisition', dict(item=item), BUYER)


def test_quote_currency_and_terms_survive_award(s):
    quote = act(s, 'quote', dict(supplier=s['suppliers'][0]['id'], valid=today(), currency='EUR', rate=2,
        freight=7, tax=0, paymentDays=45, leadDays=3,
        lines=[dict(item=s['items'][0]['id'], qty=10, price=4)]), ADMIN)
    report = procurement_insights(s)
    assert report['basketComparisons'][0]['offers'][0]['baseTotal'] == 94
    act(s, 'award', dict(id=quote['id']), BUYER)
    po = s['orders'][0]
    assert po['currency'] == 'EUR' and po['rate'] == '2'
    assert po['freight'] == 7 and po['tax'] == 0 and po['paymentDays'] == 45
    assert po['status'] == 'Draft'
    assert po['due'] == (date.fromisoformat(today()) + timedelta(days=3)).isoformat()


def test_only_identical_quote_baskets_are_ranked(s):
    supplier = s['suppliers'][0]['id']
    for qty, price in [(10, 4), (10, 3), (20, 2)]:
        act(s, 'quote', dict(supplier=supplier, valid=today(), tax=0,
            lines=[dict(item=s['items'][0]['id'], qty=qty, price=price)]), ADMIN)
    report = procurement_insights(s)
    assert sorted(len(b['offers']) for b in report['basketComparisons']) == [1, 2]
    basket = next(b for b in report['basketComparisons'] if len(b['offers']) == 2)
    assert [o['baseTotal'] for o in basket['offers']] == [30, 40]


def test_scorecards_resolve_supplier_via_order(s):
    po = order(s)
    issue(s, po)
    receipt(s, po)
    before = deepcopy(s)
    row = procurement_insights(s)['supplierScorecards'][0]
    assert row['receipts'] == 1 and row['acceptanceRate'] == 100 and row['onTimeRate'] == 100
    assert s == before


def consume(s):
    item = s['items'][0]['id']
    act(s, 'stockIssue', dict(item=item, qty=99, reason='Operational consumption', date=today()), ADMIN)
    return item


def test_forecast_request_revalidates_and_cannot_duplicate(s):
    item = consume(s)
    s['items'][0]['packSize'] = 12
    before = deepcopy(s)
    recommendation = procurement_insights(s)['forecastPurchaseRecommendations'][0]
    assert s == before
    assert recommendation['suggestedQty'] == 108
    act(s, 'forecastRequisition', dict(item=item, qty=99999), BUYER)
    request = s['requisitions'][0]
    assert request['status'] == 'Pending' and request['lines'][0]['qty'] == 108
    assert request['planningEvidence']['observedDemand'] == 99
    with pytest.raises(RuleError, match='No unblocked'):
        act(s, 'forecastRequisition', dict(item=item), BUYER)


def test_transfers_and_unknown_legacy_outflows_are_not_demand(s):
    item = s['items'][0]['id']
    wh = act(s, 'master', dict(collection='warehouses', name='Second', active=True), ADMIN)['id']
    act(s, 'stockTransfer', dict(item=item, qty=99, fromWarehouse='WH-MAIN', toWarehouse=wh, reason='Transfer'), ADMIN)
    s['stockMoves'].append(dict(id='OLD', item=item, qty=-1000, type='Unknown', date=today()))
    assert procurement_insights(s)['forecastPurchaseRecommendations'] == []


def test_forecast_uses_transaction_date_and_excludes_future(s):
    item = s['items'][0]['id']
    consume(s)
    movement = s['stockMoves'][0]
    movement['date'] = '2000-01-01'
    assert procurement_insights(s)['forecastPurchaseRecommendations'] == []
    movement['date'] = '2099-01-01'
    assert procurement_insights(s)['forecastPurchaseRecommendations'] == []
    assert item


def test_forecast_automation_is_opt_in_and_preserves_approval(s):
    consume(s)
    act(s, 'settings', dict(mode='automatic', autoReorder=True, reorderMethod='forecast'), ADMIN)
    plan = automation_plan(s)
    assert len(plan) == 1 and plan[0][0] == 'forecastRequisition'
    act(s, *plan[0], dict(id='automation', role='system'))
    assert s['requisitions'][0]['status'] == 'Pending'
    assert automation_plan(s) == []


def test_current_supply_suppresses_replenishment(s):
    consume(s)
    po = order(s, qty=50)
    issue(s, po)
    assert procurement_insights(s)['forecastPurchaseRecommendations'] == []
