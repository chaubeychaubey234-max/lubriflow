from copy import deepcopy
import pytest
from test_domain import FINANCE, BUYER
from lubriflow.domain import act, RuleError, today
from lubriflow.bank_import import import_statement, suggestions, parse, fingerprint

pytest_plugins = ['test_domain']


def payload(s):
    day = today()
    return dict(bankLedger='LED-BANK', statementCurrency=s['settings']['currency'], openingBalance='100',
                csv=f'date,reference,money_in,money_out,balance\n{day},IN-1,50,,150\n{day},OUT-1,,20,130\n')


def test_preview_is_readonly_and_import_atomic(s):
    data = payload(s)
    before = deepcopy(s)
    preview = import_statement(s, data, FINANCE, preview=True)
    assert s == before
    assert preview['closingBalance'] == '130'
    data['previewHash'] = preview['previewHash']
    result = act(s, 'bankStatementImport', data, FINANCE)
    assert result['rowCount'] == 2
    assert len(s['bankStatements']) == 2
    assert [r['direction'] for r in result['rows']] == ['debit', 'credit']
    assert s['journal'] == before['journal']
    imported = deepcopy(s)
    with pytest.raises(RuleError, match='reference'):
        act(s, 'bankStatementImport', data, FINANCE)
    assert s == imported


def test_stale_preview_currency_role_and_period(s):
    data = payload(s)
    data['previewHash'] = import_statement(s, data, FINANCE, preview=True)['previewHash']
    data['openingBalance'] = '200'
    with pytest.raises(RuleError, match='Preview'):
        act(s, 'bankStatementImport', data, FINANCE)
    data = payload(s)
    data['statementCurrency'] = 'INVALID'
    with pytest.raises(RuleError, match='currency'):
        import_statement(s, data, FINANCE, preview=True)
    with pytest.raises(RuleError, match='Finance'):
        import_statement(s, payload(s), BUYER, preview=True)
    s['settings']['lockedThrough'] = today()
    with pytest.raises(RuleError, match='locked'):
        import_statement(s, payload(s), FINANCE, preview=True)


@pytest.mark.parametrize('csv', [
    'date,reference,money_in,money_out\n2026-01-01,X,1,1',
    'date,reference,money_in,money_out\n2026-01-01,X,-1,0',
    'date,reference,money_in,money_out\n2026-01-01,X,1.001,0',
    'date,reference,money_in,money_out\n2026-01-01,X,1e999,0',
    'date,reference,money_in,money_out\n2026-01-01,X,NaN,0',
    'date,reference,money_in,money_out\n2026-01-01,X,1,0\n2026-01-01,x,2,0',
    'date,reference,money_in,money_out\n2026-01-02,X,1,0\n2026-01-01,Y,2,0',
    'date,reference,money_in,money_out\n2026-01-01,X,1',
    'date,reference,money_in,money_out\n2026-01-01,X,"1,0',
    '"date,reference,money_in,money_out',
    'date,reference,money_in,money_out,balance\n2026-01-01,X,1,0,999',
])
def test_invalid_csv_rejected(csv):
    with pytest.raises(RuleError):
        parse(dict(csv=csv, openingBalance=0))


def test_late_duplicate_leaves_no_partial_import(s):
    data = payload(s)
    act(s, 'bankStatement', dict(bankLedger='LED-BANK', date=today(), reference='OUT-1', amount=20, direction='credit'), FINANCE)
    before = deepcopy(s)
    with pytest.raises(RuleError, match='reference'):
        import_statement(s, data, FINANCE, preview=True)
    assert s == before


def test_suggestions_are_readonly_and_exclude_wrong_candidates(s):
    statement = act(s, 'bankStatement', dict(bankLedger='LED-BANK', date=today(), reference='PAY-1', amount=20, direction='credit'), FINANCE)
    payment = dict(id='PAY-1', date=today(), reference='PAY-1', amount=20, bankLedger='LED-BANK')
    s['payments'] = [payment, dict(payment, id='PAY-2', reference='Other'),
                     dict(payment, id='reversed', status='Reversed'),
                     dict(payment, id='matched', reconciledStatement='another'),
                     dict(payment, id='different-bank', bankLedger='OTHER'),
                     dict(payment, id='old', date='2000-01-01'),
                     dict(payment, id='different-amount', amount=21)]
    s['customerPayments'] = [dict(payment, id='wrong-direction')]
    before = deepcopy(s)
    result = suggestions(s, statement['id'])
    assert [c['transaction'] for c in result['candidates']] == ['PAY-1', 'PAY-2']
    assert result['ambiguous'] and not result['automaticMatch']
    assert s == before


def test_preview_hash_normalizes_numeric_representations():
    assert fingerprint({'openingBalance': 0}) == fingerprint({'openingBalance': '0.00'})
    assert fingerprint({'openingBalance': 100.0}) == fingerprint({'openingBalance': '100'})
    assert fingerprint({'openingBalance': 0}) != fingerprint({'openingBalance': None})


def test_row_limit_rejects_oversized_batch():
    csv = 'date,reference,money_in,money_out\n' + '\n'.join(f'2026-01-01,R{i},1,0' for i in range(501))
    with pytest.raises(RuleError, match='500'):
        parse(dict(csv=csv))
