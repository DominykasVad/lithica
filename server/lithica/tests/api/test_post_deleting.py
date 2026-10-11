from unittest.mock import patch

import pytest

from lithica import db, errors, model
from lithica.func import posts, snapshots
from lithica.tests.api.http import assert_error, ok


@pytest.fixture(autouse=True)
def inject_config(config_injector):
    config_injector(
        {
            "secret": "secret",
            "data_dir": "",
            "delete_source_files": False,
            "privileges": {"posts:delete": model.User.RANK_REGULAR},
        }
    )


def test_deleting(user_factory, post_factory, client):
    auth_user = user_factory(rank=model.User.RANK_REGULAR)
    post = post_factory(id=1)
    db.session.add(post)
    db.session.flush()
    with patch("lithica.func.snapshots.delete"):
        result = ok(client.delete("/post/1", user=auth_user, body={"version": 1}))
        assert result == {}
        assert db.session.query(model.Post).count() == 0
        snapshots.delete.assert_called_once_with(post, auth_user)


def test_trying_to_delete_non_existing(user_factory, client):
    assert_error(
        client.delete("/post/999", user=user_factory(rank=model.User.RANK_REGULAR)),
        posts.PostNotFoundError,
    )


def test_trying_to_delete_without_privileges(user_factory, post_factory, client):
    db.session.add(post_factory(id=1))
    db.session.commit()
    assert_error(
        client.delete("/post/1", user=user_factory(rank=model.User.RANK_ANONYMOUS)),
        errors.AuthError,
    )
    assert db.session.query(model.Post).count() == 1
