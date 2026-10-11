from unittest.mock import patch

import pytest

from lithica import db, errors, model
from lithica.func import snapshots, tags
from lithica.tests.api.http import assert_error, ok


@pytest.fixture(autouse=True)
def inject_config(config_injector):
    config_injector({"privileges": {"tags:merge": model.User.RANK_REGULAR}})


def test_merging(user_factory, tag_factory, client, post_factory):
    auth_user = user_factory(rank=model.User.RANK_REGULAR)
    source_tag = tag_factory(names=["source"])
    target_tag = tag_factory(names=["target"])
    db.session.add_all([source_tag, target_tag])
    db.session.flush()
    assert source_tag.post_count == 0
    assert target_tag.post_count == 0
    post = post_factory()
    post.tags = [source_tag]
    db.session.add(post)
    db.session.commit()
    assert source_tag.post_count == 1
    assert target_tag.post_count == 0
    with (
        patch("lithica.func.tags.serialize_tag"),
        patch("lithica.func.tags.merge_tags"),
        patch("lithica.func.snapshots.merge"),
    ):
        ok(
            client.post(
                "/tag-merge",
                user=auth_user,
                body={
                    "removeVersion": 1,
                    "mergeToVersion": 1,
                    "remove": "source",
                    "mergeTo": "target",
                },
            )
        )
        tags.merge_tags.assert_called_once_with(source_tag, target_tag)
        snapshots.merge.assert_called_once_with(source_tag, target_tag, auth_user)


@pytest.mark.parametrize(
    "field", ["remove", "mergeTo", "removeVersion", "mergeToVersion"]
)
def test_trying_to_omit_mandatory_field(user_factory, tag_factory, client, field):
    db.session.add_all(
        [
            tag_factory(names=["source"]),
            tag_factory(names=["target"]),
        ]
    )
    db.session.commit()
    params = {
        "removeVersion": 1,
        "mergeToVersion": 1,
        "remove": "source",
        "mergeTo": "target",
    }
    del params[field]
    assert_error(
        client.post(
            "/tag-merge", user=user_factory(rank=model.User.RANK_REGULAR), body=params
        ),
        errors.ValidationError,
    )


def test_trying_to_merge_non_existing(user_factory, tag_factory, client):
    db.session.add(tag_factory(names=["good"]))
    db.session.commit()
    assert_error(
        client.post(
            "/tag-merge",
            user=user_factory(rank=model.User.RANK_REGULAR),
            body={"remove": "good", "mergeTo": "bad"},
        ),
        tags.TagNotFoundError,
    )
    assert_error(
        client.post(
            "/tag-merge",
            user=user_factory(rank=model.User.RANK_REGULAR),
            body={"remove": "bad", "mergeTo": "good"},
        ),
        tags.TagNotFoundError,
    )


def test_trying_to_merge_without_privileges(user_factory, tag_factory, client):
    db.session.add_all(
        [
            tag_factory(names=["source"]),
            tag_factory(names=["target"]),
        ]
    )
    db.session.commit()
    assert_error(
        client.post(
            "/tag-merge",
            user=user_factory(rank=model.User.RANK_ANONYMOUS),
            body={
                "removeVersion": 1,
                "mergeToVersion": 1,
                "remove": "source",
                "mergeTo": "target",
            },
        ),
        errors.AuthError,
    )
