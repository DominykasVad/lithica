"""Related media imports validate first and keep file writes transactional."""

import base64
from pathlib import Path
from unittest.mock import patch

import pytest

from lithica import config, db, errors, model
from lithica.func import documents, posts, util
from lithica.modules.cards import media
from lithica.tests.api.http import assert_error, ok
from lithica.tests.api.test_tokens import _app_token, _as
from lithica.tests.modules import cards
from lithica.tests.modules.test_card_data_creation import (
    create,
    external,
    privileges,  # noqa: F401
)


def disk():
    root = Path(config.config["data_dir"])
    return {
        str(p.relative_to(root)): p.read_bytes()
        for name in ("posts", "generated-thumbnails")
        for p in (root / name).rglob("*")
        if p.is_file()
    }


def token(client, user, content):
    return ok(client.post("/uploads", user=user, files={"content": content}))["token"]


def test_images_roles_main_avatar_and_rerun(site, user):
    client = site(["cards"])
    images = [
        {
            "role": role,
            "token": token(client, user, cards.picture(i * 30)),
            **({"label": "  happy  "} if role == "expression" else {}),
        }
        for i, role in enumerate(
            ("avatar", "alternate-avatar", "gallery", "expression")
        )
    ]
    first = ok(
        create(
            client,
            user,
            images=images,
            externalIds=external(1),
            tags=["nsfw"],
            safety="unsafe",
        )
    )
    post = posts.get_post_by_id(first["post"]["id"])
    avatar = documents.get(post).data["avatar"]
    assert first["skippedImages"] == [] and avatar is not None
    rows = (
        db.session.query(model.PostTypedRelation)
        .filter_by(to_post_id=post.post_id)
        .all()
    )
    assert sorted(r.type for r in rows) == [
        "avatar-of",
        "avatar-of",
        "expression-of",
        "gallery-of",
    ]
    assert next(r.label for r in rows if r.type == "expression-of") == "happy"
    for row in rows:
        image = posts.get_post_by_id(row.from_post_id)
        assert image.kind == "media" and not image.listed and image.safety == "unsafe"
        assert image.user_id == user.user_id
        assert [t.first_name for t in image.tags] == ["nsfw"]
        assert (
            db.session.query(model.Snapshot)
            .filter_by(resource_type="post", resource_pkey=image.post_id)
            .count()
            == 1
        )
    count = db.session.query(model.Post).count()
    assert (
        ok(
            create(
                client, user, images=images, externalIds=external(1), tags=["ignored"]
            )
        )["outcome"]
        == "unchanged"
    )
    assert db.session.query(model.Post).count() == count
    assert documents.get(post).version == 0
    assert db.session.query(model.PostTypedRelation).count() == 4
    # Omitting the main avatar on an update retains it.
    ok(create(client, user, cards.v3_card(name="Updated"), externalIds=external(1)))
    assert documents.get(post).data["avatar"] == avatar


def test_existing_media_is_unchanged_and_card_png_stays_media(site, user):
    client = site(["cards"])
    content = cards.png_card(cards.v3_card(name="Image's embedded card"), shade=30)
    uploaded = token(client, user, content)
    first = ok(
        create(
            client,
            user,
            images=[{"role": "avatar", "token": uploaded}],
            externalIds=external(1),
        )
    )
    image_id = documents.get(posts.get_post_by_id(first["post"]["id"])).data["avatar"]
    image = posts.get_post_by_id(image_id)
    assert image.kind == "media" and image.contents
    assert db.session.get(model.PostDocument, image_id) is None
    before = (
        image.version,
        image.listed,
        image.safety,
        image.user_id,
        [t.first_name for t in image.tags],
    )
    ok(
        create(
            client,
            user,
            cards.v3_card(name="Other"),
            images=[
                {"role": "avatar", "postId": image_id},
                {"role": "gallery", "token": uploaded},
            ],
            tags=["nsfw"],
            safety="unsafe",
        )
    )
    assert (
        image.version,
        image.listed,
        image.safety,
        image.user_id,
        [t.first_name for t in image.tags],
    ) == before


@pytest.mark.parametrize(
    "bad",
    [
        {"role": "avatar"},
        {"role": "gallery", "token": "missing"},
        {"role": "expression", "token": "valid"},
        {"role": "gallery", "postId": 999999},
        {"role": "gallery", "token": "valid", "postId": 1},
        {"role": "expression", "token": "valid", "label": "\x00"},
    ],
)
def test_invalid_image_is_named_and_leaves_nothing(site, user, bad):
    client = site(["cards"])
    uploaded = token(client, user, cards.picture(30))
    bad = dict(bad)
    if bad.get("token") == "valid":
        bad["token"] = uploaded
    before = disk()
    error = assert_error(
        create(client, user, images=[{"role": "gallery", "token": uploaded}, bad]),
        errors.ValidationError,
    )
    assert "Image 1" in error["description"]
    assert db.session.query(model.Post).count() == 0
    assert disk() == before


@pytest.mark.parametrize("content", [b'{"name": "JSON"}', cards.charx()])
def test_non_media_tokens_are_rejected_before_writes(site, user, content):
    client = site(["cards"])
    images = [
        {"role": "avatar", "token": token(client, user, cards.picture(40))},
        {"role": "gallery", "token": token(client, user, content)},
    ]
    error = assert_error(create(client, user, images=images), errors.ValidationError)
    assert "Image 1" in error["description"]
    assert db.session.query(model.Post).count() == 0 and disk() == {}


@pytest.mark.parametrize("mode", ["main", "same", "too-many"])
def test_image_list_limits(site, user, mode):
    client = site(["cards"])
    uploaded = token(client, user, cards.picture(30))
    images = [{"role": "avatar", "token": uploaded}]
    if mode == "main":
        images.append({"role": "avatar", "token": uploaded})
    elif mode == "same":
        images.append({"role": "alternate-avatar", "token": uploaded})
    else:
        images = [{"role": "gallery", "token": uploaded}] * 201
    assert_error(create(client, user, images=images), errors.ValidationError)
    assert db.session.query(model.Post).count() == 0


def test_nonmedia_and_retired_tokens_are_skipped(site, user):
    client = site(["cards"])
    embedded = cards.png_card(cards.v3_card(name="Existing file card"), shade=30)
    owner = ok(
        client.post(
            "/posts", user=user, body={"safety": "safe"}, files={"content": embedded}
        )
    )
    retired = cards.picture(60)
    posts.retire_checksum(
        posts.get_post_by_id(owner["id"]), util.get_sha1(retired), "replaced"
    )
    db.session.commit()
    images = [
        {"role": "avatar", "token": token(client, user, embedded)},
        {"role": "gallery", "token": token(client, user, retired)},
    ]
    result = ok(create(client, user, images=images))
    assert result["skippedImages"] == [0, 1]
    assert (
        documents.get(posts.get_post_by_id(result["post"]["id"])).data["avatar"] is None
    )
    assert db.session.query(model.PostTypedRelation).count() == 0


def test_related_privilege_and_late_failure_leave_no_files(site, user):
    client = site(["cards"])
    images = [{"role": "avatar", "token": token(client, user, cards.picture(40))}]
    config.config["privileges"]["posts:edit:typed_relations"] = "administrator"
    assert_error(create(client, user, images=images), errors.AuthError)
    assert disk() == {} and db.session.query(model.Post).count() == 0
    config.config["privileges"]["posts:edit:typed_relations"] = "regular"
    # A refusal after creating deferred media must roll back rows and files.
    with patch(
        "lithica.modules.cards.data_creation._add_ids",
        side_effect=errors.ValidationError("Refused"),
    ):
        assert_error(create(client, user, images=images), errors.ValidationError)
    assert disk() == {} and db.session.query(model.Post).count() == 0


def test_partial_file_failure_is_cleaned_up(site, user, monkeypatch):
    client = site(["cards"])
    images = [{"role": "avatar", "token": token(client, user, cards.picture(40))}]
    original = media.files.save

    def fail_after_save(path, content):
        original(path, content)
        if path.startswith("posts/"):
            raise errors.ValidationError("Disk failure")

    monkeypatch.setattr(media.files, "save", fail_after_save)
    assert_error(create(client, user, images=images), errors.ValidationError)
    assert disk() == {} and db.session.query(model.Post).count() == 0


def test_app_token_import_and_read_only_refusal(site, user):
    client = site(["cards"])
    config.config["privileges"]["app_tokens:create:self"] = "regular"
    headers = _as(_app_token(client, user, ["read", "write", "upload"]), user)
    read_only = _as(_app_token(client, user, ["read"]), user)
    uploaded = ok(
        client.post(
            "/uploads",
            headers=headers,
            body={"contentBase64": base64.b64encode(cards.picture(40)).decode()},
        )
    )["token"]
    result = ok(
        client.post(
            "/modules/cards/cards",
            headers=headers,
            body={
                "card": cards.v3_card(),
                "safety": "safe",
                "externalIds": external(1),
                "images": [{"role": "avatar", "token": uploaded}],
            },
        )
    )
    assert result["outcome"] == "created"
    assert_error(
        client.post(
            "/modules/cards/cards",
            headers=read_only,
            body={"card": cards.v3_card(), "safety": "safe"},
        ),
        errors.AuthError,
    )


def test_hidden_token_is_skipped_and_hidden_post_id_is_invalid(
    site, user, user_factory
):
    client = site(["cards"])
    parent = ok(create(client, user, externalIds=external(1)))["post"]["id"]
    content = cards.picture(80)
    hidden = ok(
        client.post(
            "/posts",
            user=user,
            body={"safety": "safe", "tags": ["nsfw"]},
            files={"content": content},
        )
    )["id"]
    uploaded = token(client, user, content)
    count = db.session.query(model.Post).count()
    config.config["visibility"] = "nsfw-login"
    for name in (
        "posts:create:identified",
        "posts:edit:document",
        "posts:edit:external_ids",
        "posts:edit:typed_relations",
    ):
        config.config["privileges"][name] = "anonymous"
    anonymous = user_factory(rank=model.User.RANK_ANONYMOUS)
    body = {
        "card": cards.v3_card(),
        "externalIds": external(1),
        "images": [{"role": "avatar", "token": uploaded}],
    }
    answer = ok(
        client.post(
            "/modules/cards/cards", user=anonymous, query={"fields": "id"}, body=body
        )
    )
    assert answer == {
        "post": {"id": parent},
        "outcome": "unchanged",
        "skippedImages": [0],
    }
    body["images"] = [{"role": "gallery", "postId": hidden}]
    error = assert_error(
        client.post("/modules/cards/cards", user=anonymous, body=body),
        errors.ValidationError,
    )
    assert "Image 0" in error["description"] and str(hidden) not in error["description"]
    assert db.session.query(model.Post).count() == count
    assert db.session.query(model.PostTypedRelation).count() == 0


@pytest.mark.parametrize(
    "asset,type_", [("gif-animated.gif", "animation"), ("mp4.mp4", "video")]
)
def test_animation_and_video_tokens_are_media(site, user, read_asset, asset, type_):
    client = site(["cards"])
    uploaded = token(client, user, read_asset(asset))
    answer = ok(create(client, user, images=[{"role": "avatar", "token": uploaded}]))
    image_id = documents.get(posts.get_post_by_id(answer["post"]["id"])).data["avatar"]
    image = posts.get_post_by_id(image_id)
    assert image.kind == "media" and image.type == type_
    if type_ == "video":
        assert model.Post.FLAG_LOOP in image.flags
