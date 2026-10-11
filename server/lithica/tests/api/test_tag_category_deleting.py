from unittest.mock import patch

import pytest

from lithica import db, errors, model
from lithica.func import snapshots, tag_categories
from lithica.tests.api.http import assert_error, ok


@pytest.fixture(autouse=True)
def inject_config(config_injector):
    config_injector(
        {
            "privileges": {"tag_categories:delete": model.User.RANK_REGULAR},
        }
    )


def test_deleting(user_factory, tag_category_factory, client):
    auth_user = user_factory(rank=model.User.RANK_REGULAR)
    category = tag_category_factory(name="category")
    db.session.add(tag_category_factory(name="root"))
    db.session.add(category)
    db.session.flush()
    with patch("lithica.func.snapshots.delete"):
        result = ok(
            client.delete("/tag-category/category", user=auth_user, body={"version": 1})
        )
        assert result == {}
        assert db.session.query(model.TagCategory).count() == 1
        assert db.session.query(model.TagCategory).one().name == "root"
        snapshots.delete.assert_called_once_with(category, auth_user)


def test_trying_to_delete_used(user_factory, tag_category_factory, tag_factory, client):
    category = tag_category_factory(name="category")
    db.session.add(category)
    db.session.flush()
    tag = tag_factory(names=["tag"], category=category)
    db.session.add(tag)
    db.session.commit()
    assert_error(
        client.delete(
            "/tag-category/category",
            user=user_factory(rank=model.User.RANK_REGULAR),
            body={"version": 1},
        ),
        tag_categories.TagCategoryIsInUseError,
    )
    assert db.session.query(model.TagCategory).count() == 1


def test_trying_to_delete_last(user_factory, tag_category_factory, client):
    db.session.add(tag_category_factory(name="root"))
    db.session.commit()
    assert_error(
        client.delete(
            "/tag-category/root",
            user=user_factory(rank=model.User.RANK_REGULAR),
            body={"version": 1},
        ),
        tag_categories.TagCategoryIsInUseError,
    )


def test_trying_to_delete_non_existing(user_factory, client):
    assert_error(
        client.delete(
            "/tag-category/bad", user=user_factory(rank=model.User.RANK_REGULAR)
        ),
        tag_categories.TagCategoryNotFoundError,
    )


def test_trying_to_delete_without_privileges(
    user_factory, tag_category_factory, client
):
    db.session.add(tag_category_factory(name="category"))
    db.session.commit()
    assert_error(
        client.delete(
            "/tag-category/category",
            user=user_factory(rank=model.User.RANK_ANONYMOUS),
            body={"version": 1},
        ),
        errors.AuthError,
    )
    assert db.session.query(model.TagCategory).count() == 1
