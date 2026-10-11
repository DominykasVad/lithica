from unittest.mock import patch

import pytest

from lithica import db, errors, model
from lithica.func import comments
from lithica.tests.api.http import assert_error, ok


@pytest.fixture(autouse=True)
def inject_config(config_injector):
    config_injector({"privileges": {"comments:score": model.User.RANK_REGULAR}})


def test_simple_rating(user_factory, comment_factory, client, fake_datetime):
    user = user_factory(rank=model.User.RANK_REGULAR)
    comment = comment_factory(user=user)
    db.session.add(comment)
    db.session.commit()
    with patch("lithica.func.comments.serialize_comment"), fake_datetime("1997-12-01"):
        comments.serialize_comment.return_value = "serialized comment"
        result = ok(
            client.put(
                "/comment/%s/score" % comment.comment_id, user=user, body={"score": 1}
            )
        )
        assert result == "serialized comment"
        assert db.session.query(model.CommentScore).count() == 1
        assert comment is not None
        assert comment.score == 1


def test_updating_rating(user_factory, comment_factory, client, fake_datetime):
    user = user_factory(rank=model.User.RANK_REGULAR)
    comment = comment_factory(user=user)
    db.session.add(comment)
    db.session.commit()
    with patch("lithica.func.comments.serialize_comment"):
        with fake_datetime("1997-12-01"):
            ok(
                client.put(
                    "/comment/%s/score" % comment.comment_id,
                    user=user,
                    body={"score": 1},
                )
            )
        with fake_datetime("1997-12-02"):
            ok(
                client.put(
                    "/comment/%s/score" % comment.comment_id,
                    user=user,
                    body={"score": -1},
                )
            )
        comment = db.session.query(model.Comment).one()
        assert db.session.query(model.CommentScore).count() == 1
        assert comment.score == -1


def test_updating_rating_to_zero(user_factory, comment_factory, client, fake_datetime):
    user = user_factory(rank=model.User.RANK_REGULAR)
    comment = comment_factory(user=user)
    db.session.add(comment)
    db.session.commit()
    with patch("lithica.func.comments.serialize_comment"):
        with fake_datetime("1997-12-01"):
            ok(
                client.put(
                    "/comment/%s/score" % comment.comment_id,
                    user=user,
                    body={"score": 1},
                )
            )
        with fake_datetime("1997-12-02"):
            ok(
                client.put(
                    "/comment/%s/score" % comment.comment_id,
                    user=user,
                    body={"score": 0},
                )
            )
        comment = db.session.query(model.Comment).one()
        assert db.session.query(model.CommentScore).count() == 0
        assert comment.score == 0


def test_deleting_rating(user_factory, comment_factory, client, fake_datetime):
    user = user_factory(rank=model.User.RANK_REGULAR)
    comment = comment_factory(user=user)
    db.session.add(comment)
    db.session.commit()
    with patch("lithica.func.comments.serialize_comment"):
        with fake_datetime("1997-12-01"):
            ok(
                client.put(
                    "/comment/%s/score" % comment.comment_id,
                    user=user,
                    body={"score": 1},
                )
            )
        with fake_datetime("1997-12-02"):
            ok(client.delete("/comment/%s/score" % comment.comment_id, user=user))
        comment = db.session.query(model.Comment).one()
        assert db.session.query(model.CommentScore).count() == 0
        assert comment.score == 0


def test_ratings_from_multiple_users(
    user_factory, comment_factory, client, fake_datetime
):
    user1 = user_factory(rank=model.User.RANK_REGULAR)
    user2 = user_factory(rank=model.User.RANK_REGULAR)
    comment = comment_factory()
    db.session.add_all([user1, user2, comment])
    db.session.commit()
    with patch("lithica.func.comments.serialize_comment"):
        with fake_datetime("1997-12-01"):
            ok(
                client.put(
                    "/comment/%s/score" % comment.comment_id,
                    user=user1,
                    body={"score": 1},
                )
            )
        with fake_datetime("1997-12-02"):
            ok(
                client.put(
                    "/comment/%s/score" % comment.comment_id,
                    user=user2,
                    body={"score": -1},
                )
            )
        comment = db.session.query(model.Comment).one()
        assert db.session.query(model.CommentScore).count() == 2
        assert comment.score == 0


def test_trying_to_omit_mandatory_field(user_factory, comment_factory, client):
    user = user_factory()
    comment = comment_factory(user=user)
    db.session.add(comment)
    db.session.commit()
    assert_error(
        client.put("/comment/%s/score" % comment.comment_id, user=user, body={}),
        errors.ValidationError,
    )


def test_trying_to_update_non_existing(user_factory, client):
    assert_error(
        client.put(
            "/comment/5/score",
            user=user_factory(rank=model.User.RANK_REGULAR),
            body={"score": 1},
        ),
        comments.CommentNotFoundError,
    )


def test_trying_to_rate_without_privileges(user_factory, comment_factory, client):
    comment = comment_factory()
    db.session.add(comment)
    db.session.commit()
    assert_error(
        client.put(
            "/comment/%s/score" % comment.comment_id,
            user=user_factory(rank=model.User.RANK_ANONYMOUS),
            body={"score": 1},
        ),
        errors.AuthError,
    )
