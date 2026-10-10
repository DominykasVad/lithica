from unittest.mock import patch

import pytest

from lithica import api
from lithica.func import user_tokens, users


@pytest.fixture(autouse=True)
def inject_config(config_injector):
    config_injector({"privileges": {"user_tokens:create:self": "regular"}})


def test_creating_user_token(
    user_token_factory, context_factory, fake_datetime
):
    user_token = user_token_factory()
    with patch("lithica.func.user_tokens.create_user_token"), patch(
        "lithica.func.user_tokens.serialize_user_token"
    ), patch("lithica.func.users.get_user_by_name"), fake_datetime(
        "1969-02-12"
    ):
        users.get_user_by_name.return_value = user_token.user
        user_tokens.serialize_user_token.return_value = "serialized user token"
        user_tokens.create_user_token.return_value = user_token
        result = api.user_token_api.create_user_token(
            context_factory(user=user_token.user),
            {"user_name": user_token.user.name},
        )
        assert result == "serialized user token"
        user_tokens.create_user_token.assert_called_once_with(
            user_token.user, True
        )
