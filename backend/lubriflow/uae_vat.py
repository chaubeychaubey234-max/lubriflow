"""Read-only UAE domestic VAT calculation preview; not a return or eligibility decision."""
import re
from decimal import Decimal, ROUND_HALF_UP
from .domain import require, dec, valid_date

STANDARD_RATE_SOURCE = 'https://tax.gov.ae/en/faq.aspx?keyword=Does+VAT+apply+to+all+goods+and+services'
RULE = dict(id='AE-DOMESTIC-VAT-2018', effectiveFrom='2018-01-01', standardRate='5',
            source=STANDARD_RATE_SOURCE, reviewedOn='2026-11-11')


def calculate(data):
    day = valid_date(data.get('taxDate'))
    require(day >= RULE['effectiveFrom'], 'No supported UAE VAT rules for this date.')
    require(data.get('side') in {'purchase', 'sale'}, 'Choose purchase or sale.')
    trn = data.get('trn')
    require(isinstance(trn, str) and re.fullmatch(r'[0-9]{15}', trn), 'TRN must contain exactly 15 digits.')
    lines = data.get('lines')
    require(isinstance(lines, list) and 1 <= len(lines) <= 100, 'Provide 1–100 lines.')
    output = []
    totals = {key: Decimal(0) for key in ('net', 'vat', 'gross', 'recoverableInputVat', 'nonrecoverableInputVat')}
    for line in lines:
        require(isinstance(line, dict), 'Each line must be an object.')
        treatment = line.get('treatment')
        require(treatment in {'standard', 'zero', 'exempt'}, 'Unsupported treatment; review imports/reverse charge separately.')
        net = dec(line.get('netAED'))
        require(0 <= net <= Decimal('10000000000') and net == net.quantize(Decimal('.01')),
                'Net AED must be nonnegative with at most two decimal places.')
        rate = Decimal(RULE['standardRate']) if treatment == 'standard' else Decimal(0)
        vat = (net * rate / 100).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)
        recoverable = Decimal(0)
        if data['side'] == 'purchase':
            require('recoveryPercent' in line, 'Specify reviewed input-tax recovery percentage.')
            percentage = dec(line['recoveryPercent'])
            require(0 <= percentage <= 100, 'Recovery percentage must be 0–100.')
            recoverable = (vat * percentage / 100).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)
        values = dict(net=net, vat=vat, gross=net+vat, recoverableInputVat=recoverable,
                      nonrecoverableInputVat=vat-recoverable if data['side'] == 'purchase' else Decimal(0))
        for key, value in values.items(): totals[key] += value
        output.append(dict(treatment=treatment, rate=str(rate), **{key: format(value, '.2f') for key, value in values.items()}))
    return dict(rule=RULE.copy(), taxDate=day, side=data['side'], currency='AED', lines=output,
                totals={key: format(value, '.2f') for key, value in totals.items()},
                trnFormatValid=True, trnVerified=False, status='Preview',
                limitations=['Domestic tax-exclusive AED amounts only', 'Treatment and recovery eligibility require review',
                             'TRN format check is not FTA verification', 'No posting, return preparation or filing'])
