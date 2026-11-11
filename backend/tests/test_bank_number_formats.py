import pytest
from lubriflow.bank_import import DEFAULT_MAPPING, parse, localized_amount, validate_mapping
from lubriflow.domain import RuleError


@pytest.mark.parametrize('decimal,group,value', [('.', ',', '1,234.56'), (',', '.', '1.234,56'), (',', ' ', '1 234,56'), (',', '', '1234,56')])
def test_localized_values_and_running_balance(decimal, group, value):
    mapping = {**DEFAULT_MAPPING, 'delimiter': ';', 'decimalSeparator': decimal, 'thousandsSeparator': group}
    rows, summary = parse(dict(csv=f'date;reference;money_in;money_out;balance\n2026-01-01;LOCAL;{value};0;{value}', openingBalance=0), mapping)
    assert rows[0]['amount'] == 1234.56
    assert summary['closingBalance'] == '1234.56'


@pytest.mark.parametrize('value', ['12,34.56', '1,234,56', '1.234,56', 'NaN', '1e3', '1234.567'])
def test_malformed_amounts_never_guessed(value):
    with pytest.raises(RuleError):
        localized_amount(value, 'Amount', {**DEFAULT_MAPPING, 'thousandsSeparator': ','})


def test_separators_cannot_collide():
    with pytest.raises(RuleError):
        validate_mapping({**DEFAULT_MAPPING, 'thousandsSeparator': '.'})
