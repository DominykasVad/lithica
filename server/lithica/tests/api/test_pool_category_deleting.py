from unittest.mock import patch

import pytest

from lithica import db, errors, model
from lithica.func import pool_categories, snapshots
from lithica.tests.api.http import assert_error, ok


@pytest.fixture(autouse=True)
def inject_config(config_injector):
    config_injector(
        {
            "privileges": {"pool_categories:delete": model.User.RANK_REGULAR},
        }
    )


def test_deleting(user_factory, pool_category_factory, client):
    auth_user = user_factory(rank=model.User.RANK_REGULAR)
    category = pool_category_factory(name="category")
    db.session.add(pool_category_factory(name="root"))
    db.session.add(category)
    db.session.flush()
    with patch("lithica.func.snapshots.delete"):
        result = ok(
            client.delete(
                "/pool-category/category", user=auth_user, body={"version": 1}
            )
        )
        assert result == {}
        assert db.session.query(model.PoolCategory).count() == 1
        assert db.session.query(model.PoolCategory).one().name == "root"
        snapshots.delete.assert_called_once_with(category, auth_user)


def test_trying_to_delete_used(
    user_factory, pool_category_factory, pool_factory, client
):
    category = pool_category_factory(name="category")
    db.session.add(category)
    db.session.flush()
    pool = pool_factory(names=["pool"], category=category)
    db.session.add(pool)
    db.session.commit()
    assert_error(
        client.delete(
            "/pool-category/category",
            user=user_factory(rank=model.User.RANK_REGULAR),
            body={"version": 1},
        ),
        pool_categories.PoolCategoryIsInUseError,
    )
    assert db.session.query(model.PoolCategory).count() == 1


def test_trying_to_delete_last(user_factory, pool_category_factory, client):
    db.session.add(pool_category_factory(name="root"))
    db.session.commit()
    assert_error(
        client.delete(
            "/pool-category/root",
            user=user_factory(rank=model.User.RANK_REGULAR),
            body={"version": 1},
        ),
        pool_categories.PoolCategoryIsInUseError,
    )


def test_trying_to_delete_non_existing(user_factory, client):
    assert_error(
        client.delete(
            "/pool-category/bad", user=user_factory(rank=model.User.RANK_REGULAR)
        ),
        pool_categories.PoolCategoryNotFoundError,
    )


def test_trying_to_delete_without_privileges(
    user_factory, pool_category_factory, client
):
    db.session.add(pool_category_factory(name="category"))
    db.session.commit()
    assert_error(
        client.delete(
            "/pool-category/category",
            user=user_factory(rank=model.User.RANK_ANONYMOUS),
            body={"version": 1},
        ),
        errors.AuthError,
    )
    assert db.session.query(model.PoolCategory).count() == 1
