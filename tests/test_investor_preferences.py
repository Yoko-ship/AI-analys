import pytest
from pydantic import ValidationError
from server.accounts.routes import ProfilePreferencesRequest
from identity.settings import DEFAULT_PROFILE_PREFERENCES


def test_interests_and_screeners_are_validated_account_preferences():
    saved = {'id': 'bank-growth', 'name': 'Banks', 'filters': {'sector': 'banks', 'direction': 'gain'}}
    values = ProfilePreferencesRequest(investment_interests=['banks', 'dividends'], saved_screeners=[saved]).model_dump(exclude_none=True)
    assert values['investment_interests'] == ['banks', 'dividends']
    assert values['saved_screeners'][0]['filters']['direction'] == 'gain'
    assert DEFAULT_PROFILE_PREFERENCES['saved_screeners'] == []
    assert DEFAULT_PROFILE_PREFERENCES['investment_interests'] == []


@pytest.mark.parametrize('values', [
    {'investment_interests': ['imaginary']}, {'investment_interests': ['banks'] * 12},
    {'saved_screeners': [{'id':'x', 'name':'', 'filters':{}}]},
    {'saved_screeners': [{'id':'x', 'name':'x', 'filters':{'direction':'invented'}}]},
    {'saved_screeners': [{'id':str(i), 'name':'x', 'filters':{}} for i in range(31)]},
])
def test_investor_preferences_reject_invalid_values(values):
    with pytest.raises(ValidationError):
        ProfilePreferencesRequest(**values)
