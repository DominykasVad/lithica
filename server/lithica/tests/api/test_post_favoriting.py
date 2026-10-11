from datetime import datetime
from unittest.mock import patch

import pytest

from lithica import db, errors, model
from lithica.func import posts
from lithica.tests.api.http import assert_error, ok


@pytest.fixture(autouse=True)
def inject_config(config_injector):
    config_injector({"privileges": {"posts:favorite": model.User.RANK_REGULAR}})


def test_adding_to_favorites(user_factory, post_factory, client, fake_datetime):
    post = post_factory()
    db.session.add(post)
    db.session.commit()
    assert post.score == 0
    with patch("lithica.func.posts.serialize_post"), fake_datetime("1997-12-01"):
        posts.serialize_post.return_value = "serialized post"
        result = ok(
            client.post("/post/%s/favorite" % post.post_id, user=user_factory())
        )
        assert result == "serialized post"
        post = db.session.query(model.Post).one()
        assert db.session.query(model.PostFavorite).count() == 1
        assert post is not None
        assert post.favorite_count == 1
        assert post.score == 1


def test_removing_from_favorites(user_factory, post_factory, client, fake_datetime):
    user = user_factory()
    post = post_factory()
    db.session.add(post)
    db.session.commit()
    assert post.score == 0
    with patch("lithica.func.posts.serialize_post"):
        with fake_datetime("1997-12-01"):
            ok(client.post("/post/%s/favorite" % post.post_id, user=user))
        assert post.score == 1
        with fake_datetime("1997-12-02"):
            ok(client.delete("/post/%s/favorite" % post.post_id, user=user))
        post = db.session.query(model.Post).one()
        assert post.score == 1
        assert db.session.query(model.PostFavorite).count() == 0
        assert post.favorite_count == 0


def test_favoriting_twice(user_factory, post_factory, client, fake_datetime):
    user = user_factory()
    post = post_factory()
    db.session.add(post)
    db.session.commit()
    with patch("lithica.func.posts.serialize_post"):
        with fake_datetime("1997-12-01"):
            ok(client.post("/post/%s/favorite" % post.post_id, user=user))
        with fake_datetime("1997-12-02"):
            ok(client.post("/post/%s/favorite" % post.post_id, user=user))
        post = db.session.query(model.Post).one()
        assert db.session.query(model.PostFavorite).count() == 1
        assert post.favorite_count == 1


def test_removing_twice(user_factory, post_factory, client, fake_datetime):
    user = user_factory()
    post = post_factory()
    db.session.add(post)
    db.session.commit()
    with patch("lithica.func.posts.serialize_post"):
        with fake_datetime("1997-12-01"):
            ok(client.post("/post/%s/favorite" % post.post_id, user=user))
        with fake_datetime("1997-12-02"):
            ok(client.delete("/post/%s/favorite" % post.post_id, user=user))
        with fake_datetime("1997-12-02"):
            ok(client.delete("/post/%s/favorite" % post.post_id, user=user))
        post = db.session.query(model.Post).one()
        assert db.session.query(model.PostFavorite).count() == 0
        assert post.favorite_count == 0


def test_favorites_from_multiple_users(
    user_factory, post_factory, client, fake_datetime
):
    user1 = user_factory()
    user2 = user_factory()
    post = post_factory()
    db.session.add_all([user1, user2, post])
    db.session.commit()
    with patch("lithica.func.posts.serialize_post"):
        with fake_datetime("1997-12-01"):
            ok(client.post("/post/%s/favorite" % post.post_id, user=user1))
        with fake_datetime("1997-12-02"):
            ok(client.post("/post/%s/favorite" % post.post_id, user=user2))
        post = db.session.query(model.Post).one()
        assert db.session.query(model.PostFavorite).count() == 2
        assert post.favorite_count == 2
        assert post.last_favorite_time == datetime(1997, 12, 2)


def test_trying_to_update_non_existing(user_factory, client):
    assert_error(
        client.post("/post/5/favorite", user=user_factory()), posts.PostNotFoundError
    )


def test_trying_to_rate_without_privileges(user_factory, post_factory, client):
    post = post_factory()
    db.session.add(post)
    db.session.commit()
    assert_error(
        client.post(
            "/post/%s/favorite" % post.post_id,
            user=user_factory(rank=model.User.RANK_ANONYMOUS),
        ),
        errors.AuthError,
    )
