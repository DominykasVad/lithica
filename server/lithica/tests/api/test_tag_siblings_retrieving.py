from unittest.mock import patch

import pytest

from lithica import db, errors, model
from lithica.func import tags
from lithica.tests.api.http import assert_error, ok


@pytest.fixture(autouse=True)
def inject_config(config_injector):
    config_injector({"privileges": {"tags:view": model.User.RANK_REGULAR}})


def test_get_tag_siblings(user_factory, tag_factory, client):
    db.session.add(tag_factory(names=["tag"]))
    db.session.flush()
    with (
        patch("lithica.func.tags.serialize_tag"),
        patch("lithica.func.tags.get_tag_siblings"),
    ):
        tags.serialize_tag.side_effect = lambda tag, *args, **kwargs: (
            "serialized tag %s" % tag.names[0].name
        )
        tags.get_tag_siblings.return_value = [
            (tag_factory(names=["sib1"]), 1),
            (tag_factory(names=["sib2"]), 3),
        ]
        result = ok(
            client.get(
                "/tag-siblings/tag", user=user_factory(rank=model.User.RANK_REGULAR)
            )
        )
        assert result == {
            "results": [
                {
                    "tag": "serialized tag sib1",
                    "occurrences": 1,
                },
                {
                    "tag": "serialized tag sib2",
                    "occurrences": 3,
                },
            ],
        }


def test_trying_to_retrieve_non_existing(user_factory, client):
    assert_error(
        client.get("/tag-siblings/-", user=user_factory(rank=model.User.RANK_REGULAR)),
        tags.TagNotFoundError,
    )


def test_trying_to_retrieve_without_privileges(user_factory, client):
    assert_error(
        client.get(
            "/tag-siblings/-", user=user_factory(rank=model.User.RANK_ANONYMOUS)
        ),
        errors.AuthError,
    )
