from unittest.mock import patch

import pytest

from lithica import db, errors, model
from lithica.func import posts, snapshots
from lithica.tests.api.http import assert_error, ok


@pytest.fixture(autouse=True)
def inject_config(config_injector):
    config_injector(
        {
            "privileges": {
                "posts:feature": model.User.RANK_REGULAR,
                "posts:view": model.User.RANK_REGULAR,
                "posts:view:featured": model.User.RANK_REGULAR,
            },
        }
    )


def test_featuring(user_factory, post_factory, client):
    auth_user = user_factory(rank=model.User.RANK_REGULAR)
    post = post_factory(id=1)
    db.session.add(post)
    db.session.flush()
    assert not posts.get_post_by_id(1).is_featured
    with (
        patch("lithica.func.posts.serialize_post"),
        patch("lithica.func.snapshots.modify"),
    ):
        posts.serialize_post.return_value = "serialized post"
        result = ok(client.post("/featured-post", user=auth_user, body={"id": 1}))
        assert result == "serialized post"
        featured_post = posts.try_get_featured_post()
        assert featured_post is not None
        assert featured_post.post_id == 1
        assert posts.get_post_by_id(1).is_featured
        result = ok(
            client.get(
                "/featured-post", user=user_factory(rank=model.User.RANK_REGULAR)
            )
        )
        assert result == "serialized post"
        snapshots.modify.assert_called_once_with(post, auth_user)


def test_trying_to_omit_required_parameter(user_factory, client):
    assert_error(
        client.post("/featured-post", user=user_factory(rank=model.User.RANK_REGULAR)),
        errors.MissingRequiredParameterError,
    )


def test_trying_to_feature_the_same_post_twice(user_factory, post_factory, client):
    db.session.add(post_factory(id=1))
    db.session.commit()
    with (
        patch("lithica.func.posts.serialize_post"),
        patch("lithica.func.snapshots._post_to_webhooks"),
    ):
        ok(
            client.post(
                "/featured-post",
                user=user_factory(rank=model.User.RANK_REGULAR),
                body={"id": 1},
            )
        )
        assert_error(
            client.post(
                "/featured-post",
                user=user_factory(rank=model.User.RANK_REGULAR),
                body={"id": 1},
            ),
            posts.PostAlreadyFeaturedError,
        )


def test_featuring_one_post_after_another(
    user_factory, post_factory, client, fake_datetime
):
    db.session.add(post_factory(id=1))
    db.session.add(post_factory(id=2))
    db.session.commit()
    assert posts.try_get_featured_post() is None
    assert not posts.get_post_by_id(1).is_featured
    assert not posts.get_post_by_id(2).is_featured
    with (
        patch("lithica.func.posts.serialize_post"),
        patch("lithica.func.snapshots._post_to_webhooks"),
    ):
        with fake_datetime("1997"):
            ok(
                client.post(
                    "/featured-post",
                    user=user_factory(rank=model.User.RANK_REGULAR),
                    body={"id": 1},
                )
            )
        with fake_datetime("1998"):
            ok(
                client.post(
                    "/featured-post",
                    user=user_factory(rank=model.User.RANK_REGULAR),
                    body={"id": 2},
                )
            )
        featured_post = posts.try_get_featured_post()
        assert featured_post is not None
        assert featured_post.post_id == 2
        assert not posts.get_post_by_id(1).is_featured
        assert posts.get_post_by_id(2).is_featured


def test_trying_to_feature_non_existing(user_factory, client):
    assert_error(
        client.post(
            "/featured-post",
            user=user_factory(rank=model.User.RANK_REGULAR),
            body={"id": 1},
        ),
        posts.PostNotFoundError,
    )


def test_trying_to_retrieve_without_privileges(user_factory, client):
    assert_error(
        client.get("/featured-post", user=user_factory(rank=model.User.RANK_ANONYMOUS)),
        errors.AuthError,
    )


def test_trying_to_feature_without_privileges(user_factory, client):
    assert_error(
        client.post(
            "/featured-post", user=user_factory(rank=model.User.RANK_ANONYMOUS)
        ),
        errors.AuthError,
    )
