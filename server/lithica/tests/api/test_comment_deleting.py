import pytest

from lithica import db, errors, model
from lithica.func import comments
from lithica.tests.api.http import assert_error, ok


@pytest.fixture(autouse=True)
def inject_config(config_injector):
    config_injector(
        {
            "privileges": {
                "comments:delete:own": model.User.RANK_REGULAR,
                "comments:delete:any": model.User.RANK_MODERATOR,
            },
        }
    )


def test_deleting_own_comment(user_factory, comment_factory, client):
    user = user_factory()
    comment = comment_factory(user=user)
    db.session.add(comment)
    db.session.commit()
    result = ok(
        client.delete(
            "/comment/%s" % comment.comment_id, user=user, body={"version": 1}
        )
    )
    assert result == {}
    assert db.session.query(model.Comment).count() == 0


def test_deleting_someones_else_comment(user_factory, comment_factory, client):
    user1 = user_factory(rank=model.User.RANK_REGULAR)
    user2 = user_factory(rank=model.User.RANK_MODERATOR)
    comment = comment_factory(user=user1)
    db.session.add(comment)
    db.session.commit()
    ok(
        client.delete(
            "/comment/%s" % comment.comment_id, user=user2, body={"version": 1}
        )
    )
    assert db.session.query(model.Comment).count() == 0


def test_trying_to_delete_someones_else_comment_without_privileges(
    user_factory, comment_factory, client
):
    user1 = user_factory(rank=model.User.RANK_REGULAR)
    user2 = user_factory(rank=model.User.RANK_REGULAR)
    comment = comment_factory(user=user1)
    db.session.add(comment)
    db.session.commit()
    assert_error(
        client.delete(
            "/comment/%s" % comment.comment_id, user=user2, body={"version": 1}
        ),
        errors.AuthError,
    )
    assert db.session.query(model.Comment).count() == 1


def test_trying_to_delete_non_existing(user_factory, client):
    assert_error(
        client.delete(
            "/comment/1",
            user=user_factory(rank=model.User.RANK_REGULAR),
            body={"version": 1},
        ),
        comments.CommentNotFoundError,
    )
