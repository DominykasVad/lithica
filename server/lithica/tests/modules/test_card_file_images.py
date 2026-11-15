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
