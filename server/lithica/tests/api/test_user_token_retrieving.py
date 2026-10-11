from unittest.mock import patch

import pytest

from lithica import db
from lithica.api import resources
from lithica.func import user_tokens, users
from lithica.tests.api.http import assert_fits, ok


@pytest.fixture(autouse=True)
def inject_config(config_injector):
    config_injector({"privileges": {"user_tokens:list:self": "regular"}})


def test_retrieving_user_tokens(user_token_factory, client, fake_datetime):
    user_token1 = user_token_factory()
    user_token2 = user_token_factory(user=user_token1.user)
    user_token3 = user_token_factory(user=user_token1.user)
    with (
        patch("lithica.func.user_tokens.get_user_tokens"),
        patch("lithica.func.user_tokens.serialize_user_token"),
        patch("lithica.func.users.get_user_by_name"),
        fake_datetime("1969-02-12"),
    ):
        users.get_user_by_name.return_value = user_token1.user
        user_tokens.serialize_user_token.return_value = "serialized user token"
        user_tokens.get_user_tokens.return_value = [
            user_token1,
            user_token2,
            user_token3,
        ]
        result = ok(
            client.get("/user-tokens/%s" % user_token1.user.name, user=user_token1.user)
        )
        assert result == {"results": ["serialized user token"] * 3}
        user_tokens.get_user_tokens.assert_called_once_with(user_token1.user)


def test_user_token_fits_its_response_model(
    user_token_factory, client, config_injector
):
    config_injector(
        {
            "thumbnails": {"avatar_width": 30, "avatar_height": 30},
            "privileges": {"user_tokens:list:self": "regular"},
        }
    )
    user_token = user_token_factory()
    db.session.add(user_token)
    db.session.flush()
    listed = ok(
        client.get("/user-tokens/%s" % user_token.user.name, user=user_token.user)
    )
    assert [token["token"] for token in listed["results"]] == [user_token.token]
    assert_fits(resources.Unpaged[resources.UserToken], listed)
