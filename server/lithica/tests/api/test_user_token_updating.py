from unittest.mock import patch

import pytest

from lithica import db
from lithica.func import user_tokens, users
from lithica.tests.api.http import assert_error, ok


@pytest.fixture(autouse=True)
def inject_config(config_injector):
    config_injector({"privileges": {"user_tokens:edit:self": "regular"}})


def test_edit_user_token(user_token_factory, client, fake_datetime):
    user_token = user_token_factory()
    db.session.add(user_token)
    db.session.commit()
    with (
        patch("lithica.func.user_tokens.get_by_user_and_token"),
        patch("lithica.func.user_tokens.update_user_token_enabled"),
        patch("lithica.func.user_tokens.update_user_token_edit_time"),
        patch("lithica.func.user_tokens.serialize_user_token"),
        patch("lithica.func.users.get_user_by_name"),
        fake_datetime("1969-02-12"),
    ):
        users.get_user_by_name.return_value = user_token.user
        user_tokens.serialize_user_token.return_value = "serialized user token"
        user_tokens.get_by_user_and_token.return_value = user_token
        result = ok(
            client.put(
                "/user-token/%s/%s" % (user_token.user.name, user_token.token),
                user=user_token.user,
                body={
                    "version": user_token.version,
                    "enabled": False,
                },
            )
        )
        assert result == "serialized user token"
        user_tokens.get_by_user_and_token.assert_called_once_with(
            user_token.user, user_token.token
        )
        user_tokens.update_user_token_enabled.assert_called_once_with(user_token, False)
        user_tokens.update_user_token_edit_time.assert_called_once_with(user_token)


def test_edit_unknown_user_token(user_token_factory, client):
    user_token = user_token_factory()
    db.session.add(user_token)
    db.session.commit()
    assert_error(
        client.put(
            "/user-token/%s/%s" % (user_token.user.name, "no-such-token"),
            user=user_token.user,
            body={"version": 1},
        ),
        user_tokens.UserTokenNotFoundError,
    )
