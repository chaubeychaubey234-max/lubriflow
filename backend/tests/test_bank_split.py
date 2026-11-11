from copy import deepcopy
import pytest
from test_domain import ADMIN
from test_bank_group_reconciliation import receipts
from lubriflow.domain import act, get, RuleError, today

pytest_plugins = ['test_domain']


def prepare(s):
    payment = receipts(s, [50])[0]
    rows = [act(s, 'bankStatement', dict(reference=f'SPLIT-{i}', amount=value, direction='debit'), ADMIN)
            for i, value in enumerate([30, 20])]
    return dict(collection='customerPayments', transaction=payment['id'], statements=[r['id'] for r in rows])


def test_split_reconcile_unmatch_from_second_entry_and_rematch(s):
    data = prepare(s)
    act(s, 'reconcileBankSplit', data, ADMIN)
    assert all(get(s, 'bankStatements', key)['status'] == 'Reconciled' for key in data['statements'])
    with pytest.raises(RuleError):
        act(s, 'reconcileBankSplit', data, ADMIN)
    act(s, 'unmatchBank', dict(statement=data['statements'][1], reason='Correct the match'), ADMIN)
    assert all(get(s, 'bankStatements', key)['status'] == 'Unreconciled' for key in data['statements'])
    assert all(get(s, 'bankStatements', key)['matchHistory'][0]['splitStatements'] == data['statements'] for key in data['statements'])
    assert not get(s, 'customerPayments', data['transaction']).get('reconciledStatement')
    act(s, 'reconcileBankSplit', data, ADMIN)


@pytest.mark.parametrize('fault', ['duplicate', 'amount', 'direction', 'bank', 'locked', 'reversed'])
def test_split_invalid_match_is_atomic(s, fault):
    data = prepare(s)
    row = get(s, 'bankStatements', data['statements'][1])
    if fault == 'duplicate': data['statements'][1] = data['statements'][0]
    if fault == 'amount': row['amount'] = 21
    if fault == 'direction': row['direction'] = 'credit'
    if fault == 'bank': row['bankLedger'] = 'LED-CASH'
    if fault == 'locked': s['settings']['lockedThrough'] = today()
    if fault == 'reversed': get(s, 'customerPayments', data['transaction'])['status'] = 'Reversed'
    before = deepcopy(s)
    with pytest.raises(RuleError): act(s, 'reconcileBankSplit', data, ADMIN)
    assert s == before
