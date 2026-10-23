import pytest
from pydantic import ValidationError
from server.accounts.routes import ProfilePreferencesRequest
from identity.settings import DEFAULT_PROFILE_PREFERENCES


def test_terminal_layout_is_a_validated_account_preference():
    panel = {"ticker": "AGBA", "func": "PL", "form": "MSFO", "scope": "consolidated"}
    assert "terminal_layout" in DEFAULT_PROFILE_PREFERENCES
    assert ProfilePreferencesRequest(terminal_layout=[panel]).model_dump(exclude_none=True)["terminal_layout"] == [panel]
    for value in ([panel] * 5, [{**panel, "func": "ADM"}], [{**panel, "ticker": "<script>"}]):
        with pytest.raises(ValidationError):
            ProfilePreferencesRequest(terminal_layout=value)
