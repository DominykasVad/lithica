from unittest.mock import patch

import pytest

from lithica import db, errors, model
from lithica.func import net, posts, snapshots
from lithica.tests.api.http import assert_error, ok


@pytest.fixture(autouse=True)
def inject_config(config_injector):
    config_injector(
        {
            "privileges": {
                "posts:create:anonymous": model.User.RANK_REGULAR,
                "posts:create:identified": model.User.RANK_REGULAR,
                "tags:create": model.User.RANK_REGULAR,
                "uploads:use_downloader": model.User.RANK_REGULAR,
            },
            "allow_broken_uploads": False,
        }
    )


def test_creating_minimal_posts(client, post_factory, user_factory):
    auth_user = user_factory(rank=model.User.RANK_REGULAR)
    post = post_factory()
    db.session.add(post)
    db.session.flush()

    with (
        patch("lithica.func.posts.create_post"),
        patch("lithica.func.posts.update_post_safety"),
        patch("lithica.func.posts.update_post_source"),
        patch("lithica.func.posts.update_post_relations"),
        patch("lithica.func.posts.update_post_notes"),
        patch("lithica.func.posts.update_post_flags"),
        patch("lithica.func.posts.update_post_thumbnail"),
        patch("lithica.func.posts.serialize_post"),
        patch("lithica.func.snapshots.create"),
    ):
        posts.create_post.return_value = (post, [])
        posts.serialize_post.return_value = "serialized post"

        result = ok(
            client.post(
                "/posts",
                user=auth_user,
                body={
                    "safety": "safe",
                    "tags": ["tag1", "tag2"],
                },
                files={
                    "content": b"post-content",
                    "thumbnail": b"post-thumbnail",
                },
            )
        )

        assert result == "serialized post"
        posts.create_post.assert_called_once_with(
            b"post-content", ["tag1", "tag2"], auth_user
        )
        posts.update_post_thumbnail.assert_called_once_with(post, b"post-thumbnail")
        posts.update_post_safety.assert_called_once_with(post, "safe")
        posts.update_post_source.assert_called_once_with(post, "")
        posts.update_post_relations.assert_called_once_with(post, [])
        posts.update_post_notes.assert_called_once_with(post, [])
        posts.update_post_flags.assert_called_once_with(post, [])
        posts.update_post_thumbnail.assert_called_once_with(post, b"post-thumbnail")
        posts.serialize_post.assert_called_once_with(post, auth_user, options=[])
        snapshots.create.assert_called_once_with(post, auth_user)


def test_creating_full_posts(client, post_factory, user_factory):
    auth_user = user_factory(rank=model.User.RANK_REGULAR)
    post = post_factory()
    db.session.add(post)
    db.session.flush()

    with (
        patch("lithica.func.posts.create_post"),
        patch("lithica.func.posts.update_post_safety"),
        patch("lithica.func.posts.update_post_source"),
        patch("lithica.func.posts.update_post_relations"),
        patch("lithica.func.posts.update_post_notes"),
        patch("lithica.func.posts.update_post_flags"),
        patch("lithica.func.posts.serialize_post"),
        patch("lithica.func.snapshots.create"),
    ):
        posts.create_post.return_value = (post, [])
        posts.serialize_post.return_value = "serialized post"

        result = ok(
            client.post(
                "/posts",
                user=auth_user,
                body={
                    "safety": "safe",
                    "tags": ["tag1", "tag2"],
                    "relations": [1, 2],
                    "source": "source",
                    "notes": ["note1", "note2"],
                    "flags": ["flag1", "flag2"],
                },
                files={
                    "content": b"post-content",
                },
            )
        )

        assert result == "serialized post"
        posts.create_post.assert_called_once_with(
            b"post-content", ["tag1", "tag2"], auth_user
        )
        posts.update_post_safety.assert_called_once_with(post, "safe")
        posts.update_post_source.assert_called_once_with(post, "source")
        posts.update_post_relations.assert_called_once_with(post, [1, 2])
        posts.update_post_notes.assert_called_once_with(post, ["note1", "note2"])
        posts.update_post_flags.assert_called_once_with(post, ["flag1", "flag2"])
        posts.serialize_post.assert_called_once_with(post, auth_user, options=[])
        snapshots.create.assert_called_once_with(post, auth_user)


def test_anonymous_uploads(config_injector, client, post_factory, user_factory):
    auth_user = user_factory(rank=model.User.RANK_REGULAR)
    post = post_factory()
    db.session.add(post)
    db.session.flush()

    with (
        patch("lithica.func.posts.serialize_post"),
        patch("lithica.func.posts.create_post"),
        patch("lithica.func.posts.update_post_source"),
        patch("lithica.func.snapshots._post_to_webhooks"),
    ):
        config_injector(
            {
                "privileges": {
                    "posts:create:anonymous": model.User.RANK_REGULAR,
                    "uploads:use_downloader": model.User.RANK_POWER,
                },
            }
        )
        posts.create_post.return_value = [post, []]
        ok(
            client.post(
                "/posts",
                user=auth_user,
                body={
                    "safety": "safe",
                    "tags": ["tag1", "tag2"],
                    "anonymous": "True",
                },
                files={
                    "content": b"post-content",
                },
            )
        )
        posts.create_post.assert_called_once_with(
            b"post-content", ["tag1", "tag2"], None
        )


def test_creating_from_url_saves_source(
    config_injector, client, post_factory, user_factory
):
    auth_user = user_factory(rank=model.User.RANK_REGULAR)
    post = post_factory()
    db.session.add(post)
    db.session.flush()

    with (
        patch("lithica.func.net.download"),
        patch("lithica.func.posts.serialize_post"),
        patch("lithica.func.posts.create_post"),
        patch("lithica.func.posts.update_post_source"),
        patch("lithica.func.snapshots._post_to_webhooks"),
    ):
        config_injector(
            {
                "privileges": {
                    "posts:create:identified": model.User.RANK_REGULAR,
                    "uploads:use_downloader": model.User.RANK_POWER,
                },
            }
        )
        net.download.return_value = b"content"
        posts.create_post.return_value = [post, []]
        ok(
            client.post(
                "/posts",
                user=auth_user,
                body={
                    "safety": "safe",
                    "tags": ["tag1", "tag2"],
                    "contentUrl": "example.com",
                },
            )
        )
        net.download.assert_called_once_with("example.com", use_video_downloader=False)
        posts.create_post.assert_called_once_with(
            b"content", ["tag1", "tag2"], auth_user
        )
        posts.update_post_source.assert_called_once_with(post, "example.com")


def test_creating_from_url_with_source_specified(
    config_injector, client, post_factory, user_factory
):
    auth_user = user_factory(rank=model.User.RANK_REGULAR)
    post = post_factory()
    db.session.add(post)
    db.session.flush()

    with (
        patch("lithica.func.net.download"),
        patch("lithica.func.posts.serialize_post"),
        patch("lithica.func.posts.create_post"),
        patch("lithica.func.posts.update_post_source"),
        patch("lithica.func.snapshots._post_to_webhooks"),
    ):
        config_injector(
            {
                "privileges": {
                    "posts:create:identified": model.User.RANK_REGULAR,
                    "uploads:use_downloader": model.User.RANK_REGULAR,
                },
            }
        )
        net.download.return_value = b"content"
        posts.create_post.return_value = [post, []]
        ok(
            client.post(
                "/posts",
                user=auth_user,
                body={
                    "safety": "safe",
                    "tags": ["tag1", "tag2"],
                    "contentUrl": "example.com",
                    "source": "example2.com",
                },
            )
        )
        net.download.assert_called_once_with("example.com", use_video_downloader=True)
        posts.create_post.assert_called_once_with(
            b"content", ["tag1", "tag2"], auth_user
        )
        posts.update_post_source.assert_called_once_with(post, "example2.com")


@pytest.mark.parametrize("field", ["safety"])
def test_trying_to_omit_mandatory_field(client, user_factory, field):
    params = {
        "safety": "safe",
    }
    del params[field]
    assert_error(
        client.post(
            "/posts",
            user=user_factory(rank=model.User.RANK_REGULAR),
            body=params,
            files={"content": "..."},
        ),
        errors.MissingRequiredParameterError,
    )


@pytest.mark.parametrize("field", ["tags", "relations", "source", "notes", "flags"])
def test_omitting_optional_field(field, client, post_factory, user_factory):
    auth_user = user_factory(rank=model.User.RANK_REGULAR)
    post = post_factory()
    db.session.add(post)
    db.session.flush()
    params = {
        "safety": "safe",
        "tags": ["tag1", "tag2"],
        "relations": [1, 2],
        "source": "source",
        "notes": ["note1", "note2"],
        "flags": ["flag1", "flag2"],
    }
    del params[field]
    with (
        patch("lithica.func.posts.create_post"),
        patch("lithica.func.posts.update_post_safety"),
        patch("lithica.func.posts.update_post_source"),
        patch("lithica.func.posts.update_post_relations"),
        patch("lithica.func.posts.update_post_notes"),
        patch("lithica.func.posts.update_post_flags"),
        patch("lithica.func.posts.serialize_post"),
        patch("lithica.func.snapshots.create"),
    ):
        posts.create_post.return_value = (post, [])
        posts.serialize_post.return_value = "serialized post"
        result = ok(
            client.post(
                "/posts",
                user=auth_user,
                body=params,
                files={"content": b"post-content"},
            )
        )
        assert result == "serialized post"


def test_errors_not_spending_ids(
    config_injector, tmpdir, client, read_asset, user_factory
):
    config_injector(
        {
            "data_dir": str(tmpdir.mkdir("data")),
            "data_url": "example.com",
            "thumbnails": {
                "post_width": 300,
                "post_height": 300,
            },
            "privileges": {
                "posts:create:identified": model.User.RANK_REGULAR,
                "uploads:use_downloader": model.User.RANK_POWER,
            },
            "secret": "test",
        }
    )
    auth_user = user_factory(rank=model.User.RANK_REGULAR)

    # successful request
    with (
        patch("lithica.func.posts.serialize_post"),
        patch("lithica.func.posts.update_post_tags"),
        patch("lithica.func.snapshots._post_to_webhooks"),
    ):
        posts.serialize_post.side_effect = lambda post, *_, **__: post.post_id
        post1_id = ok(
            client.post(
                "/posts",
                user=auth_user,
                body={"safety": "safe", "tags": []},
                files={"content": read_asset("png.png")},
            )
        )
    assert_error(
        client.post(
            "/posts",
            user=auth_user,
            body={"safety": "safe", "tags": []},
            files={"content": read_asset("png.png")},
        ),
        posts.PostAlreadyUploadedError,
    )

    # successful request
    with (
        patch("lithica.func.posts.serialize_post"),
        patch("lithica.func.posts.update_post_tags"),
        patch("lithica.func.snapshots._post_to_webhooks"),
    ):
        posts.serialize_post.side_effect = lambda post, *_, **__: post.post_id
        post2_id = ok(
            client.post(
                "/posts",
                user=auth_user,
                body={"safety": "safe", "tags": []},
                files={"content": read_asset("jpeg.jpg")},
            )
        )

    # serialize_post is mocked to return the post id
    assert isinstance(post1_id, int)
    assert isinstance(post2_id, int)
    assert post1_id > 0
    assert post2_id > 0
    assert post2_id == post1_id + 1


def test_trying_to_omit_content(client, user_factory):
    assert_error(
        client.post(
            "/posts",
            user=user_factory(rank=model.User.RANK_REGULAR),
            body={
                "safety": "safe",
                "tags": ["tag1", "tag2"],
            },
        ),
        errors.MissingRequiredFileError,
    )


def test_trying_to_create_post_without_privileges(client, user_factory):
    assert_error(
        client.post("/posts", user=user_factory(rank=model.User.RANK_ANONYMOUS)),
        errors.AuthError,
    )


def test_trying_to_create_tags_without_privileges(
    config_injector, client, user_factory
):
    config_injector(
        {
            "privileges": {
                "posts:create:anonymous": model.User.RANK_REGULAR,
                "posts:create:identified": model.User.RANK_REGULAR,
                "tags:create": model.User.RANK_ADMINISTRATOR,
                "uploads:use_downloader": model.User.RANK_POWER,
            },
        }
    )
    with (
        patch("lithica.func.posts.update_post_content"),
        patch("lithica.func.posts.update_post_tags"),
    ):
        posts.update_post_tags.return_value = ["new-tag"]
        assert_error(
            client.post(
                "/posts",
                user=user_factory(rank=model.User.RANK_REGULAR),
                body={
                    "safety": "safe",
                    "tags": ["tag1", "tag2"],
                },
                files={
                    "content": posts.EMPTY_PIXEL,
                },
            ),
            errors.AuthError,
        )
