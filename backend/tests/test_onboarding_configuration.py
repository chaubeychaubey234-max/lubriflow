from test_domain import ADMIN
from lubriflow.domain import act, empty


def test_company_onboarding_completion_is_configuration_driven():
    state = empty("Configured company")
    assert state["settings"]["onboardingCompleted"] is False
    act(
        state,
        "settings",
        {
            "country": "AE",
            "legalEntityType": "company",
            "industryTemplate": "trading",
            "taxRegistrationStatus": "registered",
            "currency": "AED",
            "taxRegime": "vat",
        },
        ADMIN,
    )
    assert state["settings"]["onboardingCompleted"] is True


def test_onboarding_stays_incomplete_until_required_company_context_exists():
    state = empty("Configured company")
    act(state, "settings", {"country": "AE", "currency": "AED"}, ADMIN)
    assert state["settings"]["onboardingCompleted"] is False
