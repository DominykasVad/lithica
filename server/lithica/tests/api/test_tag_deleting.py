from unittest.mock import patch

import pytest

from lithica import db, errors, model
from lithica.func import snapshots, tags
from lithica.tests.api.http import assert_error, ok


@pytest.fixture(autouse=True)
def inject_config(config_injector):
    config_injector({"privileges": {"tags:delete": model.User.RANK_REGULAR}})


def test_deleting(user_factory, tag_factory, client):
    auth_user = user_factory(rank=model.User.RANK_REGULAR)
    tag = tag_factory(names=["tag"])
    db.session.add(tag)
    db.session.commit()
    with patch("lithica.func.snapshots.delete"):
        result = ok(client.delete("/tag/tag", user=auth_user, body={"version": 1}))
        assert result == {}
        assert db.session.query(model.Tag).count() == 0
        snapshots.delete.assert_called_once_with(tag, auth_user)


def test_deleting_used(user_factory, tag_factory, client, post_factory):
    tag = tag_factory(names=["tag"])
    post = post_factory()
    post.tags.append(tag)
    db.session.add_all([tag, post])
    db.session.commit()
    with patch("lithica.func.snapshots._post_to_webhooks"):
        ok(
            client.delete(
                "/tag/tag",
                user=user_factory(rank=model.User.RANK_REGULAR),
                body={"version": 1},
            )
        )
        db.session.refresh(post)
        assert db.session.query(model.Tag).count() == 0
        assert post.tags == []


def test_trying_to_delete_non_existing(user_factory, client):
    assert_error(
        client.delete("/tag/bad", user=user_factory(rank=model.User.RANK_REGULAR)),
        tags.TagNotFoundError,
    )


def test_trying_to_delete_without_privileges(user_factory, tag_factory, client):
    db.session.add(tag_factory(names=["tag"]))
    db.session.commit()
    assert_error(
        client.delete(
            "/tag/tag",
            user=user_factory(rank=model.User.RANK_ANONYMOUS),
            body={"version": 1},
        ),
        errors.AuthError,
    )
    assert db.session.query(model.Tag).count() == 1
