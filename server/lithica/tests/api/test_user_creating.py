from unittest.mock import ANY, patch

import pytest

from lithica import api, errors, model
from lithica.func import users


@pytest.fixture(autouse=True)
def inject_config(config_injector):
    config_injector({"privileges": {"users:create:self": "regular"}})


def test_creating_user(user_factory, context_factory, fake_datetime):
    user = user_factory()
    with patch("lithica.func.users.create_user"), patch(
        "lithica.func.users.update_user_name"
    ), patch("lithica.func.users.update_user_password"), patch(
        "lithica.func.users.update_user_email"
    ), patch(
        "lithica.func.users.update_user_rank"
    ), patch(
        "lithica.func.users.update_user_avatar"
    ), patch(
        "lithica.func.users.serialize_user"
    ), fake_datetime(
        "1969-02-12"
    ):
        users.serialize_user.return_value = "serialized user"
        users.create_user.return_value = user
        result = api.user_api.create_user(
            context_factory(
                params={
                    "name": "chewie1",
                    "email": "asd@asd.asd",
                    "password": "oks",
                    "rank": "moderator",
                    "avatarStyle": "manual",
                },
                files={"avatar": b"..."},
                user=user_factory(rank=model.User.RANK_REGULAR),
            )
        )
        assert result == "serialized user"
        users.create_user.assert_called_once_with(
            "chewie1", "oks", "asd@asd.asd"
        )
        assert not users.update_user_name.called
        assert not users.update_user_password.called
        assert not users.update_user_email.called
        users.update_user_rank.assert_called_once_with(user, "moderator", ANY)
        users.update_user_avatar.assert_called_once_with(user, "manual", b"...")


@pytest.mark.parametrize("field", ["name", "password"])
def test_trying_to_omit_mandatory_field(user_factory, context_factory, field):
    params = {
        "name": "chewie",
        "email": "asd@asd.asd",
        "password": "oks",
    }
    user = user_factory()
    auth_user = user_factory(rank=model.User.RANK_REGULAR)
    del params[field]
    with patch("lithica.func.users.create_user"), pytest.raises(
        errors.MissingRequiredParameterError
    ):
        users.create_user.return_value = user
        api.user_api.create_user(
            context_factory(params=params, user=auth_user)
        )


@pytest.mark.parametrize("field", ["rank", "email", "avatarStyle"])
def test_omitting_optional_field(user_factory, context_factory, field):
    params = {
        "name": "chewie",
        "email": "asd@asd.asd",
        "password": "oks",
        "rank": "moderator",
        "avatarStyle": "gravatar",
    }
    del params[field]
    user = user_factory()
    auth_user = user_factory(rank=model.User.RANK_MODERATOR)
    with patch("lithica.func.users.create_user"), patch(
        "lithica.func.users.update_user_avatar"
    ), patch("lithica.func.users.serialize_user"):
        users.create_user.return_value = user
        api.user_api.create_user(
            context_factory(params=params, user=auth_user)
        )


def test_trying_to_create_user_without_privileges(
    context_factory, user_factory
):
    with pytest.raises(errors.AuthError):
        api.user_api.create_user(
            context_factory(
                params="whatever",
                user=user_factory(rank=model.User.RANK_ANONYMOUS),
            )
        )
