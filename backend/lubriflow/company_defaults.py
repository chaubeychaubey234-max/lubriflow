"""Explicit UAE launch defaults used only when provisioning a new company."""
from .domain import empty, require, text


def new_uae_company(company, industry='trading'):
    require(industry in {'trading', 'services'}, 'Choose trading or services for the UAE launch.')
    state = empty(text(company, 'Company', True))
    state['settings'].update(
        country='AE', currency='AED', timezone='Asia/Dubai', industryTemplate=industry,
        taxRegistrationStatus='pending', taxRegime='Pending UAE tax configuration',
        mode='manual', autoPO=False, autoApprove=False, autoMatch=False, autoReorder=False,
        separation=True, onboardingCompleted=False,
        launchProfile='uae-v1', interfaceLanguage='en',
    )
    state['settings']['modules'].update(sales=True, manufacturing=False)
    # Registration and tax treatments require explicit setup; defaults are not a VAT assessment.
    return state
