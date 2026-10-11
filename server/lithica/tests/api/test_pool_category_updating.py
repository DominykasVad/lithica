from unittest.mock import patch

import pytest

from lithica import db, errors, model
from lithica.func import pool_categories, snapshots
from lithica.tests.api.http import assert_error, ok


def _update_category_name(category, name):
    category.name = name


@pytest.fixture(autouse=True)
def inject_config(config_injector):
    config_injector(
        {
            "privileges": {
                "pool_categories:edit:name": model.User.RANK_REGULAR,
                "pool_categories:edit:color": model.User.RANK_REGULAR,
                "pool_categories:set_default": model.User.RANK_REGULAR,
            },
        }
    )


def test_simple_updating(user_factory, pool_category_factory, client):
    auth_user = user_factory(rank=model.User.RANK_REGULAR)
    category = pool_category_factory(name="name", color="black")
    db.session.add(category)
    db.session.flush()
    with (
        patch("lithica.func.pool_categories.serialize_category"),
        patch("lithica.func.pool_categories.update_category_name"),
        patch("lithica.func.pool_categories.update_category_color"),
        patch("lithica.func.snapshots.modify"),
    ):
        pool_categories.update_category_name.side_effect = _update_category_name
        pool_categories.serialize_category.return_value = "serialized category"
        result = ok(
            client.put(
                "/pool-category/name",
                user=auth_user,
                body={"name": "changed", "color": "white", "version": 1},
            )
        )
        assert result == "serialized category"
        pool_categories.update_category_name.assert_called_once_with(
            category, "changed"
        )
        pool_categories.update_category_color.assert_called_once_with(category, "white")
        snapshots.modify.assert_called_once_with(category, auth_user)


@pytest.mark.parametrize("field", ["name", "color"])
def test_omitting_optional_field(user_factory, pool_category_factory, client, field):
    db.session.add(pool_category_factory(name="name", color="black"))
    db.session.commit()
    params = {
        "name": "changed",
        "color": "white",
    }
    del params[field]
    with (
        patch("lithica.func.pool_categories.serialize_category"),
        patch("lithica.func.pool_categories.update_category_name"),
        patch("lithica.func.snapshots._post_to_webhooks"),
    ):
        ok(
            client.put(
                "/pool-category/name",
                user=user_factory(rank=model.User.RANK_REGULAR),
                body={**params, **{"version": 1}},
            )
        )


def test_trying_to_update_non_existing(user_factory, client):
    assert_error(
        client.put(
            "/pool-category/bad",
            user=user_factory(rank=model.User.RANK_REGULAR),
            body={"name": ["dummy"]},
        ),
        pool_categories.PoolCategoryNotFoundError,
    )


@pytest.mark.parametrize(
    "params",
    [
        {"name": "whatever"},
        {"color": "whatever"},
    ],
)
def test_trying_to_update_without_privileges(
    user_factory, pool_category_factory, client, params
):
    db.session.add(pool_category_factory(name="dummy"))
    db.session.commit()
    assert_error(
        client.put(
            "/pool-category/dummy",
            user=user_factory(rank=model.User.RANK_ANONYMOUS),
            body={**params, **{"version": 1}},
        ),
        errors.AuthError,
    )


def test_set_as_default(user_factory, pool_category_factory, client):
    category = pool_category_factory(name="name", color="black")
    db.session.add(category)
    db.session.commit()
    with (
        patch("lithica.func.pool_categories.serialize_category"),
        patch("lithica.func.pool_categories.set_default_category"),
    ):
        pool_categories.update_category_name.side_effect = _update_category_name
        pool_categories.serialize_category.return_value = "serialized category"
        result = ok(
            client.put(
                "/pool-category/name/default",
                user=user_factory(rank=model.User.RANK_REGULAR),
                body={
                    "name": "changed",
                    "color": "white",
                    "version": 1,
                },
            )
        )
        assert result == "serialized category"
        pool_categories.set_default_category.assert_called_once_with(category)
