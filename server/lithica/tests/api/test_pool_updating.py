from unittest.mock import patch

import pytest

from lithica import db, errors, model
from lithica.func import pools, posts, snapshots
from lithica.tests.api.http import assert_error, ok


@pytest.fixture(autouse=True)
def inject_config(config_injector):
    config_injector(
        {
            "privileges": {
                "pools:create": model.User.RANK_REGULAR,
                "pools:edit:names": model.User.RANK_REGULAR,
                "pools:edit:category": model.User.RANK_REGULAR,
                "pools:edit:description": model.User.RANK_REGULAR,
                "pools:edit:posts": model.User.RANK_REGULAR,
            },
        }
    )


def test_simple_updating(user_factory, pool_factory, client):
    auth_user = user_factory(rank=model.User.RANK_REGULAR)
    pool = pool_factory(id=1, names=["pool1", "pool2"])
    db.session.add(pool)
    db.session.commit()
    with (
        patch("lithica.func.pools.create_pool"),
        patch("lithica.func.posts.get_posts_by_ids"),
        patch("lithica.func.pools.update_pool_names"),
        patch("lithica.func.pools.update_pool_category_name"),
        patch("lithica.func.pools.update_pool_description"),
        patch("lithica.func.pools.update_pool_posts"),
        patch("lithica.func.pools.serialize_pool"),
        patch("lithica.func.snapshots.modify"),
    ):
        posts.get_posts_by_ids.return_value = ([], [])
        pools.serialize_pool.return_value = "serialized pool"
        result = ok(
            client.put(
                "/pool/1",
                user=auth_user,
                body={
                    "version": 1,
                    "names": ["pool3"],
                    "category": "series",
                    "description": "desc",
                    "posts": [1, 2],
                },
            )
        )
        assert result == "serialized pool"
        pools.create_pool.assert_not_called()
        pools.update_pool_names.assert_called_once_with(pool, ["pool3"])
        pools.update_pool_category_name.assert_called_once_with(pool, "series")
        pools.update_pool_description.assert_called_once_with(pool, "desc")
        pools.update_pool_posts.assert_called_once_with(pool, [1, 2])
        pools.serialize_pool.assert_called_once_with(pool, options=[])
        snapshots.modify.assert_called_once_with(pool, auth_user)


@pytest.mark.parametrize(
    "field",
    [
        "names",
        "category",
        "description",
        "posts",
    ],
)
def test_omitting_optional_field(user_factory, pool_factory, client, field):
    db.session.add(pool_factory(id=1))
    db.session.commit()
    params = {
        "names": ["pool1", "pool2"],
        "category": "default",
        "description": "desc",
        "posts": [],
    }
    del params[field]
    with (
        patch("lithica.func.pools.create_pool"),
        patch("lithica.func.pools.update_pool_names"),
        patch("lithica.func.pools.update_pool_category_name"),
        patch("lithica.func.pools.serialize_pool"),
    ):
        ok(
            client.put(
                "/pool/1",
                user=user_factory(rank=model.User.RANK_REGULAR),
                body={**params, **{"version": 1}},
            )
        )


def test_trying_to_update_non_existing(user_factory, client):
    assert_error(
        client.put(
            "/pool/9999",
            user=user_factory(rank=model.User.RANK_REGULAR),
            body={"names": ["dummy"]},
        ),
        pools.PoolNotFoundError,
    )


@pytest.mark.parametrize(
    "params",
    [
        {"names": ["whatever"]},
        {"category": "whatever"},
        {"posts": [1]},
    ],
)
def test_trying_to_update_without_privileges(
    user_factory, pool_factory, client, params
):
    db.session.add(pool_factory(id=1))
    db.session.commit()
    assert_error(
        client.put(
            "/pool/1",
            user=user_factory(rank=model.User.RANK_ANONYMOUS),
            body={**params, **{"version": 1}},
        ),
        errors.AuthError,
    )


def test_trying_to_create_pools_without_privileges(
    config_injector, client, pool_factory, user_factory
):
    pool = pool_factory(id=1)
    db.session.add(pool)
    db.session.commit()
    config_injector(
        {
            "privileges": {
                "pools:create": model.User.RANK_ADMINISTRATOR,
                "pools:edit:posts": model.User.RANK_REGULAR,
            },
            "delete_source_files": False,
        }
    )
    with patch("lithica.func.posts.get_posts_by_ids"):
        posts.get_posts_by_ids.return_value = ([], ["new-post"])
        # the old test passed a pool id as well, which creating ignores
        assert_error(
            client.post(
                "/pool",
                user=user_factory(rank=model.User.RANK_REGULAR),
                body={"posts": [1, 2], "version": 1},
            ),
            errors.AuthError,
        )
