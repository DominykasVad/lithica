from unittest.mock import patch

import pytest

from lithica import db, errors, model
from lithica.func import users
from lithica.tests.api.http import assert_error, ok


@pytest.fixture(autouse=True)
def inject_config(config_injector):
    config_injector(
        {
            "privileges": {
                "users:edit:self:name": model.User.RANK_REGULAR,
                "users:edit:self:pass": model.User.RANK_REGULAR,
                "users:edit:self:email": model.User.RANK_REGULAR,
                "users:edit:self:rank": model.User.RANK_MODERATOR,
                "users:edit:self:avatar": model.User.RANK_MODERATOR,
                "users:edit:any:name": model.User.RANK_MODERATOR,
                "users:edit:any:pass": model.User.RANK_MODERATOR,
                "users:edit:any:email": model.User.RANK_MODERATOR,
                "users:edit:any:rank": model.User.RANK_ADMINISTRATOR,
                "users:edit:any:avatar": model.User.RANK_ADMINISTRATOR,
            },
        }
    )


def test_updating_user(client, user_factory):
    user = user_factory(name="u1", rank=model.User.RANK_ADMINISTRATOR)
    auth_user = user_factory(rank=model.User.RANK_ADMINISTRATOR)
    db.session.add(user)
    db.session.flush()

    with (
        patch("lithica.func.users.create_user"),
        patch("lithica.func.users.update_user_name"),
        patch("lithica.func.users.update_user_password"),
        patch("lithica.func.users.update_user_email"),
        patch("lithica.func.users.update_user_rank"),
        patch("lithica.func.users.update_user_avatar"),
        patch("lithica.func.users.serialize_user"),
    ):
        users.serialize_user.return_value = "serialized user"

        result = ok(
            client.put(
                "/user/u1",
                user=auth_user,
                body={
                    "version": 1,
                    "name": "chewie",
                    "email": "asd@asd.asd",
                    "password": "oks",
                    "rank": "moderator",
                    "avatarStyle": "manual",
                },
                files={
                    "avatar": b"...",
                },
            )
        )

        assert result == "serialized user"
        users.create_user.assert_not_called()
        users.update_user_name.assert_called_once_with(user, "chewie")
        users.update_user_password.assert_called_once_with(user, "oks")
        users.update_user_email.assert_called_once_with(user, "asd@asd.asd")
        users.update_user_rank.assert_called_once_with(user, "moderator", auth_user)
        users.update_user_avatar.assert_called_once_with(user, "manual", b"...")
        users.serialize_user.assert_called_once_with(user, auth_user, options=[])


@pytest.mark.parametrize("field", ["name", "email", "password", "rank", "avatarStyle"])
def test_omitting_optional_field(user_factory, client, field):
    user = user_factory(name="u1", rank=model.User.RANK_ADMINISTRATOR)
    db.session.add(user)
    db.session.flush()
    params = {
        "name": "chewie",
        "email": "asd@asd.asd",
        "password": "oks",
        "rank": "moderator",
        "avatarStyle": "gravatar",
    }
    del params[field]
    with (
        patch("lithica.func.users.create_user"),
        patch("lithica.func.users.update_user_name"),
        patch("lithica.func.users.update_user_password"),
        patch("lithica.func.users.update_user_email"),
        patch("lithica.func.users.update_user_rank"),
        patch("lithica.func.users.update_user_avatar"),
        patch("lithica.func.users.serialize_user"),
    ):
        ok(
            client.put(
                "/user/u1",
                user=user,
                body={**params, **{"version": 1}},
                files={"avatar": b"..."},
            )
        )


def test_trying_to_update_non_existing(user_factory, client):
    user = user_factory(name="u1", rank=model.User.RANK_ADMINISTRATOR)
    db.session.add(user)
    db.session.flush()
    assert_error(client.put("/user/u2", user=user), users.UserNotFoundError)


@pytest.mark.parametrize(
    "params",
    [
        {"name": "whatever"},
        {"email": "whatever"},
        {"rank": "whatever"},
        {"password": "whatever"},
        {"avatarStyle": "whatever"},
    ],
)
def test_trying_to_update_field_without_privileges(user_factory, client, params):
    user1 = user_factory(name="u1", rank=model.User.RANK_REGULAR)
    user2 = user_factory(name="u2", rank=model.User.RANK_REGULAR)
    db.session.add_all([user1, user2])
    db.session.flush()
    assert_error(
        client.put(
            "/user/%s" % user2.name, user=user1, body={**params, **{"version": 1}}
        ),
        errors.AuthError,
    )
