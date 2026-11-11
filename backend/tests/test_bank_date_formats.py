import pytest
from lubriflow.bank_import import parse, DEFAULT_MAPPING, import_statement
from lubriflow.domain import act, empty, RuleError

ADMIN = {'id': 'admin', 'role': 'admin'}


@pytest.mark.parametrize('format,expected', [('DD/MM/YYYY', '2026-04-03'), ('MM/DD/YYYY', '2026-03-04')])
def test_ambiguous_dates_follow_explicit_mapping(format, expected):
    rows, _ = parse({'csv': 'date\treference\tmoney_in\tmoney_out\n03/04/2026\tTEST\t10\t0'},
                    {**DEFAULT_MAPPING, 'delimiter': '\t', 'dateFormat': format})
    assert rows[0]['date'] == expected


@pytest.mark.parametrize('value', ['31/02/2026', '3/04/2026', '2026-04-03'])
def test_invalid_or_mixed_format_is_rejected(value):
    with pytest.raises(RuleError):
        parse({'csv': f'date,reference,money_in,money_out\n{value},TEST,10,0'},
              {**DEFAULT_MAPPING, 'dateFormat': 'DD/MM/YYYY'})


def test_date_format_changes_require_new_preview():
    s = empty()
    profile = act(s, 'bankImportMapping', dict(name='Dates', dateFormat='DD/MM/YYYY'), ADMIN)
    data = dict(csv='date,reference,money_in,money_out\n03/04/2026,TEST,10,0',
                bankLedger='LED-BANK', statementCurrency='USD', mappingId=profile['id'])
    data['previewHash'] = import_statement(s, data, ADMIN, preview=True)['previewHash']
    act(s, 'bankImportMapping', dict(id=profile['id'], name='Dates', dateFormat='MM/DD/YYYY'), ADMIN)
    with pytest.raises(RuleError, match='Preview'):
        act(s, 'bankStatementImport', data, ADMIN)
    assert not s['bankStatements']
    data['previewHash'] = import_statement(s, data, ADMIN, preview=True)['previewHash']
    act(s, 'bankStatementImport', data, ADMIN)
    assert s['bankStatements'][0]['date'] == '2026-03-04'
