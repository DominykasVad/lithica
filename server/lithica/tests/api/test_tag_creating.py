from unittest.mock import patch

import pytest

from lithica import errors, model
from lithica.func import snapshots, tags
from lithica.tests.api.http import assert_error, ok


@pytest.fixture(autouse=True)
def inject_config(config_injector):
    config_injector({"privileges": {"tags:create": model.User.RANK_REGULAR}})


def test_creating_simple_tags(tag_factory, user_factory, client):
    auth_user = user_factory(rank=model.User.RANK_REGULAR)
    tag = tag_factory()
    with (
        patch("lithica.func.tags.create_tag"),
        patch("lithica.func.tags.get_or_create_tags_by_names"),
        patch("lithica.func.tags.serialize_tag"),
        patch("lithica.func.snapshots.create"),
    ):
        tags.get_or_create_tags_by_names.return_value = ([], [])
        tags.create_tag.return_value = tag
        tags.serialize_tag.return_value = "serialized tag"
        result = ok(
            client.post(
                "/tags",
                user=auth_user,
                body={
                    "names": ["tag1", "tag2"],
                    "category": "meta",
                    "description": "desc",
                    "suggestions": ["sug1", "sug2"],
                    "implications": ["imp1", "imp2"],
                },
            )
        )
        assert result == "serialized tag"
        tags.create_tag.assert_called_once_with(
            ["tag1", "tag2"], "meta", ["sug1", "sug2"], ["imp1", "imp2"]
        )
        snapshots.create.assert_called_once_with(tag, auth_user)


@pytest.mark.parametrize("field", ["names", "category"])
def test_trying_to_omit_mandatory_field(user_factory, client, field):
    params = {
        "names": ["tag1", "tag2"],
        "category": "meta",
        "suggestions": [],
        "implications": [],
    }
    del params[field]
    assert_error(
        client.post(
            "/tags", user=user_factory(rank=model.User.RANK_REGULAR), body=params
        ),
        errors.ValidationError,
    )


@pytest.mark.parametrize("field", ["implications", "suggestions"])
def test_omitting_optional_field(tag_factory, user_factory, client, field):
    params = {
        "names": ["tag1", "tag2"],
        "category": "meta",
        "suggestions": [],
        "implications": [],
    }
    del params[field]
    with (
        patch("lithica.func.tags.create_tag"),
        patch("lithica.func.tags.serialize_tag"),
        patch("lithica.func.snapshots._post_to_webhooks"),
    ):
        tags.create_tag.return_value = tag_factory()
        ok(
            client.post(
                "/tags", user=user_factory(rank=model.User.RANK_REGULAR), body=params
            )
        )


def test_trying_to_create_tag_without_privileges(user_factory, client):
    assert_error(
        client.post(
            "/tags",
            user=user_factory(rank=model.User.RANK_ANONYMOUS),
            body={
                "names": ["tag"],
                "category": "meta",
                "suggestions": ["tag"],
                "implications": [],
            },
        ),
        errors.AuthError,
    )
