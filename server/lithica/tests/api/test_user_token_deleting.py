from unittest.mock import patch

import pytest

from lithica import db
from lithica.func import user_tokens, users
from lithica.tests.api.http import ok


@pytest.fixture(autouse=True)
def inject_config(config_injector):
    config_injector({"privileges": {"user_tokens:delete:self": "regular"}})


def test_deleting_user_token(user_token_factory, client, fake_datetime):
    user_token = user_token_factory()
    db.session.add(user_token)
    db.session.commit()
    with (
        patch("lithica.func.user_tokens.get_by_user_and_token"),
        patch("lithica.func.users.get_user_by_name"),
        fake_datetime("1969-02-12"),
    ):
        users.get_user_by_name.return_value = user_token.user
        user_tokens.get_by_user_and_token.return_value = user_token
        result = ok(
            client.delete(
                "/user-token/%s/%s" % (user_token.user.name, user_token.token),
                user=user_token.user,
            )
        )
        assert result == {}
        user_tokens.get_by_user_and_token.assert_called_once_with(
            user_token.user, user_token.token
        )
