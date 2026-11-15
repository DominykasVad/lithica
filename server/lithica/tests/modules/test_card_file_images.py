"""File images inherit upload policy and are projected once per current file."""

import argparse
import base64
from collections.abc import Callable
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

import pytest

from lithica import config, db, model
from lithica.func import documents, posts
from lithica.modules.cards import jobs
from lithica.modules.cards.model import Card, CardImage
from lithica.tests.api.http import ok
from lithica.tests.conftest import ApiClient
from lithica.tests.modules import cards

Site = Callable[[list[str]], ApiClient]


def upload(client: ApiClient, user: model.User, content: bytes, **body: object) -> int:
    return ok(
        client.post(
            "/posts",
            user=user,
            body={"safety": "safe", **body},
            files={"content": content},
        )
    )["id"]


def with_assets() -> bytes:
    raw = cards.v3_card(
        assets=[
            {"type": "emotion", "name": "smile", "uri": "__asset:smile"},
            {"type": "icon", "name": "main", "uri": "ccdefault:"},
            {"type": "background", "name": "wall", "uri": "__asset:wall"},
            {"type": "emotion", "uri": "__asset:bad"},
        ]
    )
    return cards.png_with(
        cards.text_chunk(b"ccv3", cards.encoded(raw)),
        cards.text_chunk(
            b"chara-ext-asset_:smile", base64.b64encode(cards.picture(20))
        ),
        cards.text_chunk(b"chara-ext-asset_:wall", base64.b64encode(cards.picture(30))),
        cards.text_chunk(b"chara-ext-asset_:bad", b"!!!"),
    )


def test_upload_main_and_job(site: Site, user: model.User) -> None:
    client = site(["cards"])
    config.config["privileges"]["posts:edit:typed_relations"] = "administrator"
    parent = upload(client, user, with_assets(), safety="unsafe", tags=["nsfw"])
    document = documents.get(posts.get_post_by_id(parent))
    avatar = document.data["avatar"]
    assert avatar is not None and document.version == 0
    row = db.session.get(Card, parent)
    assert row is not None and not row.images_read
    image = posts.get_post_by_id(avatar)
    assert (
        image.user_id == user.user_id and image.safety == "unsafe" and not image.listed
    )
    assert [t.names[0].name for t in image.tags] == ["nsfw"]
    first = db.session.query(CardImage).one()
    assert first.uri == "ccdefault:" and first.position == 1
    job = db.session.query(model.Job).filter_by(type="cards-images").one()
    jobs.run_images(job.payload)
    assert row.images_read
    assert db.session.query(CardImage).count() == 3
    assert {r.type for r in db.session.query(CardImage)} == {
        "avatar-of",
        "expression-of",
        "embedded-in",
    }
    count = db.session.query(model.Post).count()
    jobs.run_images(job.payload)
    assert db.session.query(model.Post).count() == count
    assert db.session.query(CardImage).count() == 3
    assert document.version == 0


def test_stale_job_does_nothing(site: Site, user: model.User) -> None:
    client = site(["cards"])
    parent = upload(client, user, with_assets())
    jobs.run_images({"postId": parent, "checksum": "changed"})
    assert db.session.query(CardImage).count() == 1
    assert not db.session.get(Card, parent).images_read


def test_shared_picture_and_no_extra_privilege(site: Site, user: model.User) -> None:
    client = site(["cards"])
    config.config["privileges"]["posts:edit:typed_relations"] = "administrator"
    ids = [
        upload(client, user, cards.png_card(cards.v2_card(name=str(i))))
        for i in range(2)
    ]
    avatars = [documents.get(posts.get_post_by_id(i)).data["avatar"] for i in ids]
    assert avatars[0] is not None and avatars[0] == avatars[1]
    assert db.session.query(model.PostTypedRelation).count() == 2
    assert all(db.session.get(Card, i).images_read for i in ids)


def test_backfill_one_version_only(
    site: Site, user: model.User, capsys: pytest.CaptureFixture[str]
) -> None:
    client = site(["cards"])
    parent = upload(client, user, cards.png_card(cards.v2_card()))
    post = posts.get_post_by_id(parent)
    document = documents.get(post)
    data = deepcopy(document.data)
    data["avatar"] = None
    documents.write(post, data, 0, user)
    db.session.get(Card, parent).images_read = False
    db.session.flush()
    jobs.command(argparse.Namespace(count=True))
    assert "1 cards" in capsys.readouterr().out
    jobs.run({"after": 0})
    assert document.version == 2 and document.data["avatar"] is not None
    assert documents.get_version(post, 2).note == "Images read from the file."
    jobs.run({"after": 0})
    assert document.version == 2 and jobs.pending().count() == 0


def test_media_cleanup_on_savepoint_rollback(
    site: Site, user: model.User, tmp_path: Path
) -> None:
    from lithica.modules.cards import file_images

    client = site(["cards"])
    parent = upload(client, user, with_assets())
    post = posts.get_post_by_id(parent)
    before = {
        p.relative_to(config.config["data_dir"])
        for p in Path(config.config["data_dir"]).rglob("*")
        if p.is_file()
    }
    with pytest.raises(RuntimeError), db.session.begin_nested():
        result = file_images.read_all(post, None)
        file_images.finish(post, result)
        db.session.flush()
        during = {p for p in Path(config.config["data_dir"]).rglob("*") if p.is_file()}
        assert len(during) > len(before)
        raise RuntimeError("rollback")
    after = {
        p.relative_to(config.config["data_dir"])
        for p in Path(config.config["data_dir"]).rglob("*")
        if p.is_file()
    }
    assert after == before
    assert db.session.query(CardImage).count() == 1


def test_bad_asset_never_fails_upload(site: Site, user: model.User) -> None:
    client = site(["cards"])
    with patch(
        "lithica.modules.cards.assets.Source.picture",
        side_effect=ValueError("private bytes"),
    ):
        parent = upload(client, user, with_assets())
    assert documents.get(posts.get_post_by_id(parent)).data["avatar"] is None


@pytest.mark.parametrize("shared", [False, True])
def test_replacement_discards_only_unrelated_old_media(
    site: Site, user: model.User, shared: bool
) -> None:
    from lithica.func import files
    from lithica.tests.modules.test_card_file_replace import replace

    client = site(["cards"])
    config.config["delete_source_files"] = True
    parent = upload(client, user, cards.png_card(cards.v2_card(name="First")))
    old = documents.get(posts.get_post_by_id(parent)).data["avatar"]
    old_path = posts.get_post_content_path(posts.get_post_by_id(old))
    if shared:
        other = upload(client, user, cards.png_card(cards.v2_card(name="Second")))
        assert documents.get(posts.get_post_by_id(other)).data["avatar"] == old
    answer = ok(
        replace(
            client,
            user,
            parent,
            cards.png_card(cards.v2_card(name="New"), shade=80),
            keepOldPicture=False,
        )
    )
    assert answer["keptPostId"] is None
    assert documents.get(posts.get_post_by_id(parent)).data["avatar"] != old
    assert (
        db.session.query(model.PostTypedRelation)
        .filter_by(from_post_id=old, to_post_id=parent, type="avatar-of")
        .count()
        == 0
    )
    assert (posts.try_get_post_by_id(old) is not None) == shared
    assert files.has(old_path) == shared


def test_failed_replacement_keeps_old_media_files(site: Site, user: model.User) -> None:
    from lithica import errors
    from lithica.func import files
    from lithica.modules.cards import replacement

    client = site(["cards"])
    config.config["delete_source_files"] = True
    parent = upload(client, user, cards.png_card(cards.v2_card()))
    post = posts.get_post_by_id(parent)
    old = documents.get(post).data["avatar"]
    old_path = posts.get_post_content_path(posts.get_post_by_id(old))
    root = Path(config.config["data_dir"])
    before = {
        p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()
    }
    with (
        pytest.raises(errors.ValidationError),
        db.session.begin_nested(),
        patch(
            "lithica.modules.cards.replacement.snapshots.modify",
            side_effect=errors.ValidationError("late refusal"),
        ),
    ):
        replacement.replace(
            post,
            cards.png_card(cards.v2_card(name="New"), shade=80),
            post.version,
            False,
            user,
        )
    assert files.has(old_path)
    assert posts.get_post_by_id(old).kind == "media"
    assert documents.get(post).data["avatar"] == old
    after = {
        p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()
    }
    assert after == before


@pytest.mark.parametrize("has_avatar", [False, True])
def test_fileless_card_gains_main_or_alternate_avatar(
    site: Site, user: model.User, has_avatar: bool
) -> None:
    from lithica.tests.modules.test_card_file_replace import replace

    client = site(["cards"])
    old = upload(client, user, cards.picture(50)) if has_avatar else None
    post = posts.create_fileless_post("card", user)
    db.session.flush()
    documents.create(
        post,
        "card",
        {"spec": "card_v1", "card": cards.V1_CARD, "lorebooks": [], "avatar": old},
        user,
    )
    db.session.commit()
    answer = ok(replace(client, user, post.post_id, cards.png_card(cards.V1_CARD)))
    image = db.session.query(CardImage).filter_by(card_post_id=post.post_id).one()
    avatar = documents.get(post).data["avatar"]
    assert avatar == (old if has_avatar else image.post_id)
    assert image.type == "avatar-of" and image.uri == "ccdefault:"
    assert answer["keptPostId"] is None and answer["samePicture"] is False
    assert db.session.query(model.PostRetiredChecksum).count() == 0


def test_answer_image_order_mime_and_visibility(
    site: Site, user: model.User, user_factory: Callable[..., model.User]
) -> None:
    from io import BytesIO

    from PIL import Image

    client = site(["cards"])
    blobs: dict[str, bytes] = {"main.png": cards.picture()}
    for path, format_ in (("smile.gif", "GIF"), ("wall.webp", "WEBP")):
        output = BytesIO()
        Image.new("RGB", (16, 16), (40, 60, 80)).save(output, format_)
        blobs[path] = output.getvalue()
    raw = cards.v3_card(
        name="Formats",
        assets=[
            {"type": "emotion", "name": "smile", "uri": "embeded://smile.gif"},
            {"type": "icon", "name": "main", "uri": "embeded://main.png"},
            {"type": "background", "name": "wall", "uri": "embedded://wall.webp"},
        ],
    )
    parent = upload(client, user, cards.charx(raw, **blobs))
    jobs.run_images(
        db.session.query(model.Job).filter_by(type="cards-images").one().payload
    )
    answer = ok(client.get(f"/modules/cards/post/{parent}", user=user))
    assert answer["imagesRead"] is True
    images = answer["images"]
    assert [i["post"]["mimeType"] for i in images] == [
        "image/gif",
        "image/png",
        "image/webp",
    ]
    assert [i["relation"] for i in images] == [
        "expression-of",
        "avatar-of",
        "embedded-in",
    ]
    assert [i["label"] for i in images] == ["smile", "main", "wall"]
    assert [i["assetType"] for i in images] == ["emotion", "icon", "background"]
    assert answer["avatar"]["id"] == images[1]["post"]["id"]
    assert [i["post"]["contentUrl"].rsplit(".", 1)[1] for i in images] == [
        "gif",
        "png",
        "webp",
    ]
    posts.update_post_tags(posts.get_post_by_id(images[0]["post"]["id"]), ["nsfw"])
    db.session.commit()
    config.config["visibility"] = "nsfw-login"
    config.config["privileges"]["posts:view"] = "anonymous"
    anonymous = user_factory(rank=model.User.RANK_ANONYMOUS)
    hidden = ok(client.get(f"/modules/cards/post/{parent}", user=anonymous))
    assert [i["uri"] for i in hidden["images"]] == [
        "embeded://main.png",
        "embedded://wall.webp",
    ]
    assert hidden["imagesRead"] is True


def test_card_post_field_query_count_ignores_image_rows(
    site: Site, user: model.User
) -> None:
    import sqlalchemy as sa
    import sqlalchemy.event as sa_event

    from lithica.modules.cards import api

    client = site(["cards"])
    parent = upload(client, user, with_assets())

    def query_count() -> int:
        db.session.expire_all()
        post = posts.get_post_by_id(parent)
        count = 0

        def queried(*_args: object) -> None:
            nonlocal count
            count += 1

        sa_event.listen(sa.engine.Engine, "before_cursor_execute", queried)
        try:
            assert api.card_fields([post], user)[parent] is not None
        finally:
            sa_event.remove(sa.engine.Engine, "before_cursor_execute", queried)
        return count

    before = query_count()
    jobs.run_images(
        db.session.query(model.Job).filter_by(type="cards-images").one().payload
    )
    assert db.session.query(CardImage).count() == 3
    assert query_count() == before == 1


def test_same_media_keeps_each_asset_label(site: Site, user: model.User) -> None:
    client = site(["cards"])
    content = cards.png_with(
        cards.text_chunk(
            b"ccv3",
            cards.encoded(
                cards.v3_card(
                    assets=[
                        {"type": "emotion", "name": "happy", "uri": "__asset:a"},
                        {"type": "emotion", "name": "sad", "uri": "__asset:b"},
                    ]
                )
            ),
        ),
        cards.text_chunk(b"chara-ext-asset_:a", base64.b64encode(cards.picture(21))),
        cards.text_chunk(b"chara-ext-asset_:b", base64.b64encode(cards.picture(21))),
    )
    parent = upload(client, user, content)
    jobs.run_images(
        db.session.query(model.Job).filter_by(type="cards-images").one().payload
    )
    answer = ok(client.get(f"/modules/cards/post/{parent}", user=user))
    images = answer["images"]
    assert [image["label"] for image in images] == ["happy", "sad"]
    assert images[0]["post"]["id"] == images[1]["post"]["id"]
    relation = (
        db.session.query(model.PostTypedRelation).filter_by(to_post_id=parent).one()
    )
    assert relation.type == "expression-of" and relation.label == "happy"
