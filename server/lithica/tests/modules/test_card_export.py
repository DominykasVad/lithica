"""Integration tests for card export (embedded mode, assets, text links, limits)."""

import base64
import io
import json
from collections.abc import Callable
from typing import Any

import pytest
from PIL import Image

from lithica import config, db, model
from lithica.func import file_uploads, post_metadata, posts, util
from lithica.modules.cards import archived_links, assets, charx, png
from lithica.modules.cards import card as card_format
from lithica.modules.cards.model import ArchivedLink, CardImage
from lithica.tests.api.http import ok
from lithica.tests.conftest import ApiClient
from lithica.tests.modules import cards
from lithica.tests.modules.test_card_data_creation import create


@pytest.fixture
def client(site: Callable[[list[str]], ApiClient]) -> ApiClient:
    config.config["visibility"] = "nsfw-login"
    config.config["privileges"]["posts:view"] = "anonymous"
    config.config["privileges"]["posts:edit:typed_relations"] = "regular"
    config.config["privileges"]["posts:delete"] = "regular"
    return site(["cards"])


def _upload_media(
    client: ApiClient,
    user: model.User,
    data: bytes,
    *,
    tags: list[str] | None = None,
    safety: str = "safe",
) -> int:
    return ok(
        client.post(
            "/posts",
            user=user,
            body={"safety": safety, "tags": tags or []},
            files={"content": data},
        )
    )["id"]


def _animated_gif() -> bytes:
    frames = [
        Image.new("RGB", (16, 16), (200, 10, 10)),
        Image.new("RGB", (16, 16), (10, 200, 10)),
    ]
    buf = io.BytesIO()
    frames[0].save(
        buf, format="GIF", save_all=True, append_images=frames[1:], duration=100, loop=0
    )
    return buf.getvalue()


def _pixels(data: bytes) -> tuple[tuple[int, int], bytes]:
    with Image.open(io.BytesIO(data)) as img:
        rgba = img.convert("RGBA")
        return rgba.size, rgba.tobytes()


def test_export_formats_specs_and_errors(client: ApiClient, user: model.User) -> None:
    avatar = cards.picture(12)
    uploaded = ok(
        client.post(
            "/posts",
            user=user,
            body={"safety": "safe"},
            files={"content": cards.png_card(cards.v3_card(name="Ada"), shade=12)},
        )
    )
    post_id = uploaded["id"]

    # Default export: PNG v3+v2 embedded.
    resp = client.post(f"/modules/cards/post/{post_id}/export", user=user, body={})
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["cache-control"] == "no-store"
    assert resp.headers["x-lithica-export-skipped"] == "0"
    assert 'filename="Ada.png"' in resp.headers["content-disposition"]
    embedded = png.read(io.BytesIO(resp.content))
    assert [c.keyword for c in embedded.cards] == [png.V3_KEYWORD, png.V2_KEYWORD]
    v3_read = png.read_card(io.BytesIO(resp.content))
    assert v3_read is not None and v3_read["spec"] == "chara_card_v3"
    assert _pixels(resp.content) == _pixels(avatar)

    # PNG v3 only and v2 only.
    resp_v3 = client.post(
        f"/modules/cards/post/{post_id}/export",
        user=user,
        body={"format": "png", "spec": "v3"},
    )
    assert resp_v3.status_code == 200
    assert [c.keyword for c in png.read(io.BytesIO(resp_v3.content)).cards] == [
        png.V3_KEYWORD
    ]

    resp_v2 = client.post(
        f"/modules/cards/post/{post_id}/export",
        user=user,
        body={"format": "png", "spec": "v2"},
    )
    assert resp_v2.status_code == 200
    assert [c.keyword for c in png.read(io.BytesIO(resp_v2.content)).cards] == [
        png.V2_KEYWORD
    ]
    v2_read = png.read_card(io.BytesIO(resp_v2.content))
    assert v2_read is not None and v2_read["spec"] == "chara_card_v2"

    # CHARX v3.
    resp_charx = client.post(
        f"/modules/cards/post/{post_id}/export",
        user=user,
        body={"format": "charx"},
    )
    assert resp_charx.status_code == 200
    assert resp_charx.headers["content-type"] == charx.MIME_TYPE
    assert 'filename="Ada.charx"' in resp_charx.headers["content-disposition"]
    with charx.opened(io.BytesIO(resp_charx.content)) as opened:
        assert opened.card["spec"] == "chara_card_v3"
        assert charx.main_icon(opened) == avatar

    # JSON v3 and v2.
    resp_json_v3 = client.post(
        f"/modules/cards/post/{post_id}/export",
        user=user,
        body={"format": "json"},
    )
    assert resp_json_v3.status_code == 200
    assert resp_json_v3.headers["content-type"] == "application/json"
    parsed_v3 = json.loads(resp_json_v3.content)
    assert parsed_v3["spec"] == "chara_card_v3"
    assert parsed_v3["data"]["assets"][0]["uri"].startswith("data:image/png;base64,")

    resp_json_v2 = client.post(
        f"/modules/cards/post/{post_id}/export",
        user=user,
        body={"format": "json", "spec": "v2"},
    )
    assert resp_json_v2.status_code == 200
    parsed_v2 = json.loads(resp_json_v2.content)
    assert parsed_v2["spec"] == "chara_card_v2"
    assert "assets" not in parsed_v2["data"]

    # Invalid spec combinations.
    for body in (
        {"format": "charx", "spec": "v2"},
        {"format": "charx", "spec": "v3+v2"},
        {"format": "json", "spec": "v3+v2"},
    ):
        bad = client.post(f"/modules/cards/post/{post_id}/export", user=user, body=body)
        assert bad.status_code == 400

    # Non-card post -> 404 "has no character card".
    media_id = _upload_media(client, user, cards.picture(99))
    not_card = client.post(
        f"/modules/cards/post/{media_id}/export", user=user, body={"format": "json"}
    )
    assert not_card.status_code == 404
    assert "has no character card" in not_card.json()["description"]


def test_round_trip_png_and_charx(client: ApiClient, user: model.User) -> None:
    avatar = cards.picture(21)
    emotion = cards.picture(22)
    book_id = ok(
        client.post(
            "/modules/cards/lorebooks",
            user=user,
            body={"safety": "safe", "book": cards.LOREBOOK},
        )
    )["post"]["id"]
    card_id = ok(
        create(
            client,
            user,
            cards.v3_card(name="RoundTrip", first_mes="Hello there."),
            lorebooks=[book_id],
            images=[
                {"role": "avatar", "token": file_uploads.save(avatar)},
                {
                    "role": "expression",
                    "token": file_uploads.save(emotion),
                    "label": "smile",
                },
            ],
        )
    )["post"]["id"]
    before = ok(client.get(f"/modules/cards/post/{card_id}", user=user))

    png_bytes = client.post(
        f"/modules/cards/post/{card_id}/export",
        user=user,
        body={"format": "png", "spec": "v3+v2", "images": "embedded"},
    ).content
    charx_bytes = client.post(
        f"/modules/cards/post/{card_id}/export",
        user=user,
        body={"format": "charx", "spec": "v3", "images": "embedded"},
    ).content

    # Delete source card first (data duplicate otherwise), then upload PNG export.
    card_post = ok(client.get(f"/post/{card_id}", user=user))
    assert (
        client.delete(
            f"/post/{card_id}", user=user, body={"version": card_post["version"]}
        ).status_code
        == 200
    )

    re_png = ok(
        client.post(
            "/posts", user=user, body={"safety": "safe"}, files={"content": png_bytes}
        )
    )
    # Run the images job to attach non-main assets, as on normal upload.
    from lithica.modules.cards import file_images

    file_images.read_all(posts.get_post_by_id(re_png["id"]), user)
    db.session.commit()
    after_png = ok(client.get(f"/modules/cards/post/{re_png['id']}", user=user))
    assert after_png["name"] == before["name"]
    assert after_png["firstMessage"] == before["firstMessage"]
    assert after_png["lorebook"] == before["lorebook"]
    assert len(after_png["images"]) == 2

    # Delete PNG card, upload CHARX export.
    re_png_post = ok(client.get(f"/post/{re_png['id']}", user=user))
    assert (
        client.delete(
            f"/post/{re_png['id']}",
            user=user,
            body={"version": re_png_post["version"]},
        ).status_code
        == 200
    )
    re_charx = ok(
        client.post(
            "/posts",
            user=user,
            body={"safety": "safe"},
            files={"content": charx_bytes},
        )
    )
    file_images.read_all(posts.get_post_by_id(re_charx["id"]), user)
    db.session.commit()
    after_charx = ok(client.get(f"/modules/cards/post/{re_charx['id']}", user=user))
    assert after_charx["name"] == before["name"]
    assert after_charx["firstMessage"] == before["firstMessage"]
    assert after_charx["lorebook"] == before["lorebook"]
    assert len(after_charx["images"]) == 2


def test_assets_resolution_dedup_relations_and_visibility(
    client: ApiClient, user: model.User
) -> None:
    avatar_bytes = cards.picture(31)
    pos_bytes = cards.picture(32)
    archived_bytes = cards.picture(33)
    ref_bytes = cards.picture(34)
    alt_bytes = cards.picture(35)
    expr_bytes = cards.picture(36)
    gallery_bytes = cards.picture(37)
    hidden_bytes = cards.picture(38)

    avatar_id = _upload_media(client, user, avatar_bytes)
    pos_id = _upload_media(client, user, pos_bytes)
    archived_id = _upload_media(client, user, archived_bytes)
    ref_id = _upload_media(client, user, ref_bytes)
    alt_id = _upload_media(client, user, alt_bytes)
    expr_id = _upload_media(client, user, expr_bytes)
    gallery_id = _upload_media(client, user, gallery_bytes)
    hidden_id = _upload_media(
        client, user, hidden_bytes, tags=["nsfw"], safety="unsafe"
    )

    visible_book_id = ok(
        client.post(
            "/modules/cards/lorebooks",
            user=user,
            body={"safety": "safe", "book": {"name": "Visible", "entries": []}},
        )
    )["post"]["id"]
    hidden_book_id = ok(
        client.post(
            "/modules/cards/lorebooks",
            user=user,
            body={
                "safety": "unsafe",
                "tags": ["nsfw"],
                "book": {"name": "HiddenBook", "entries": []},
            },
        )
    )["post"]["id"]

    card_payload = cards.v3_card(
        name="AssetsTest",
        assets=[
            {"type": "icon", "uri": "ccdefault:", "name": "main", "ext": "png"},
            {
                "type": "x-pos",
                "uri": "embeded://old/pos.png",
                "name": "by-pos",
                "ext": "png",
            },
            {
                "type": "x-dup",
                "uri": f"lithica:post/{pos_id}",
                "name": "same-post",
                "ext": "png",
            },
            {
                "type": "background",
                "uri": "https://img.test/archived.png",
                "name": "arch",
                "ext": "png",
            },
            {
                "type": "background",
                "uri": "https://img.test/unarchived.png",
                "name": "keep-https",
                "ext": "png",
            },
            {
                "type": "x-ref",
                "uri": f"lithica:post/{ref_id}",
                "name": "by-ref",
                "ext": "png",
            },
            {
                "type": "x-hidden-ref",
                "uri": f"lithica:post/{hidden_id}",
                "name": "hidden-ref",
                "ext": "png",
            },
            {
                "type": "x-missing",
                "uri": "embeded://missing.png",
                "name": "missing",
                "ext": "png",
            },
        ],
    )
    card_payload["data"].pop("character_book", None)
    card_id = ok(
        create(
            client,
            user,
            card_payload,
            lorebooks=[visible_book_id, hidden_book_id],
            images=[
                {"role": "avatar", "postId": avatar_id},
                {"role": "alternate-avatar", "postId": alt_id},
                {"role": "expression", "postId": expr_id, "label": "wink"},
                {"role": "gallery", "postId": gallery_id},
            ],
        )
    )["post"]["id"]

    db.session.add(
        CardImage(
            card_post_id=card_id,
            uri="embeded://old/pos.png",
            post_id=pos_id,
            type="embedded-in",
            asset_type="x-pos",
            label="by-pos",
            position=1,
        )
    )
    db.session.add(
        ArchivedLink(
            card_post_id=card_id,
            url="https://img.test/archived.png",
            url_hash=archived_links.url_hash("https://img.test/archived.png"),
            status="archived",
            reason=None,
            post_id=archived_id,
            attempts=1,
            last_attempt_time=util.utcnow(),
        )
    )
    post_metadata.create_typed_relation(
        archived_id, card_id, "archived-from", None, user
    )
    db.session.commit()

    # Anonymous viewer: hidden_id and hidden_book_id are invisible.
    resp = client.post(
        f"/modules/cards/post/{card_id}/export",
        body={"format": "charx", "images": "embedded"},
    )
    assert resp.status_code == 200
    # 2 skipped: hidden_ref + missing embeded://
    assert resp.headers["x-lithica-export-skipped"] == "2"
    with charx.opened(io.BytesIO(resp.content)) as opened:
        out_assets: list[dict[str, Any]] = opened.card["data"]["assets"]  # type: ignore[index]
        names = [(a["type"], a["name"]) for a in out_assets]
        assert names == [
            ("icon", "main"),
            ("x-pos", "by-pos"),
            ("x-dup", "same-post"),
            ("background", "arch"),
            ("background", "keep-https"),
            ("x-ref", "by-ref"),
            ("icon", "alt-1"),
            ("emotion", "wink"),
        ]
        # Same post (pos_id) appears once in the archive, shared by both entries.
        assert out_assets[1]["uri"] == out_assets[2]["uri"]
        assert out_assets[4]["uri"] == "https://img.test/unarchived.png"
        # Gallery and archived-from posts are not added as assets.
        file_entries = [e.filename for e in opened.entries if e.filename != "card.json"]
        # Unique posts: avatar, pos, archived, ref, alt, expr = 6 files.
        assert len(file_entries) == 6
        # Only visible book is included (single book -> unchanged, no HiddenBook).
        book = opened.card["data"]["character_book"]  # type: ignore[index]
        assert book["name"] == "Visible"
        assert "HiddenBook" not in json.dumps(opened.card)
        assert f"lithica:post/{hidden_id}" not in json.dumps(opened.card)
        assert "hidden-ref" not in json.dumps(opened.card)


def test_png_refused_without_avatar_and_handles_gif_and_video(
    client: ApiClient, user: model.User
) -> None:
    # Card without avatar: PNG refused, JSON/CHARX succeed without main icon.
    no_avatar_id = ok(create(client, user, cards.v3_card(name="NoAvatar")))["post"][
        "id"
    ]
    bad = client.post(
        f"/modules/cards/post/{no_avatar_id}/export", user=user, body={"format": "png"}
    )
    assert bad.status_code == 400
    assert "no avatar" in bad.json()["description"]

    ok_json = client.post(
        f"/modules/cards/post/{no_avatar_id}/export", user=user, body={"format": "json"}
    )
    assert ok_json.status_code == 200
    assert json.loads(ok_json.content)["data"]["assets"] == []

    # Animated GIF avatar -> re-encoded to PNG (first frame).
    gif_id = _upload_media(client, user, _animated_gif())
    gif_card_id = ok(
        create(
            client,
            user,
            cards.v3_card(name="GifAvatar"),
            images=[{"role": "avatar", "postId": gif_id}],
        )
    )["post"]["id"]
    resp_gif = client.post(
        f"/modules/cards/post/{gif_card_id}/export", user=user, body={"format": "png"}
    )
    assert resp_gif.status_code == 200
    assert resp_gif.content.startswith(png.SIGNATURE)
    with Image.open(io.BytesIO(resp_gif.content)) as img:
        assert img.size == (16, 16)
        assert img.convert("RGB").getpixel((0, 0)) == (200, 10, 10)

    # Video avatar -> thumbnail re-encoded to PNG.
    video_post, _ = posts.create_post(cards.picture(61), ["video_tag"], user)
    video_post.mime_type = "video/mp4"
    video_post.type = model.Post.TYPE_VIDEO
    from lithica.func import files as storage

    storage.save(posts.get_post_content_path(video_post), b"\x00\x00\x00\x18ftypisom")
    storage.save(posts.get_post_thumbnail_path(video_post), cards.picture(60))
    db.session.commit()

    vid_card_id = ok(
        create(
            client,
            user,
            cards.v3_card(name="VidAvatar"),
            images=[{"role": "avatar", "postId": video_post.post_id}],
        )
    )["post"]["id"]
    resp_vid = client.post(
        f"/modules/cards/post/{vid_card_id}/export", user=user, body={"format": "png"}
    )
    assert resp_vid.status_code == 200
    assert resp_vid.content.startswith(png.SIGNATURE)
    assert _pixels(resp_vid.content) == _pixels(cards.picture(60))


def test_text_links_resolution_and_extensions_untouched(
    client: ApiClient, user: model.User
) -> None:
    img_bytes = cards.picture(44)
    img_id = _upload_media(client, user, img_bytes)
    hidden_id = _upload_media(
        client, user, cards.picture(45), tags=["nsfw"], safety="unsafe"
    )
    expected_uri = (
        f"data:image/png;base64,{base64.b64encode(img_bytes).decode('ascii')}"
    )

    text = (
        "![md](https://img.test/a.png)\n"
        '<img src="https://img.test/b.png" srcset="https://img.test/a.png 1x, '
        f'lithica:post/{img_id} 2x">\n'
        '<div style="background: url(https://img.test/a.png)"></div>\n'
        "`![code](https://img.test/a.png)`\n"
        "![hidden](https://img.test/hidden.png)\n"
        f"![missing-ref](lithica:post/{hidden_id})\n"
    )
    card_id = ok(
        create(
            client,
            user,
            cards.v3_card(
                name="TextLinks",
                first_mes=text,
                extensions={"keep": "![ext](https://img.test/a.png)"},
            ),
        )
    )["post"]["id"]
    for url, target in (
        ("https://img.test/a.png", img_id),
        ("https://img.test/b.png", img_id),
        ("https://img.test/hidden.png", hidden_id),
    ):
        db.session.add(
            ArchivedLink(
                card_post_id=card_id,
                url=url,
                url_hash=archived_links.url_hash(url),
                status="archived",
                reason=None,
                post_id=target,
                attempts=1,
                last_attempt_time=util.utcnow(),
            )
        )
    db.session.commit()

    # Export as anonymous (hidden_id is invisible).
    resp = client.post(
        f"/modules/cards/post/{card_id}/export",
        body={"format": "json", "spec": "v3", "images": "embedded"},
    )
    assert resp.status_code == 200
    assert resp.headers["x-lithica-export-skipped"] == "2"
    exported = json.loads(resp.content)
    out_text = exported["data"]["first_mes"]
    assert f"![md]({expected_uri})" in out_text
    assert f'src="{expected_uri}"' in out_text
    assert f'srcset="{expected_uri} 1x, {expected_uri} 2x"' in out_text
    assert f"url({expected_uri})" in out_text
    assert "`![code](https://img.test/a.png)`" in out_text
    assert "![hidden](https://img.test/hidden.png)" in out_text
    assert f"![missing-ref](lithica:post/{hidden_id})" in out_text
    assert exported["data"]["extensions"] == {"keep": "![ext](https://img.test/a.png)"}


def test_export_limits_per_format(
    client: ApiClient, user: model.User, monkeypatch: pytest.MonkeyPatch
) -> None:
    avatar_id = _upload_media(client, user, cards.picture(51))
    card_id = ok(
        create(
            client,
            user,
            cards.v3_card(name="Limits", description="x" * 1000),
            images=[{"role": "avatar", "postId": avatar_id}],
        )
    )["post"]["id"]

    # PNG chunk limit.
    monkeypatch.setattr(card_format, "MAX_CARD_SIZE", 500)
    r_png = client.post(
        f"/modules/cards/post/{card_id}/export", user=user, body={"format": "png"}
    )
    assert r_png.status_code == 400
    assert "chunk limit" in r_png.json()["description"]
    monkeypatch.undo()

    # CHARX card.json limit.
    monkeypatch.setattr(charx, "MAX_CARD_SIZE", 500)
    r_charx = client.post(
        f"/modules/cards/post/{card_id}/export", user=user, body={"format": "charx"}
    )
    assert r_charx.status_code == 400
    assert "card.json" in r_charx.json()["description"]
    monkeypatch.undo()

    # JSON max_base64_upload_size limit.
    monkeypatch.setitem(config.config, "max_base64_upload_size", 500)
    r_json = client.post(
        f"/modules/cards/post/{card_id}/export", user=user, body={"format": "json"}
    )
    assert r_json.status_code == 400
    assert "JSON" in r_json.json()["description"]
    monkeypatch.undo()

    # PNG asset size limit.
    extra_id = _upload_media(client, user, cards.picture(52))
    post_metadata.create_typed_relation(extra_id, card_id, "avatar-of", None, user)
    db.session.commit()
    monkeypatch.setattr(assets, "MAX_IMAGE_SIZE", 10)
    r_asset = client.post(
        f"/modules/cards/post/{card_id}/export", user=user, body={"format": "png"}
    )
    assert r_asset.status_code == 400
    assert "PNG asset limit" in r_asset.json()["description"]


def test_share_link_mode_reuse_and_png_avatar_excluded(
    client: ApiClient, user: model.User, monkeypatch: pytest.MonkeyPatch
) -> None:
    config.config["privileges"]["share_links:create"] = "regular"
    monkeypatch.setitem(config.config, "domain", "https://booru.test/")

    avatar_id = _upload_media(client, user, cards.picture(71))
    expr_id = _upload_media(client, user, cards.picture(72))
    text_img_id = _upload_media(client, user, cards.picture(73))

    card_id = ok(
        create(
            client,
            user,
            cards.v3_card(
                name="LinkCard",
                first_mes=f"Look: ![pic](lithica:post/{text_img_id})",
            ),
            images=[
                {"role": "avatar", "postId": avatar_id},
                {"role": "expression", "postId": expr_id, "label": "happy"},
            ],
        )
    )["post"]["id"]

    # Manual links (different note or with expiry) must never be reused.
    from lithica.func import share_links

    manual_other_note = share_links.create(
        posts.get_post_by_id(expr_id), user, "Manual note", None
    )
    manual_expiring = share_links.create(
        posts.get_post_by_id(expr_id), user, "Card export", "2099-01-01T00:00:00"
    )
    db.session.commit()

    resp = client.post(
        f"/modules/cards/post/{card_id}/export",
        user=user,
        body={"format": "png", "spec": "v3+v2", "images": "links"},
    )
    assert resp.status_code == 200
    exported = png.read_card(io.BytesIO(resp.content))
    assert exported is not None
    # PNG's own picture never gets a share link.
    assert db.session.query(model.ShareLink).filter_by(post_id=avatar_id).count() == 0
    # Expression got a new "Card export" link (manual links not reused).
    expr_links = (
        db.session.query(model.ShareLink)
        .filter_by(post_id=expr_id)
        .order_by(model.ShareLink.id)
        .all()
    )
    assert len(expr_links) == 3
    export_link = next(
        link
        for link in expr_links
        if link.id not in (manual_other_note.id, manual_expiring.id)
    )
    assert export_link.note == "Card export"
    assert export_link.expires_at is None
    expected_expr_url = (
        f"https://booru.test/share/{share_links.derive_token(export_link.salt)}"
    )
    out_assets: list[dict[str, Any]] = exported["data"]["assets"]  # type: ignore[index]
    assert out_assets[0]["uri"] == "ccdefault:"
    assert out_assets[1]["uri"] == expected_expr_url

    text_link = db.session.query(model.ShareLink).filter_by(post_id=text_img_id).one()
    expected_text_url = (
        f"https://booru.test/share/{share_links.derive_token(text_link.salt)}"
    )
    assert f"![pic]({expected_text_url})" in exported["data"]["first_mes"]  # type: ignore[index]

    # Second export reuses the exact same "Card export" links.
    resp2 = client.post(
        f"/modules/cards/post/{card_id}/export",
        user=user,
        body={"format": "charx", "images": "links"},
    )
    assert resp2.status_code == 200
    assert db.session.query(model.ShareLink).filter_by(post_id=expr_id).count() == 3
    assert db.session.query(model.ShareLink).filter_by(post_id=text_img_id).count() == 1
    # CHARX does create a link for the avatar (it is not a PNG carrier).
    assert db.session.query(model.ShareLink).filter_by(post_id=avatar_id).count() == 1


def test_share_link_mode_nsfw_domain_privilege_and_rollback(
    client: ApiClient, user: model.User, monkeypatch: pytest.MonkeyPatch
) -> None:
    config.config["privileges"]["share_links:create"] = "power"
    avatar_id = _upload_media(client, user, cards.picture(81))
    safe_img_id = _upload_media(client, user, cards.picture(82))
    nsfw_img_id = _upload_media(
        client, user, cards.picture(83), tags=["nsfw"], safety="unsafe"
    )

    safe_card_id = ok(
        create(
            client,
            user,
            cards.v3_card(name="SafeCard"),
            images=[
                {"role": "avatar", "postId": avatar_id},
                {"role": "expression", "postId": safe_img_id, "label": "ok"},
            ],
        )
    )["post"]["id"]

    # Privilege check: regular user lacks share_links:create (power).
    monkeypatch.setitem(config.config, "domain", "https://booru.test")
    no_priv = client.post(
        f"/modules/cards/post/{safe_card_id}/export",
        user=user,
        body={"format": "json", "images": "links"},
    )
    assert no_priv.status_code == 403

    # Grant privilege; missing domain refused.
    config.config["privileges"]["share_links:create"] = "regular"
    monkeypatch.setitem(config.config, "domain", "")
    no_domain = client.post(
        f"/modules/cards/post/{safe_card_id}/export",
        user=user,
        body={"format": "json", "images": "links"},
    )
    assert no_domain.status_code == 400
    assert "domain" in no_domain.json()["description"]
    assert db.session.query(model.ShareLink).count() == 0

    monkeypatch.setitem(config.config, "domain", "https://booru.test")

    # NSFW card with untagged images refused while share_links_nsfw is off.
    nsfw_card_id = ok(
        create(
            client,
            user,
            cards.v3_card(name="NsfwCard"),
            safety="unsafe",
            tags=["nsfw"],
            images=[
                {"role": "avatar", "postId": avatar_id},
                {"role": "expression", "postId": safe_img_id, "label": "ok"},
            ],
        )
    )["post"]["id"]
    refused_card = client.post(
        f"/modules/cards/post/{nsfw_card_id}/export",
        user=user,
        body={"format": "json", "images": "links"},
    )
    assert refused_card.status_code == 400
    assert (
        "Share links for NSFW posts are disabled: 2 images are NSFW."
        in refused_card.json()["description"]
    )
    assert db.session.query(model.ShareLink).count() == 0

    # Embedded mode allows NSFW card even while share_links_nsfw is off.
    ok_embedded = client.post(
        f"/modules/cards/post/{nsfw_card_id}/export",
        user=user,
        body={"format": "json", "images": "embedded"},
    )
    assert ok_embedded.status_code == 200

    # Safe card with one NSFW image refused, 0 links created.
    mixed_card_id = ok(
        create(
            client,
            user,
            cards.v3_card(name="MixedCard"),
            images=[
                {"role": "avatar", "postId": avatar_id},
                {"role": "expression", "postId": nsfw_img_id, "label": "spicy"},
            ],
        )
    )["post"]["id"]
    refused_img = client.post(
        f"/modules/cards/post/{mixed_card_id}/export",
        user=user,
        body={"format": "json", "images": "links"},
    )
    assert refused_img.status_code == 400
    assert (
        "Share links for NSFW posts are disabled: 1 images are NSFW."
        in refused_img.json()["description"]
    )
    assert db.session.query(model.ShareLink).count() == 0

    # Refused by a format limit creates no share links either.
    monkeypatch.setitem(config.config, "max_base64_upload_size", 50)
    refused_limit = client.post(
        f"/modules/cards/post/{safe_card_id}/export",
        user=user,
        body={"format": "json", "images": "links"},
    )
    assert refused_limit.status_code == 400
    assert db.session.query(model.ShareLink).count() == 0
    monkeypatch.setitem(config.config, "max_base64_upload_size", 64 * 1024 * 1024)

    # Turning share_links_nsfw on permits the NSFW export.
    monkeypatch.setitem(config.config, "share_links_nsfw", True)
    allowed = client.post(
        f"/modules/cards/post/{nsfw_card_id}/export",
        user=user,
        body={"format": "json", "images": "links"},
    )
    assert allowed.status_code == 200
    assert db.session.query(model.ShareLink).count() == 2


def test_assets_match_by_uri_and_position_only_for_data_markers(
    client: ApiClient, user: model.User
) -> None:
    avatar_bytes = cards.picture(91)
    first_bytes = cards.picture(92)
    second_bytes = cards.picture(93)
    data_bytes = cards.picture(94)
    data_uri = f"data:image/png;base64,{base64.b64encode(data_bytes).decode('ascii')}"

    avatar_id = _upload_media(client, user, avatar_bytes)
    first_id = _upload_media(client, user, first_bytes)
    second_id = _upload_media(client, user, second_bytes)
    data_id = _upload_media(client, user, data_bytes)

    # Document assets are reordered relative to the stored CardImage positions,
    # include an unmatched URI, a marker at a non-data position, and a marker
    # at a data: URI position.
    card_payload = cards.v3_card(
        name="ReorderedAssets",
        assets=[
            {"type": "icon", "uri": "ccdefault:", "name": "main", "ext": "png"},
            {
                "type": "x-item",
                "uri": "embeded://assets/x/second.png",
                "name": "second",
                "ext": "png",
            },
            {
                "type": "x-item",
                "uri": "embeded://assets/x/missing.png",
                "name": "missing",
                "ext": "png",
            },
            {
                "type": "x-item",
                "uri": "embeded://assets/x/first.png",
                "name": "first",
                "ext": "png",
            },
            {
                "type": "x-item",
                "uri": data_uri,
                "name": "inline-data",
                "ext": "png",
            },
        ],
    )
    card_payload["data"].pop("character_book", None)
    card_id = ok(
        create(
            client,
            user,
            card_payload,
            images=[{"role": "avatar", "postId": avatar_id}],
        )
    )["post"]["id"]

    # Stored CardImage map has first at position 1, second at position 2, and
    # the data: URI at position 4.
    db.session.add_all(
        [
            CardImage(
                card_post_id=card_id,
                uri="embeded://assets/x/first.png",
                post_id=first_id,
                type="embedded-in",
                asset_type="x-item",
                label="first",
                position=1,
            ),
            CardImage(
                card_post_id=card_id,
                uri="embeded://assets/x/second.png",
                post_id=second_id,
                type="embedded-in",
                asset_type="x-item",
                label="second",
                position=2,
            ),
            CardImage(
                card_post_id=card_id,
                uri=data_uri,
                post_id=data_id,
                type="embedded-in",
                asset_type="x-item",
                label="inline-data",
                position=4,
            ),
        ]
    )
    db.session.commit()

    resp = client.post(
        f"/modules/cards/post/{card_id}/export",
        user=user,
        body={"format": "charx", "images": "embedded"},
    )
    assert resp.status_code == 200
    # Only the unmatched embeded://assets/x/missing.png entry is skipped.
    assert resp.headers["x-lithica-export-skipped"] == "1"
    with charx.opened(io.BytesIO(resp.content)) as opened:
        out_assets: list[dict[str, Any]] = opened.card["data"]["assets"]  # type: ignore[index]
        by_name = {a["name"]: a["uri"] for a in out_assets}
        assert list(by_name) == ["main", "second", "first", "inline-data"]
        assert charx.asset_bytes(opened, by_name["second"], 1024**2) == second_bytes
        assert charx.asset_bytes(opened, by_name["first"], 1024**2) == first_bytes
        assert charx.asset_bytes(opened, by_name["inline-data"], 1024**2) == data_bytes
