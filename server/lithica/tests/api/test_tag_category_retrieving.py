import pytest

from lithica import db, errors, model
from lithica.func import tag_categories
from lithica.tests.api.http import assert_error, ok


@pytest.fixture(autouse=True)
def inject_config(config_injector):
    config_injector(
        {
            "privileges": {
                "tag_categories:list": model.User.RANK_REGULAR,
                "tag_categories:view": model.User.RANK_REGULAR,
            },
        }
    )


def test_retrieving_multiple(user_factory, tag_category_factory, client):
    db.session.add_all(
        [
            tag_category_factory(name="c1"),
            tag_category_factory(name="c2"),
        ]
    )
    db.session.flush()
    result = ok(
        client.get("/tag-categories", user=user_factory(rank=model.User.RANK_REGULAR))
    )
    assert result is not None
    assert [cat["name"] for cat in result["results"]] == ["c1", "c2"]


def test_retrieving_single(user_factory, tag_category_factory, client):
    db.session.add(tag_category_factory(name="cat"))
    db.session.flush()
    result = ok(
        client.get("/tag-category/cat", user=user_factory(rank=model.User.RANK_REGULAR))
    )
    assert result == {
        "name": "cat",
        "color": "dummy",
        "usages": 0,
        "default": False,
        "order": 1,
        "version": 1,
    }


def test_trying_to_retrieve_single_non_existing(user_factory, client):
    assert_error(
        client.get("/tag-category/-", user=user_factory(rank=model.User.RANK_REGULAR)),
        tag_categories.TagCategoryNotFoundError,
    )


def test_trying_to_retrieve_single_without_privileges(user_factory, client):
    assert_error(
        client.get(
            "/tag-category/-", user=user_factory(rank=model.User.RANK_ANONYMOUS)
        ),
        errors.AuthError,
    )


def test_tag_category_fits_its_response_model(user_factory, tag_factory, client):
    from lithica.api import resources
    from lithica.tests.api.http import assert_fits

    category = model.TagCategory("meta")
    category.default = True
    db.session.add_all([category, tag_factory(category=category)])
    db.session.flush()
    user = user_factory(rank=model.User.RANK_REGULAR)

    single = ok(client.get("/tag-category/meta", user=user))
    assert single["usages"] == 1
    assert single["default"] is True
    assert_fits(resources.TagCategory, single)

    listed = ok(client.get("/tag-categories", user=user))
    assert_fits(resources.Unpaged[resources.TagCategory], listed)
