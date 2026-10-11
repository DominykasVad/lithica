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
                "comments:list": model.User.RANK_REGULAR,
                "comments:view": model.User.RANK_REGULAR,
            },
        }
    )


def test_retrieving_multiple(user_factory, comment_factory, client):
    comment1 = comment_factory(text="text 1")
    comment2 = comment_factory(text="text 2")
    db.session.add_all([comment1, comment2])
    db.session.flush()
    with patch("lithica.func.comments.serialize_comment"):
        comments.serialize_comment.return_value = "serialized comment"
        result = ok(
            client.get(
                "/comments",
                user=user_factory(rank=model.User.RANK_REGULAR),
                query={"query": "", "offset": 0},
            )
        )
        assert result == {
            "query": "",
            "offset": 0,
            "limit": 100,
            "total": 2,
            "results": ["serialized comment", "serialized comment"],
        }


def test_trying_to_retrieve_multiple_without_privileges(user_factory, client):
    assert_error(
        client.get(
            "/comments",
            user=user_factory(rank=model.User.RANK_ANONYMOUS),
            query={"query": "", "offset": 0},
        ),
        errors.AuthError,
    )


def test_retrieving_single(user_factory, comment_factory, client):
    comment = comment_factory(text="dummy text")
    db.session.add(comment)
    db.session.flush()
    with patch("lithica.func.comments.serialize_comment"):
        comments.serialize_comment.return_value = "serialized comment"
        result = ok(
            client.get(
                "/comment/%s" % comment.comment_id,
                user=user_factory(rank=model.User.RANK_REGULAR),
            )
        )
        assert result == "serialized comment"


def test_trying_to_retrieve_single_non_existing(user_factory, client):
    assert_error(
        client.get("/comment/5", user=user_factory(rank=model.User.RANK_REGULAR)),
        comments.CommentNotFoundError,
    )


def test_trying_to_retrieve_single_without_privileges(user_factory, client):
    assert_error(
        client.get("/comment/5", user=user_factory(rank=model.User.RANK_ANONYMOUS)),
        errors.AuthError,
    )


def test_comment_fits_its_response_model(
    user_factory, comment_factory, client, config_injector
):
    from lithica.api import resources
    from lithica.tests.api.http import assert_fits

    config_injector(
        {
            "thumbnails": {"avatar_width": 30, "avatar_height": 30},
            "privileges": {
                "comments:list": model.User.RANK_REGULAR,
                "comments:view": model.User.RANK_REGULAR,
            },
        }
    )
    author = user_factory(name="author", rank=model.User.RANK_REGULAR)
    comment = comment_factory(user=author, text="hello")
    orphan = comment_factory(text="author deleted")
    db.session.add_all([author, comment, orphan])
    db.session.flush()
    orphan.user = None
    db.session.flush()

    single = ok(client.get("/comment/%d" % comment.comment_id, user=author))
    assert single["text"] == "hello"
    assert single["user"]["name"] == "author"
    assert single["creationTime"] == "1996-01-01T00:00:00Z"
    assert_fits(resources.Comment, single)

    without_author = ok(client.get("/comment/%d" % orphan.comment_id, user=author))
    assert without_author["user"] is None
    assert_fits(resources.Comment, without_author)

    listed = ok(client.get("/comments", user=author))
    assert listed["total"] >= 1
    assert_fits(resources.Paged[resources.Comment], listed)


def test_comment_id_that_is_not_a_number(user_factory, client):
    assert_error(
        client.get("/comment/abc", user=user_factory(rank=model.User.RANK_REGULAR)),
        comments.InvalidCommentIdError,
        "Invalid comment ID: 'abc'.",
    )
