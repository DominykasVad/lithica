from unittest.mock import patch

import pytest

from lithica import db, errors, model
from lithica.func import snapshots, tag_categories
from lithica.tests.api.http import assert_error, ok


def _update_category_name(category, name):
    category.name = name


@pytest.fixture(autouse=True)
def inject_config(config_injector):
    config_injector(
        {
            "privileges": {
                "tag_categories:edit:name": model.User.RANK_REGULAR,
                "tag_categories:edit:color": model.User.RANK_REGULAR,
                "tag_categories:edit:order": model.User.RANK_REGULAR,
                "tag_categories:set_default": model.User.RANK_REGULAR,
            },
        }
    )


def test_simple_updating(user_factory, tag_category_factory, client):
    auth_user = user_factory(rank=model.User.RANK_REGULAR)
    category = tag_category_factory(name="name", color="black")
    db.session.add(category)
    db.session.flush()
    with (
        patch("lithica.func.tag_categories.serialize_category"),
        patch("lithica.func.tag_categories.update_category_name"),
        patch("lithica.func.tag_categories.update_category_color"),
        patch("lithica.func.snapshots.modify"),
    ):
        tag_categories.update_category_name.side_effect = _update_category_name
        tag_categories.serialize_category.return_value = "serialized category"
        result = ok(
            client.put(
                "/tag-category/name",
                user=auth_user,
                body={"name": "changed", "color": "white", "version": 1},
            )
        )
        assert result == "serialized category"
        tag_categories.update_category_name.assert_called_once_with(category, "changed")
        tag_categories.update_category_color.assert_called_once_with(category, "white")
        snapshots.modify.assert_called_once_with(category, auth_user)


@pytest.mark.parametrize("field", ["name", "color"])
def test_omitting_optional_field(user_factory, tag_category_factory, client, field):
    db.session.add(tag_category_factory(name="name", color="black"))
    db.session.commit()
    params = {
        "name": "changed",
        "color": "white",
    }
    del params[field]
    with (
        patch("lithica.func.tag_categories.serialize_category"),
        patch("lithica.func.tag_categories.update_category_name"),
        patch("lithica.func.snapshots._post_to_webhooks"),
    ):
        ok(
            client.put(
                "/tag-category/name",
                user=user_factory(rank=model.User.RANK_REGULAR),
                body={**params, **{"version": 1}},
            )
        )


def test_trying_to_update_non_existing(user_factory, client):
    assert_error(
        client.put(
            "/tag-category/bad",
            user=user_factory(rank=model.User.RANK_REGULAR),
            body={"name": ["dummy"]},
        ),
        tag_categories.TagCategoryNotFoundError,
    )


@pytest.mark.parametrize(
    "params",
    [
        {"name": "whatever"},
        {"color": "whatever"},
    ],
)
def test_trying_to_update_without_privileges(
    user_factory, tag_category_factory, client, params
):
    db.session.add(tag_category_factory(name="dummy"))
    db.session.commit()
    assert_error(
        client.put(
            "/tag-category/dummy",
            user=user_factory(rank=model.User.RANK_ANONYMOUS),
            body={**params, **{"version": 1}},
        ),
        errors.AuthError,
    )


def test_set_as_default(user_factory, tag_category_factory, client):
    category = tag_category_factory(name="name", color="black")
    db.session.add(category)
    db.session.commit()
    with (
        patch("lithica.func.tag_categories.serialize_category"),
        patch("lithica.func.tag_categories.set_default_category"),
    ):
        tag_categories.update_category_name.side_effect = _update_category_name
        tag_categories.serialize_category.return_value = "serialized category"
        result = ok(
            client.put(
                "/tag-category/name/default",
                user=user_factory(rank=model.User.RANK_REGULAR),
                body={
                    "name": "changed",
                    "color": "white",
                    "version": 1,
                },
            )
        )
        assert result == "serialized category"
        tag_categories.set_default_category.assert_called_once_with(category)
