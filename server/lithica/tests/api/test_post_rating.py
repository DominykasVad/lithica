from unittest.mock import patch

import pytest

from lithica import db, errors, model
from lithica.func import posts
from lithica.tests.api.http import assert_error, ok


@pytest.fixture(autouse=True)
def inject_config(config_injector):
    config_injector({"privileges": {"posts:score": model.User.RANK_REGULAR}})


def test_simple_rating(user_factory, post_factory, client, fake_datetime):
    post = post_factory()
    db.session.add(post)
    db.session.commit()
    with patch("lithica.func.posts.serialize_post"), fake_datetime("1997-12-01"):
        posts.serialize_post.return_value = "serialized post"
        result = ok(
            client.put(
                "/post/%s/score" % post.post_id, user=user_factory(), body={"score": 1}
            )
        )
        assert result == "serialized post"
        post = db.session.query(model.Post).one()
        assert db.session.query(model.PostScore).count() == 1
        assert post is not None
        assert post.score == 1


def test_updating_rating(user_factory, post_factory, client, fake_datetime):
    user = user_factory()
    post = post_factory()
    db.session.add(post)
    db.session.commit()
    with patch("lithica.func.posts.serialize_post"):
        with fake_datetime("1997-12-01"):
            ok(
                client.put(
                    "/post/%s/score" % post.post_id, user=user, body={"score": 1}
                )
            )
        with fake_datetime("1997-12-02"):
            ok(
                client.put(
                    "/post/%s/score" % post.post_id, user=user, body={"score": -1}
                )
            )
        post = db.session.query(model.Post).one()
        assert db.session.query(model.PostScore).count() == 1
        assert post.score == -1


def test_updating_rating_to_zero(user_factory, post_factory, client, fake_datetime):
    user = user_factory()
    post = post_factory()
    db.session.add(post)
    db.session.commit()
    with patch("lithica.func.posts.serialize_post"):
        with fake_datetime("1997-12-01"):
            ok(
                client.put(
                    "/post/%s/score" % post.post_id, user=user, body={"score": 1}
                )
            )
        with fake_datetime("1997-12-02"):
            ok(
                client.put(
                    "/post/%s/score" % post.post_id, user=user, body={"score": 0}
                )
            )
        post = db.session.query(model.Post).one()
        assert db.session.query(model.PostScore).count() == 0
        assert post.score == 0


def test_deleting_rating(user_factory, post_factory, client, fake_datetime):
    user = user_factory()
    post = post_factory()
    db.session.add(post)
    db.session.commit()
    with patch("lithica.func.posts.serialize_post"):
        with fake_datetime("1997-12-01"):
            ok(
                client.put(
                    "/post/%s/score" % post.post_id, user=user, body={"score": 1}
                )
            )
        with fake_datetime("1997-12-02"):
            ok(client.delete("/post/%s/score" % post.post_id, user=user))
        post = db.session.query(model.Post).one()
        assert db.session.query(model.PostScore).count() == 0
        assert post.score == 0


def test_ratings_from_multiple_users(user_factory, post_factory, client, fake_datetime):
    user1 = user_factory()
    user2 = user_factory()
    post = post_factory()
    db.session.add_all([user1, user2, post])
    db.session.commit()
    with patch("lithica.func.posts.serialize_post"):
        with fake_datetime("1997-12-01"):
            ok(
                client.put(
                    "/post/%s/score" % post.post_id, user=user1, body={"score": 1}
                )
            )
        with fake_datetime("1997-12-02"):
            ok(
                client.put(
                    "/post/%s/score" % post.post_id, user=user2, body={"score": -1}
                )
            )
        post = db.session.query(model.Post).one()
        assert db.session.query(model.PostScore).count() == 2
        assert post.score == 0


def test_trying_to_omit_mandatory_field(user_factory, post_factory, client):
    post = post_factory()
    db.session.add(post)
    db.session.commit()
    assert_error(
        client.put("/post/%s/score" % post.post_id, user=user_factory(), body={}),
        errors.ValidationError,
    )


def test_trying_to_update_non_existing(user_factory, client):
    assert_error(
        client.put("/post/5/score", user=user_factory(), body={"score": 1}),
        posts.PostNotFoundError,
    )


def test_trying_to_rate_without_privileges(user_factory, post_factory, client):
    post = post_factory()
    db.session.add(post)
    db.session.commit()
    assert_error(
        client.put(
            "/post/%s/score" % post.post_id,
            user=user_factory(rank=model.User.RANK_ANONYMOUS),
            body={"score": 1},
        ),
        errors.AuthError,
    )
