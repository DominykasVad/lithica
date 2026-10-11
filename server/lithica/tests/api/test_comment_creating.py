from datetime import datetime
from unittest.mock import patch

import pytest

from lithica import db, errors, model
from lithica.func import comments, posts
from lithica.tests.api.http import assert_error, ok


@pytest.fixture(autouse=True)
def inject_config(config_injector):
    config_injector({"privileges": {"comments:create": model.User.RANK_REGULAR}})


def test_creating_comment(user_factory, post_factory, client, fake_datetime):
    post = post_factory()
    user = user_factory(rank=model.User.RANK_REGULAR)
    db.session.add_all([post, user])
    db.session.flush()
    with patch("lithica.func.comments.serialize_comment"), fake_datetime("1997-01-01"):
        comments.serialize_comment.return_value = "serialized comment"
        result = ok(
            client.post(
                "/comments", user=user, body={"text": "input", "postId": post.post_id}
            )
        )
        assert result == "serialized comment"
        comment = db.session.query(model.Comment).one()
        assert comment.text == "input"
        assert comment.creation_time == datetime(1997, 1, 1)
        assert comment.last_edit_time is None
        assert comment.user and comment.user.user_id == user.user_id
        assert comment.post and comment.post.post_id == post.post_id


@pytest.mark.parametrize(
    "params",
    [
        {"text": None},
        {"text": ""},
        {"text": [None]},
        {"text": [""]},
    ],
)
def test_trying_to_pass_invalid_params(user_factory, post_factory, client, params):
    post = post_factory()
    user = user_factory(rank=model.User.RANK_REGULAR)
    db.session.add_all([post, user])
    db.session.flush()
    real_params = {"text": "input", "postId": post.post_id}
    for key, value in params.items():
        real_params[key] = value
    assert_error(
        client.post("/comments", user=user, body=real_params), errors.ValidationError
    )


@pytest.mark.parametrize("field", ["text", "postId"])
def test_trying_to_omit_mandatory_field(user_factory, client, field):
    params = {
        "text": "input",
        "postId": 1,
    }
    del params[field]
    assert_error(
        client.post(
            "/comments", user=user_factory(rank=model.User.RANK_REGULAR), body={}
        ),
        errors.ValidationError,
    )


def test_trying_to_comment_non_existing(user_factory, client):
    user = user_factory(rank=model.User.RANK_REGULAR)
    db.session.add_all([user])
    db.session.flush()
    assert_error(
        client.post("/comments", user=user, body={"text": "bad", "postId": 5}),
        posts.PostNotFoundError,
    )


def test_trying_to_create_without_privileges(user_factory, client):
    assert_error(
        client.post(
            "/comments", user=user_factory(rank=model.User.RANK_ANONYMOUS), body={}
        ),
        errors.AuthError,
    )
