from unittest.mock import patch

import pytest

from lithica import api, db, errors, model
from lithica.func import snapshots, tag_categories


def _update_category_name(category, name):
    category.name = name


@pytest.fixture(autouse=True)
def inject_config(config_injector):
    config_injector(
        {
            "privileges": {"tag_categories:create": model.User.RANK_REGULAR},
        }
    )


def test_creating_category(tag_category_factory, user_factory, context_factory):
    auth_user = user_factory(rank=model.User.RANK_REGULAR)
    category = tag_category_factory(name="meta")
    db.session.add(category)

    with (
        patch("lithica.func.tag_categories.create_category"),
        patch("lithica.func.tag_categories.serialize_category"),
        patch("lithica.func.tag_categories.update_category_name"),
        patch("lithica.func.snapshots.create"),
    ):
        tag_categories.create_category.return_value = category
        tag_categories.update_category_name.side_effect = _update_category_name
        tag_categories.serialize_category.return_value = "serialized category"
        result = api.tag_category_api.create_tag_category(
            context_factory(
                params={"name": "meta", "color": "black", "order": 0},
                user=auth_user,
            )
        )
        assert result == "serialized category"
        tag_categories.create_category.assert_called_once_with("meta", "black", 0)
        snapshots.create.assert_called_once_with(category, auth_user)


@pytest.mark.parametrize("field", ["name", "color"])
def test_trying_to_omit_mandatory_field(user_factory, context_factory, field):
    params = {
        "name": "meta",
        "color": "black",
    }
    del params[field]
    with pytest.raises(errors.ValidationError):
        api.tag_category_api.create_tag_category(
            context_factory(
                params=params, user=user_factory(rank=model.User.RANK_REGULAR)
            )
        )


def test_trying_to_create_without_privileges(user_factory, context_factory):
    with pytest.raises(errors.AuthError):
        api.tag_category_api.create_tag_category(
            context_factory(
                params={"name": "meta", "color": "black"},
                user=user_factory(rank=model.User.RANK_ANONYMOUS),
            )
        )
