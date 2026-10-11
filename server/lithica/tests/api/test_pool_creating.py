from unittest.mock import patch

import pytest

from lithica import errors, model
from lithica.func import pools, posts, snapshots
from lithica.tests.api.http import assert_error, ok


@pytest.fixture(autouse=True)
def inject_config(config_injector):
    config_injector({"privileges": {"pools:create": model.User.RANK_REGULAR}})


def test_creating_simple_pools(pool_factory, user_factory, client):
    auth_user = user_factory(rank=model.User.RANK_REGULAR)
    pool = pool_factory()
    with (
        patch("lithica.func.pools.create_pool"),
        patch("lithica.func.pools.get_or_create_pools_by_names"),
        patch("lithica.func.pools.serialize_pool"),
        patch("lithica.func.snapshots.create"),
    ):
        posts.get_posts_by_ids.return_value = ([], [])
        pools.create_pool.return_value = pool
        pools.serialize_pool.return_value = "serialized pool"
        result = ok(
            client.post(
                "/pool",
                user=auth_user,
                body={
                    "names": ["pool1", "pool2"],
                    "category": "default",
                    "description": "desc",
                    "posts": [1, 2],
                },
            )
        )
        assert result == "serialized pool"
        pools.create_pool.assert_called_once_with(["pool1", "pool2"], "default", [1, 2])
        snapshots.create.assert_called_once_with(pool, auth_user)


@pytest.mark.parametrize("field", ["names", "category"])
def test_trying_to_omit_mandatory_field(user_factory, client, field):
    params = {
        "names": ["pool1", "pool2"],
        "category": "default",
        "description": "desc",
        "posts": [],
    }
    del params[field]
    assert_error(
        client.post(
            "/pool", user=user_factory(rank=model.User.RANK_REGULAR), body=params
        ),
        errors.ValidationError,
    )


@pytest.mark.parametrize("field", ["description", "posts"])
def test_omitting_optional_field(pool_factory, user_factory, client, field):
    params = {
        "names": ["pool1", "pool2"],
        "category": "default",
        "description": "desc",
        "posts": [],
    }
    del params[field]
    with (
        patch("lithica.func.pools.create_pool"),
        patch("lithica.func.pools.serialize_pool"),
        patch("lithica.func.snapshots._post_to_webhooks"),
    ):
        pools.create_pool.return_value = pool_factory()
        ok(
            client.post(
                "/pool", user=user_factory(rank=model.User.RANK_REGULAR), body=params
            )
        )


def test_trying_to_create_pool_without_privileges(user_factory, client):
    assert_error(
        client.post(
            "/pool",
            user=user_factory(rank=model.User.RANK_ANONYMOUS),
            body={
                "names": ["pool"],
                "category": "default",
                "posts": [],
            },
        ),
        errors.AuthError,
    )
