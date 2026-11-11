from copy import deepcopy
import pytest
from lubriflow.domain import act, empty, RuleError

ADMIN = {'id': 'admin', 'role': 'admin'}
CONFIG = dict(company='General company', country='AE', currency='AED', timezone='Asia/Dubai',
              fiscalYearStart='01-01', taxRegime='Pending review', legalEntityType='company',
              industryTemplate='manufacturing', taxRegistrationStatus='pending')


def test_setup_enables_modules_preserves_policies_and_records_actor():
    s = empty()
    act(s, 'configureCompany', CONFIG, ADMIN)
    assert s['settings']['modules']['manufacturing']
    assert s['settings']['modules']['sales']
    assert s['settings']['mode'] == 'manual'
    assert s['settings']['onboardingReviewedBy'] == 'admin'
    assert s['audit'][0]['action'] == 'configureCompany'


@pytest.mark.parametrize('changes', [{'country': 'Dubai'}, {'timezone': 'bad'}, {'industryTemplate': 'unknown'},
                                   {'legalEntityType': 'unknown'}, {'taxRegistrationStatus': ''}])
def test_invalid_setup_rolls_back(changes):
    s = empty()
    before = deepcopy(s)
    with pytest.raises(RuleError):
        act(s, 'configureCompany', {**CONFIG, **changes}, ADMIN)
    assert s == before


def test_setup_cannot_bypass_currency_lock_or_role_access():
    s = empty()
    s['invoices'].append({'id': 'existing'})
    with pytest.raises(RuleError, match='currency'):
        act(s, 'configureCompany', CONFIG, ADMIN)
    with pytest.raises(RuleError):
        act(empty(), 'configureCompany', CONFIG, {'id': 'finance', 'role': 'finance'})
