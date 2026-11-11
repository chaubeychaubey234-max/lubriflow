from copy import deepcopy
import pytest
from test_domain import ADMIN
from lubriflow.domain import act, get, today, RuleError
from lubriflow.bank_import import suggestions

pytest_plugins = ['test_domain']


def receipts(s, amounts):
    customer = act(s, 'master', dict(collection='customers', name='Grouped receipt customer'), ADMIN)
    item = s['items'][0]['id']
    results = []
    for number, value in enumerate(amounts, 1):
        order = act(s, 'salesOrder', dict(customer=customer['id'], lines=[dict(item=item, qty=1, price=value)]), ADMIN)
        delivery = act(s, 'deliverSale', dict(order=order['id'], lines=order['lines']), ADMIN)
        invoice = act(s, 'salesInvoice', dict(order=order['id'], number=f'GROUP-{number}', lines=delivery['lines']), ADMIN)
        results.append(act(s, 'customerPayment', dict(invoice=invoice['id'], amount=value,
            reference=f'RECEIPT-{number}', date=today()), ADMIN))
    return results


def test_grouped_receipts_reconcile_and_unmatch_atomically(s):
    first, second = receipts(s, [30, 20])
    statement = act(s, 'bankStatement', dict(reference='BANK-GROUP', amount=50, direction='debit'), ADMIN)
    reconciled = act(s, 'reconcileBankGroup', dict(statement=statement['id'], matches=[
        dict(collection='customerPayments', transaction=first['id']),
        dict(collection='customerPayments', transaction=second['id'])]), ADMIN)
    assert reconciled['status'] == 'Reconciled'
    assert [m['amount'] for m in reconciled['matches']] == [30, 20]
    matched = {row['id']: row for row in s['customerPayments']}
    assert matched[first['id']]['reconciledStatement'] == statement['id']
    assert matched[second['id']]['reconciledStatement'] == statement['id']
    assert 'transaction' not in reconciled and 'collection' not in reconciled
    act(s, 'unmatchBank', dict(statement=statement['id'], reason='Wrong grouped match'), ADMIN)
    assert get(s, 'bankStatements', statement['id'])['status'] == 'Unreconciled'
    assert 'reconciledStatement' not in first and 'reconciledStatement' not in second
    history = get(s, 'bankStatements', statement['id'])['matchHistory'][0]
    assert len(history['matches']) == 2 and history['reason'] == 'Wrong grouped match'


@pytest.mark.parametrize('matches,error', [
    ([], '1–100'),
    ([dict(collection='customerPayments', transaction='first')], 'exactly'),
    ([dict(collection='customerPayments', transaction='first'),
      dict(collection='customerPayments', transaction='first')], 'once'),
    ([dict(collection='payments', transaction='first'),
      dict(collection='customerPayments', transaction='second')], 'direction'),
])
def test_invalid_group_rolls_back(s, matches, error):
    first, second = receipts(s, [30, 20])
    for match in matches:
        if match['transaction'] == 'first': match['transaction'] = first['id']
        if match['transaction'] == 'second': match['transaction'] = second['id']
    # Make the supplier-payment collection resolve for the direction test.
    if any(m['collection'] == 'payments' for m in matches):
        s['payments'].append(dict(first, id=first['id'] + '-SUP'))
        matches[0]['transaction'] = first['id'] + '-SUP'
    statement = act(s, 'bankStatement', dict(reference='INVALID-GROUP', amount=50, direction='debit'), ADMIN)
    before = deepcopy(s)
    with pytest.raises(RuleError, match=error):
        act(s, 'reconcileBankGroup', dict(statement=statement['id'], matches=matches), ADMIN)
    assert s == before


def test_group_suggestions_are_read_only_and_bounded(s):
    first, second, third = receipts(s, [30, 20, 10])
    statement = act(s, 'bankStatement', dict(reference='RECEIPT-1', amount=50, direction='debit'), ADMIN)
    before = deepcopy(s)
    result = suggestions(s, statement['id'])
    assert s == before
    assert {c['transaction'] for c in result['candidates']} == {first['id'], second['id'], third['id']}
    assert any([m['transaction'] for m in group] == [first['id'], second['id']]
               for group in result['groupCandidates'])
    assert result['exactCandidates'] == [] and result['automaticMatch'] is False


def test_legacy_single_match_still_unmatches(s):
    payment = receipts(s, [50])[0]
    statement = act(s, 'bankStatement', dict(reference='LEGACY', amount=50, direction='debit'), ADMIN)
    act(s, 'reconcileBank', dict(statement=statement['id'], collection='customerPayments', transaction=payment['id']), ADMIN)
    act(s, 'unmatchBank', dict(statement=statement['id'], reason='Legacy correction'), ADMIN)
    assert statement['status'] == 'Unreconciled'
