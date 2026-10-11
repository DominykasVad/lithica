from unittest.mock import patch

import pytest

from lithica import db, errors, model
from lithica.api import resources
from lithica.func import users
from lithica.tests.api.http import assert_error, assert_fits, ok


@pytest.fixture(autouse=True)
def inject_config(config_injector):
    config_injector(
        {
            "privileges": {
                "users:list": model.User.RANK_REGULAR,
                "users:view": model.User.RANK_REGULAR,
                "users:edit:any:email": model.User.RANK_MODERATOR,
            },
        }
    )


def test_retrieving_multiple(user_factory, client):
    user1 = user_factory(name="u1", rank=model.User.RANK_MODERATOR)
    user2 = user_factory(name="u2", rank=model.User.RANK_MODERATOR)
    db.session.add_all([user1, user2])
    db.session.flush()
    with patch("lithica.func.users.serialize_user"):
        users.serialize_user.return_value = "serialized user"
        result = ok(
            client.get(
                "/users",
                user=user_factory(rank=model.User.RANK_REGULAR),
                query={"query": "", "page": 1},
            )
        )
        assert result == {
            "query": "",
            "offset": 0,
            "limit": 100,
            "total": 2,
            "results": ["serialized user", "serialized user"],
        }


def test_trying_to_retrieve_multiple_without_privileges(user_factory, client):
    assert_error(
        client.get(
            "/users",
            user=user_factory(rank=model.User.RANK_ANONYMOUS),
            query={"query": "", "page": 1},
        ),
        errors.AuthError,
    )


def test_retrieving_single(user_factory, client):
    user = user_factory(name="u1", rank=model.User.RANK_REGULAR)
    auth_user = user_factory(rank=model.User.RANK_REGULAR)
    db.session.add(user)
    db.session.flush()
    with patch("lithica.func.users.serialize_user"):
        users.serialize_user.return_value = "serialized user"
        result = ok(client.get("/user/u1", user=auth_user))
        assert result == "serialized user"


def test_trying_to_retrieve_single_non_existing(user_factory, client):
    auth_user = user_factory(rank=model.User.RANK_REGULAR)
    assert_error(client.get("/user/-", user=auth_user), users.UserNotFoundError)


def test_trying_to_retrieve_single_without_privileges(user_factory, client):
    auth_user = user_factory(rank=model.User.RANK_ANONYMOUS)
    db.session.add(user_factory(name="u1", rank=model.User.RANK_REGULAR))
    db.session.flush()
    assert_error(client.get("/user/u1", user=auth_user), errors.AuthError)


def test_user_fits_its_response_model(user_factory, client, config_injector):
    config_injector(
        {
            "thumbnails": {"avatar_width": 30, "avatar_height": 30},
            "privileges": {
                "users:list": model.User.RANK_REGULAR,
                "users:view": model.User.RANK_REGULAR,
                "users:edit:any:email": model.User.RANK_MODERATOR,
            },
        }
    )
    user = user_factory(name="u1", rank=model.User.RANK_REGULAR, email="u1@example.com")
    other = user_factory(name="u2", rank=model.User.RANK_REGULAR, email=None)
    db.session.add_all([user, other])
    db.session.flush()

    own = ok(client.get("/user/u1", user=user))
    assert own["email"] == "u1@example.com"
    assert own["likedPostCount"] == 0
    assert_fits(resources.User, own)

    # what the requester may not see is `false`, and still fits
    someone_else = ok(client.get("/user/u1", user=other))
    assert someone_else["email"] is False
    assert someone_else["likedPostCount"] is False
    assert_fits(resources.User, someone_else)

    listed = ok(client.get("/users", user=user))
    assert listed["total"] == 2
    assert_fits(resources.Paged[resources.User], listed)

    some_fields = ok(client.get("/user/u1", user=user, query={"fields": "name,rank"}))
    assert some_fields == {"name": "u1", "rank": "regular"}
    assert_fits(resources.User, some_fields, complete=False)


def test_unknown_field_is_refused(user_factory, client):
    user = user_factory(name="u1", rank=model.User.RANK_REGULAR)
    db.session.add(user)
    db.session.flush()
    response = client.get("/user/u1", user=user, query={"fields": "name,shoeSize"})
    assert_error(response, errors.ValidationError)
    assert "Invalid key: 'shoeSize'" in response.json()["description"]
