from unittest.mock import patch

import pytest

from lithica import db, errors, model
from lithica.func import pools, snapshots
from lithica.tests.api.http import assert_error, ok


@pytest.fixture(autouse=True)
def inject_config(config_injector):
    config_injector({"privileges": {"pools:delete": model.User.RANK_REGULAR}})


def test_deleting(user_factory, pool_factory, client):
    auth_user = user_factory(rank=model.User.RANK_REGULAR)
    pool = pool_factory(id=1)
    db.session.add(pool)
    db.session.commit()
    with patch("lithica.func.snapshots.delete"):
        result = ok(client.delete("/pool/1", user=auth_user, body={"version": 1}))
        assert result == {}
        assert db.session.query(model.Pool).count() == 0
        snapshots.delete.assert_called_once_with(pool, auth_user)


def test_deleting_used(user_factory, pool_factory, client, post_factory):
    pool = pool_factory(id=1)
    post = post_factory(id=1)
    pool.posts.append(post)
    db.session.add_all([pool, post])
    db.session.commit()
    with patch("lithica.func.snapshots._post_to_webhooks"):
        ok(
            client.delete(
                "/pool/1",
                user=user_factory(rank=model.User.RANK_REGULAR),
                body={"version": 1},
            )
        )
        db.session.refresh(post)
        assert db.session.query(model.Pool).count() == 0
        assert db.session.query(model.PoolPost).count() == 0
        assert post.pools == []


def test_trying_to_delete_non_existing(user_factory, client):
    assert_error(
        client.delete("/pool/9999", user=user_factory(rank=model.User.RANK_REGULAR)),
        pools.PoolNotFoundError,
    )


def test_trying_to_delete_without_privileges(user_factory, pool_factory, client):
    db.session.add(pool_factory(id=1))
    db.session.commit()
    assert_error(
        client.delete(
            "/pool/1",
            user=user_factory(rank=model.User.RANK_ANONYMOUS),
            body={"version": 1},
        ),
        errors.AuthError,
    )
    assert db.session.query(model.Pool).count() == 1
