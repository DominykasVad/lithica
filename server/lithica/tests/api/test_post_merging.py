from unittest.mock import patch

import pytest

from lithica import db, errors, model
from lithica.func import posts, snapshots
from lithica.tests.api.http import assert_error, ok


@pytest.fixture(autouse=True)
def inject_config(config_injector):
    config_injector({"privileges": {"posts:merge": model.User.RANK_REGULAR}})


def test_merging(user_factory, client, post_factory):
    auth_user = user_factory(rank=model.User.RANK_REGULAR)
    source_post = post_factory()
    target_post = post_factory()
    db.session.add_all([source_post, target_post])
    db.session.flush()
    with (
        patch("lithica.func.posts.serialize_post"),
        patch("lithica.func.posts.merge_posts"),
        patch("lithica.func.snapshots.merge"),
    ):
        ok(
            client.post(
                "/post-merge",
                user=auth_user,
                body={
                    "removeVersion": 1,
                    "mergeToVersion": 1,
                    "remove": source_post.post_id,
                    "mergeTo": target_post.post_id,
                    "replaceContent": False,
                },
            )
        )
        posts.merge_posts.assert_called_once_with(source_post, target_post, False)
        snapshots.merge.assert_called_once_with(source_post, target_post, auth_user)


@pytest.mark.parametrize(
    "field", ["remove", "mergeTo", "removeVersion", "mergeToVersion"]
)
def test_trying_to_omit_mandatory_field(user_factory, post_factory, client, field):
    source_post = post_factory()
    target_post = post_factory()
    db.session.add_all([source_post, target_post])
    db.session.commit()
    params = {
        "removeVersion": 1,
        "mergeToVersion": 1,
        "remove": source_post.post_id,
        "mergeTo": target_post.post_id,
        "replaceContent": False,
    }
    del params[field]
    assert_error(
        client.post(
            "/post-merge", user=user_factory(rank=model.User.RANK_REGULAR), body=params
        ),
        errors.ValidationError,
    )


def test_trying_to_merge_non_existing(user_factory, post_factory, client):
    post = post_factory()
    db.session.add(post)
    db.session.commit()
    assert_error(
        client.post(
            "/post-merge",
            user=user_factory(rank=model.User.RANK_REGULAR),
            body={"remove": post.post_id, "mergeTo": 999},
        ),
        posts.PostNotFoundError,
    )
    assert_error(
        client.post(
            "/post-merge",
            user=user_factory(rank=model.User.RANK_REGULAR),
            body={"remove": 999, "mergeTo": post.post_id},
        ),
        posts.PostNotFoundError,
    )


def test_trying_to_merge_without_privileges(user_factory, post_factory, client):
    source_post = post_factory()
    target_post = post_factory()
    db.session.add_all([source_post, target_post])
    db.session.commit()
    assert_error(
        client.post(
            "/post-merge",
            user=user_factory(rank=model.User.RANK_ANONYMOUS),
            body={
                "removeVersion": 1,
                "mergeToVersion": 1,
                "remove": source_post.post_id,
                "mergeTo": target_post.post_id,
                "replaceContent": False,
            },
        ),
        errors.AuthError,
    )
