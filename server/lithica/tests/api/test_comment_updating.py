from datetime import datetime
from unittest.mock import patch

import pytest

from lithica import db, errors, model
from lithica.func import comments
from lithica.tests.api.http import assert_error, ok


@pytest.fixture(autouse=True)
def inject_config(config_injector):
    config_injector(
        {
            "privileges": {
                "comments:edit:own": model.User.RANK_REGULAR,
                "comments:edit:any": model.User.RANK_MODERATOR,
            },
        }
    )


def test_simple_updating(user_factory, comment_factory, client, fake_datetime):
    user = user_factory(rank=model.User.RANK_REGULAR)
    comment = comment_factory(user=user)
    db.session.add(comment)
    db.session.commit()
    with patch("lithica.func.comments.serialize_comment"), fake_datetime("1997-12-01"):
        comments.serialize_comment.return_value = "serialized comment"
        result = ok(
            client.put(
                "/comment/%s" % comment.comment_id,
                user=user,
                body={"text": "new text", "version": 1},
            )
        )
        assert result == "serialized comment"
        assert comment.last_edit_time == datetime(1997, 12, 1)


@pytest.mark.parametrize(
    "params,expected_exception",
    [
        ({"text": None}, comments.EmptyCommentTextError),
        ({"text": ""}, comments.EmptyCommentTextError),
        ({"text": []}, comments.EmptyCommentTextError),
        ({"text": [None]}, errors.ValidationError),
        ({"text": [""]}, comments.EmptyCommentTextError),
    ],
)
def test_trying_to_pass_invalid_params(
    user_factory, comment_factory, client, params, expected_exception
):
    user = user_factory()
    comment = comment_factory(user=user)
    db.session.add(comment)
    db.session.commit()
    assert_error(
        client.put(
            "/comment/%s" % comment.comment_id,
            user=user,
            body={**params, **{"version": 1}},
        ),
        expected_exception,
    )


def test_trying_to_omit_mandatory_field(user_factory, comment_factory, client):
    user = user_factory()
    comment = comment_factory(user=user)
    db.session.add(comment)
    db.session.commit()
    assert_error(
        client.put("/comment/%s" % comment.comment_id, user=user, body={"version": 1}),
        errors.ValidationError,
    )


def test_trying_to_update_non_existing(user_factory, client):
    assert_error(
        client.put(
            "/comment/5",
            user=user_factory(rank=model.User.RANK_REGULAR),
            body={"text": "new text"},
        ),
        comments.CommentNotFoundError,
    )


def test_trying_to_update_someones_comment_without_privileges(
    user_factory, comment_factory, client
):
    user = user_factory(rank=model.User.RANK_REGULAR)
    user2 = user_factory(rank=model.User.RANK_REGULAR)
    comment = comment_factory(user=user)
    db.session.add(comment)
    db.session.commit()
    assert_error(
        client.put(
            "/comment/%s" % comment.comment_id,
            user=user2,
            body={"text": "new text", "version": 1},
        ),
        errors.AuthError,
    )


def test_updating_someones_comment_with_privileges(
    user_factory, comment_factory, client
):
    user = user_factory(rank=model.User.RANK_REGULAR)
    user2 = user_factory(rank=model.User.RANK_MODERATOR)
    comment = comment_factory(user=user)
    db.session.add(comment)
    db.session.commit()
    with patch("lithica.func.comments.serialize_comment"):
        ok(
            client.put(
                "/comment/%s" % comment.comment_id,
                user=user2,
                body={"text": "new text", "version": 1},
            )
        )
