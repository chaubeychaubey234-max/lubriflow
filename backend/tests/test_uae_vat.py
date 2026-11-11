from copy import deepcopy
import pytest
from lubriflow.domain import RuleError
from lubriflow.uae_vat import calculate

DATA = dict(taxDate='2026-11-01', side='purchase', trn='100000000000001',
            lines=[dict(netAED='100.00', treatment='standard', recoveryPercent='50'),
                   dict(netAED='200', treatment='zero', recoveryPercent='0'),
                   dict(netAED='300', treatment='exempt', recoveryPercent='0')])


def test_preview_is_read_only_and_preserves_distinct_zero_and_exempt_treatments():
    before = deepcopy(DATA)
    result = calculate(DATA)
    assert DATA == before
    assert result['totals'] == dict(net='600.00', vat='5.00', gross='605.00', recoverableInputVat='2.50', nonrecoverableInputVat='2.50')
    assert [line['treatment'] for line in result['lines']] == ['standard', 'zero', 'exempt']
    assert not result['trnVerified']


@pytest.mark.parametrize('changes', [dict(taxDate='2017-12-31'), dict(trn='abc'),
                                   dict(lines=[dict(netAED='100', treatment='standard')]),
                                   dict(lines=[dict(netAED='100', treatment='standard', recoveryPercent=101)]),
                                   dict(lines=[dict(netAED='1.001', treatment='standard', recoveryPercent=100)]),
                                   dict(lines=[dict(netAED='100', treatment='reverse-charge', recoveryPercent=100)])])
def test_unsupported_or_unreviewed_values_are_rejected(changes):
    with pytest.raises(RuleError): calculate({**DATA, **changes})


def test_sales_preview_and_half_fils_rounding():
    result = calculate({**DATA, 'side': 'sale', 'lines': [dict(netAED='.10', treatment='standard')]})
    assert result['totals']['vat'] == '0.01'
    assert result['totals']['recoverableInputVat'] == '0.00'
