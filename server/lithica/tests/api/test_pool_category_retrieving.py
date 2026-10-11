import pytest

from lithica import db, errors, model
from lithica.func import pool_categories
from lithica.tests.api.http import assert_error, ok


@pytest.fixture(autouse=True)
def inject_config(config_injector):
    config_injector(
        {
            "privileges": {
                "pool_categories:list": model.User.RANK_REGULAR,
                "pool_categories:view": model.User.RANK_REGULAR,
            },
        }
    )


def test_retrieving_multiple(user_factory, pool_category_factory, client):
    db.session.add_all(
        [
            pool_category_factory(name="c1"),
            pool_category_factory(name="c2"),
        ]
    )
    db.session.flush()
    result = ok(
        client.get("/pool-categories", user=user_factory(rank=model.User.RANK_REGULAR))
    )
    assert result is not None
    assert [cat["name"] for cat in result["results"]] == ["c1", "c2"]


def test_retrieving_single(user_factory, pool_category_factory, client):
    db.session.add(pool_category_factory(name="cat"))
    db.session.flush()
    result = ok(
        client.get(
            "/pool-category/cat", user=user_factory(rank=model.User.RANK_REGULAR)
        )
    )
    assert result == {
        "name": "cat",
        "color": "dummy",
        "usages": 0,
        "default": False,
        "version": 1,
    }


def test_trying_to_retrieve_single_non_existing(user_factory, client):
    assert_error(
        client.get("/pool-category/-", user=user_factory(rank=model.User.RANK_REGULAR)),
        pool_categories.PoolCategoryNotFoundError,
    )


def test_trying_to_retrieve_single_without_privileges(user_factory, client):
    assert_error(
        client.get(
            "/pool-category/-", user=user_factory(rank=model.User.RANK_ANONYMOUS)
        ),
        errors.AuthError,
    )
