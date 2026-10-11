from unittest.mock import patch

import pytest

from lithica import db, errors, model
from lithica.func import pools
from lithica.tests.api.http import assert_error, ok


@pytest.fixture(autouse=True)
def inject_config(config_injector):
    config_injector(
        {
            "privileges": {
                "pools:list": model.User.RANK_REGULAR,
                "pools:view": model.User.RANK_REGULAR,
            },
        }
    )


def test_retrieving_multiple(user_factory, pool_factory, client):
    pool1 = pool_factory(id=1)
    pool2 = pool_factory(id=2)
    db.session.add_all([pool2, pool1])
    db.session.flush()
    with patch("lithica.func.pools.serialize_pool"):
        pools.serialize_pool.return_value = "serialized pool"
        result = ok(
            client.get(
                "/pools",
                user=user_factory(rank=model.User.RANK_REGULAR),
                query={"query": "", "offset": 0},
            )
        )
        assert result == {
            "query": "",
            "offset": 0,
            "limit": 100,
            "total": 2,
            "results": ["serialized pool", "serialized pool"],
        }


def test_trying_to_retrieve_multiple_without_privileges(user_factory, client):
    assert_error(
        client.get(
            "/pools",
            user=user_factory(rank=model.User.RANK_ANONYMOUS),
            query={"query": "", "offset": 0},
        ),
        errors.AuthError,
    )


def test_retrieving_single(user_factory, pool_factory, client):
    db.session.add(pool_factory(id=1))
    db.session.flush()
    with patch("lithica.func.pools.serialize_pool"):
        pools.serialize_pool.return_value = "serialized pool"
        result = ok(
            client.get("/pool/1", user=user_factory(rank=model.User.RANK_REGULAR))
        )
        assert result == "serialized pool"


def test_trying_to_retrieve_single_non_existing(user_factory, client):
    assert_error(
        client.get("/pool/1", user=user_factory(rank=model.User.RANK_REGULAR)),
        pools.PoolNotFoundError,
    )


def test_trying_to_retrieve_single_without_privileges(user_factory, client):
    assert_error(
        client.get("/pool/1", user=user_factory(rank=model.User.RANK_ANONYMOUS)),
        errors.AuthError,
    )


def test_pool_fits_its_response_model(
    user_factory, pool_factory, post_factory, client, config_injector
):
    from lithica.api import resources
    from lithica.tests.api.http import assert_fits

    config_injector(
        {
            "secret": "test",
            "data_url": "http://example.com/data/",
            "privileges": {
                "pools:list": model.User.RANK_REGULAR,
                "pools:view": model.User.RANK_REGULAR,
                "pool_categories:view": model.User.RANK_REGULAR,
                "pool_categories:list": model.User.RANK_REGULAR,
            },
        }
    )
    post = post_factory()
    pool = pool_factory(id=1, names=["pool", "alias"], description="about")
    db.session.add_all([post, pool])
    db.session.flush()
    pool.posts.append(post)
    db.session.flush()
    user = user_factory(rank=model.User.RANK_REGULAR)

    single = ok(client.get("/pool/1", user=user))
    assert single["names"] == ["pool", "alias"]
    assert single["postCount"] == 1
    assert [post["id"] for post in single["posts"]] == [post.post_id]
    assert_fits(resources.Pool, single)

    listed = ok(client.get("/pools", user=user))
    assert listed["total"] == 1
    assert_fits(resources.Paged[resources.Pool], listed)

    category = ok(client.get("/pool-category/%s" % pool.category.name, user=user))
    assert category["usages"] == 1
    assert_fits(resources.PoolCategory, category)
    assert_fits(
        resources.Unpaged[resources.PoolCategory],
        ok(client.get("/pool-categories", user=user)),
    )


def test_pool_id_that_is_not_a_number(user_factory, client):
    assert_error(
        client.get("/pool/abc", user=user_factory(rank=model.User.RANK_REGULAR)),
        pools.PoolNotFoundError,
        "Pool 'abc' not found.",
    )
