from copy import deepcopy
import pytest
from lubriflow.domain import act, empty, get, RuleError, today

ADMIN = {'id': 'admin', 'role': 'admin'}


@pytest.mark.parametrize('kind,direction', [('charge', 'credit'), ('interest', 'debit'), ('unidentified', 'debit'), ('unidentified', 'credit')])
def test_adjustment_post_unmatch_reverse_replace(kind, direction):
    s = empty()
    statement = act(s, 'bankStatement', dict(reference='BANK', amount=20, direction=direction), ADMIN)
    data = dict(statement=statement['id'], kind=kind, reason='Reviewed statement')
    entry = act(s, 'bankAdjustment', data, ADMIN)
    assert sum(x.get('debit', 0) - x.get('credit', 0) for x in entry['entries']) == 0
    assert get(s, 'bankStatements', statement['id'])['status'] == 'Reconciled'
    with pytest.raises(RuleError): act(s, 'bankAdjustment', data, ADMIN)
    with pytest.raises(RuleError, match='Unmatch'): act(s, 'reverseVoucher', dict(id=entry['id'], reason='Correction'), ADMIN)
    act(s, 'unmatchBank', dict(statement=statement['id'], reason='Correction'), ADMIN)
    with pytest.raises(RuleError, match='Reverse'): act(s, 'bankAdjustment', data, ADMIN)
    with pytest.raises(RuleError, match='Reverse'):
        act(s, 'reconcileBank', dict(statement=statement['id']), ADMIN)
    act(s, 'reverseVoucher', dict(id=entry['id'], reason='Correction'), ADMIN)
    act(s, 'bankAdjustment', data, ADMIN)
    assert len(s['journal']) == 3


@pytest.mark.parametrize('fault', ['direction', 'locked', 'foreign', 'reason', 'role'])
def test_invalid_adjustment_rolls_back(fault):
    s = empty()
    row = act(s, 'bankStatement', dict(reference='BANK', amount=20, direction='credit'), ADMIN)
    data = dict(statement=row['id'], kind='charge', reason='Reviewed')
    actor = ADMIN
    if fault == 'direction': data['kind'] = 'interest'
    if fault == 'locked': s['settings']['lockedThrough'] = today()
    if fault == 'foreign': get(s, 'ledgers', 'LED-BANK')['currency'] = 'EUR'
    if fault == 'reason': data['reason'] = ''
    if fault == 'role': actor = {'id': 'viewer', 'role': 'viewer'}
    before = deepcopy(s)
    with pytest.raises(RuleError): act(s, 'bankAdjustment', data, actor)
    assert s == before
