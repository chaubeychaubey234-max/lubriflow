from copy import deepcopy
import pytest
from lubriflow.domain import act, empty, RuleError

ADMIN = {'id': 'admin', 'role': 'admin'}
FINANCE = {'id': 'finance', 'role': 'finance'}


def test_sensitive_change_requires_an_independent_approval_and_applies_once():
    state = empty('Company')
    request = act(state, 'requestSettingsChange', {'changes': {'defaultTax': 5, 'taxRegime': 'UAE VAT'},
                                                    'reason': 'UAE registration reviewed'}, ADMIN)
    assert state['settings']['defaultTax'] == 0
    with pytest.raises(RuleError, match='different'):
        act(state, 'approveSettingsChange', {'id': request['id'], 'reason': 'self'}, ADMIN)
    approved = act(state, 'approveSettingsChange', {'id': request['id'], 'reason': 'independent review'}, FINANCE)
    assert approved['status'] == 'Approved'
    assert state['settings']['defaultTax'] == 5
    with pytest.raises(RuleError, match='no longer pending'):
        act(state, 'approveSettingsChange', {'id': request['id'], 'reason': 'again'}, ADMIN)


@pytest.mark.parametrize('changes', [
    {'modules': {'sales': False}}, {'currency': 'AED'}, {'defaultTax': 101}, {'unknown': 'x'},
])
def test_invalid_sensitive_request_is_atomic(changes):
    state = empty()
    if changes == {'currency': 'AED'}:
        state['journal'].append({'id': 'J-1'})
    before = deepcopy(state)
    with pytest.raises(RuleError):
        act(state, 'requestSettingsChange', {'changes': changes, 'reason': 'Review'}, ADMIN)
    assert state == before
