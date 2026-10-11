from unittest.mock import patch

import pytest

from lithica import db, errors, model
from lithica.func import tags
from lithica.tests.api.http import assert_error, ok


@pytest.fixture(autouse=True)
def inject_config(config_injector):
    config_injector(
        {
            "privileges": {
                "tags:list": model.User.RANK_REGULAR,
                "tags:view": model.User.RANK_REGULAR,
            },
        }
    )


def test_retrieving_multiple(user_factory, tag_factory, client):
    tag1 = tag_factory(names=["t1"])
    tag2 = tag_factory(names=["t2"])
    db.session.add_all([tag2, tag1])
    db.session.flush()
    with patch("lithica.func.tags.serialize_tag"):
        tags.serialize_tag.return_value = "serialized tag"
        result = ok(
            client.get(
                "/tags",
                user=user_factory(rank=model.User.RANK_REGULAR),
                query={"query": "", "offset": 0},
            )
        )
        assert result == {
            "query": "",
            "offset": 0,
            "limit": 100,
            "total": 2,
            "results": ["serialized tag", "serialized tag"],
        }


def test_trying_to_retrieve_multiple_without_privileges(user_factory, client):
    assert_error(
        client.get(
            "/tags",
            user=user_factory(rank=model.User.RANK_ANONYMOUS),
            query={"query": "", "offset": 0},
        ),
        errors.AuthError,
    )


def test_retrieving_single(user_factory, tag_factory, client):
    db.session.add(tag_factory(names=["tag"]))
    db.session.flush()
    with patch("lithica.func.tags.serialize_tag"):
        tags.serialize_tag.return_value = "serialized tag"
        result = ok(
            client.get("/tag/tag", user=user_factory(rank=model.User.RANK_REGULAR))
        )
        assert result == "serialized tag"


def test_trying_to_retrieve_single_non_existing(user_factory, client):
    assert_error(
        client.get("/tag/-", user=user_factory(rank=model.User.RANK_REGULAR)),
        tags.TagNotFoundError,
    )


def test_trying_to_retrieve_single_without_privileges(user_factory, client):
    assert_error(
        client.get("/tag/-", user=user_factory(rank=model.User.RANK_ANONYMOUS)),
        errors.AuthError,
    )


def test_tag_fits_its_response_model(user_factory, tag_factory, client):
    from lithica.api import resources
    from lithica.tests.api.http import assert_fits

    category = model.TagCategory("meta")
    category.default = True
    related = tag_factory(names=["related"], category=category)
    tag = tag_factory(names=["tag", "alias"], category=category)
    tag.description = "a description"
    tag.suggestions = [related]
    tag.implications = [related]
    db.session.add_all([category, related, tag])
    db.session.flush()
    user = user_factory(rank=model.User.RANK_REGULAR)

    single = ok(client.get("/tag/alias", user=user))
    assert single["names"] == ["tag", "alias"]
    assert single["suggestions"][0]["names"] == ["related"]
    assert_fits(resources.Tag, single)

    listed = ok(client.get("/tags", user=user, query={"query": "tag"}))
    assert listed["total"] == 1
    assert_fits(resources.Paged[resources.Tag], listed)

    siblings = ok(client.get("/tag-siblings/tag", user=user))
    assert_fits(resources.Unpaged[resources.TagSibling], siblings)


@pytest.mark.parametrize(
    "name,path",
    [
        ("with/slash", "/tag/with/slash"),
        ("trailing/", "/tag/trailing/"),
        ("with space", "/tag/with%20space"),
        ("100%", "/tag/100%25"),
        ("zażółć", "/tag/za%C5%BC%C3%B3%C5%82%C4%87"),
        ("a+b", "/tag/a+b"),
    ],
)
def test_retrieving_tag_with_special_characters(
    user_factory, tag_factory, client, name, path
):
    db.session.add(tag_factory(names=[name]))
    db.session.flush()
    with patch("lithica.func.tags.serialize_tag"):
        tags.serialize_tag.return_value = "serialized tag"
        result = ok(client.get(path, user=user_factory(rank=model.User.RANK_REGULAR)))
        assert result == "serialized tag"
        assert tags.serialize_tag.call_args[0][0].names[0].name == name
