from unittest.mock import patch

import pytest

from lithica import db, errors, model
from lithica.func import snapshots, tags
from lithica.tests.api.http import assert_error, ok


@pytest.fixture(autouse=True)
def inject_config(config_injector):
    config_injector(
        {
            "privileges": {
                "tags:create": model.User.RANK_REGULAR,
                "tags:edit:names": model.User.RANK_REGULAR,
                "tags:edit:category": model.User.RANK_REGULAR,
                "tags:edit:description": model.User.RANK_REGULAR,
                "tags:edit:suggestions": model.User.RANK_REGULAR,
                "tags:edit:implications": model.User.RANK_REGULAR,
            },
        }
    )


def test_simple_updating(user_factory, tag_factory, client):
    auth_user = user_factory(rank=model.User.RANK_REGULAR)
    tag = tag_factory(names=["tag1", "tag2"])
    db.session.add(tag)
    db.session.commit()
    with (
        patch("lithica.func.tags.create_tag"),
        patch("lithica.func.tags.get_or_create_tags_by_names"),
        patch("lithica.func.tags.update_tag_names"),
        patch("lithica.func.tags.update_tag_category_name"),
        patch("lithica.func.tags.update_tag_description"),
        patch("lithica.func.tags.update_tag_suggestions"),
        patch("lithica.func.tags.update_tag_implications"),
        patch("lithica.func.tags.serialize_tag"),
        patch("lithica.func.snapshots.modify"),
    ):
        tags.get_or_create_tags_by_names.return_value = ([], [])
        tags.serialize_tag.return_value = "serialized tag"
        result = ok(
            client.put(
                "/tag/tag1",
                user=auth_user,
                body={
                    "version": 1,
                    "names": ["tag3"],
                    "category": "character",
                    "description": "desc",
                    "suggestions": ["sug1", "sug2"],
                    "implications": ["imp1", "imp2"],
                },
            )
        )
        assert result == "serialized tag"
        tags.create_tag.assert_not_called()
        tags.update_tag_names.assert_called_once_with(tag, ["tag3"])
        tags.update_tag_category_name.assert_called_once_with(tag, "character")
        tags.update_tag_description.assert_called_once_with(tag, "desc")
        tags.update_tag_suggestions.assert_called_once_with(tag, ["sug1", "sug2"])
        tags.update_tag_implications.assert_called_once_with(tag, ["imp1", "imp2"])
        tags.serialize_tag.assert_called_once_with(tag, options=[])
        snapshots.modify.assert_called_once_with(tag, auth_user)


@pytest.mark.parametrize(
    "field",
    [
        "names",
        "category",
        "description",
        "implications",
        "suggestions",
    ],
)
def test_omitting_optional_field(user_factory, tag_factory, client, field):
    db.session.add(tag_factory(names=["tag"]))
    db.session.commit()
    params = {
        "names": ["tag1", "tag2"],
        "category": "meta",
        "description": "desc",
        "suggestions": [],
        "implications": [],
    }
    del params[field]
    with (
        patch("lithica.func.tags.create_tag"),
        patch("lithica.func.tags.update_tag_names"),
        patch("lithica.func.tags.update_tag_category_name"),
        patch("lithica.func.tags.serialize_tag"),
    ):
        ok(
            client.put(
                "/tag/tag",
                user=user_factory(rank=model.User.RANK_REGULAR),
                body={**params, **{"version": 1}},
            )
        )


def test_trying_to_update_non_existing(user_factory, client):
    assert_error(
        client.put(
            "/tag/tag1",
            user=user_factory(rank=model.User.RANK_REGULAR),
            body={"names": ["dummy"]},
        ),
        tags.TagNotFoundError,
    )


@pytest.mark.parametrize(
    "params",
    [
        {"names": "whatever"},
        {"category": "whatever"},
        {"suggestions": ["whatever"]},
        {"implications": ["whatever"]},
    ],
)
def test_trying_to_update_without_privileges(user_factory, tag_factory, client, params):
    db.session.add(tag_factory(names=["tag"]))
    db.session.commit()
    assert_error(
        client.put(
            "/tag/tag",
            user=user_factory(rank=model.User.RANK_ANONYMOUS),
            body={**params, **{"version": 1}},
        ),
        errors.AuthError,
    )


@pytest.mark.parametrize("type", ["suggestions", "implications"])
def test_trying_to_create_tags_without_privileges(
    config_injector, client, tag_factory, user_factory, type
):
    tag = tag_factory(names=["tag"])
    db.session.add(tag)
    db.session.commit()
    config_injector(
        {
            "privileges": {
                "tags:create": model.User.RANK_ADMINISTRATOR,
                "tags:edit:suggestions": model.User.RANK_REGULAR,
                "tags:edit:implications": model.User.RANK_REGULAR,
            }
        }
    )
    with patch("lithica.func.tags.get_or_create_tags_by_names"):
        tags.get_or_create_tags_by_names.return_value = ([], ["new-tag"])
        assert_error(
            client.put(
                "/tag/tag",
                user=user_factory(rank=model.User.RANK_REGULAR),
                body={type: ["tag1", "tag2"], "version": 1},
            ),
            errors.AuthError,
        )
