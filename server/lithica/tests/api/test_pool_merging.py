from unittest.mock import patch

import pytest

from lithica import db, errors, model
from lithica.func import pools, snapshots
from lithica.tests.api.http import assert_error, ok


@pytest.fixture(autouse=True)
def inject_config(config_injector):
    config_injector({"privileges": {"pools:merge": model.User.RANK_REGULAR}})


def test_merging(user_factory, pool_factory, client, post_factory):
    auth_user = user_factory(rank=model.User.RANK_REGULAR)
    source_pool = pool_factory(id=1)
    target_pool = pool_factory(id=2)
    db.session.add_all([source_pool, target_pool])
    db.session.flush()
    assert source_pool.post_count == 0
    assert target_pool.post_count == 0
    post = post_factory(id=1)
    source_pool.posts = [post]
    db.session.add(post)
    db.session.commit()
    assert source_pool.post_count == 1
    assert target_pool.post_count == 0
    with (
        patch("lithica.func.pools.serialize_pool"),
        patch("lithica.func.pools.merge_pools"),
        patch("lithica.func.snapshots.merge"),
    ):
        ok(
            client.post(
                "/pool-merge",
                user=auth_user,
                body={
                    "removeVersion": 1,
                    "mergeToVersion": 1,
                    "remove": 1,
                    "mergeTo": 2,
                },
            )
        )
        pools.merge_pools.assert_called_once_with(source_pool, target_pool)
        snapshots.merge.assert_called_once_with(source_pool, target_pool, auth_user)


@pytest.mark.parametrize(
    "field", ["remove", "mergeTo", "removeVersion", "mergeToVersion"]
)
def test_trying_to_omit_mandatory_field(user_factory, pool_factory, client, field):
    db.session.add_all(
        [
            pool_factory(id=1),
            pool_factory(id=2),
        ]
    )
    db.session.commit()
    params = {
        "removeVersion": 1,
        "mergeToVersion": 1,
        "remove": 1,
        "mergeTo": 2,
    }
    del params[field]
    assert_error(
        client.post(
            "/pool-merge", user=user_factory(rank=model.User.RANK_REGULAR), body=params
        ),
        errors.ValidationError,
    )


def test_trying_to_merge_non_existing(user_factory, pool_factory, client):
    db.session.add(pool_factory(id=1))
    db.session.commit()
    assert_error(
        client.post(
            "/pool-merge",
            user=user_factory(rank=model.User.RANK_REGULAR),
            body={"remove": 1, "mergeTo": 9999},
        ),
        pools.PoolNotFoundError,
    )
    assert_error(
        client.post(
            "/pool-merge",
            user=user_factory(rank=model.User.RANK_REGULAR),
            body={"remove": 9999, "mergeTo": 1},
        ),
        pools.PoolNotFoundError,
    )


def test_trying_to_merge_without_privileges(user_factory, pool_factory, client):
    db.session.add_all(
        [
            pool_factory(id=1),
            pool_factory(id=2),
        ]
    )
    db.session.commit()
    assert_error(
        client.post(
            "/pool-merge",
            user=user_factory(rank=model.User.RANK_ANONYMOUS),
            body={
                "removeVersion": 1,
                "mergeToVersion": 1,
                "remove": 1,
                "mergeTo": 2,
            },
        ),
        errors.AuthError,
    )
