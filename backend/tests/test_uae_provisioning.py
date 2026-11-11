import pytest
from lubriflow.company_defaults import new_uae_company
from lubriflow.domain import RuleError


@pytest.mark.parametrize('industry', ['trading', 'services'])
def test_new_uae_company_has_independent_aed_books_and_manual_policies(industry):
    first = new_uae_company('First', industry)
    second = new_uae_company('Second')
    settings = first['settings']
    assert (settings['country'], settings['currency'], settings['timezone']) == ('AE', 'AED', 'Asia/Dubai')
    assert settings['mode'] == 'manual' and settings['separation']
    assert not any(settings[key] for key in ['autoPO', 'autoApprove', 'autoMatch', 'autoReorder'])
    assert settings['taxRegistrationStatus'] == 'pending' and not settings['onboardingCompleted']
    assert settings['modules']['sales'] and not settings['modules']['manufacturing']
    first['journal'].append({'id': 'test'})
    first['settings']['modules']['sales'] = False
    assert not second['journal'] and second['settings']['modules']['sales']


def test_invalid_provisioning_has_no_silent_industry_fallback():
    with pytest.raises(RuleError): new_uae_company('Test', 'process-manufacturing')
    with pytest.raises(RuleError): new_uae_company('  ')
