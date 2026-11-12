"""Replacement preserves book history and applies picture policy atomically."""

import json
import zlib
from collections.abc import Callable, Iterable
from dataclasses import replace as replace_dataclass
from pathlib import Path
from typing import BinaryIO

import pytest

from lithica import config, db, errors, model, registry
from lithica.func import documents, post_metadata, posts, util
from lithica.tests.api.http import ok
from lithica.tests.api.test_tokens import _app_token, _as
from lithica.tests.conftest import ApiClient
from lithica.tests.modules import cards
from lithica.tests.modules.test_card_file_replace import replace
from lithica.tests.modules.test_card_upload_documents import upload

Site = Callable[[list[str]], ApiClient]


@pytest.fixture(autouse=True)
def picture_privilege(site: Site) -> None:
    config.config["privileges"]["posts:edit:typed_relations"] = "regular"


def _disk() -> dict[str, bytes]:
    root = Path(config.config["data_dir"])
    return {
        str(path.relative_to(root)): path.read_bytes()
        for folder in ("posts", "generated-thumbnails")
        for path in (root / folder).rglob("*")
        if path.is_file()
    }


def _charx(client: ApiClient, user: model.User, icon: bytes | None) -> int:
    return ok(
        client.post(
            "/posts",
            user=user,
            body={"safety": "safe"},
            files={"content": cards.charx(icon=icon)},
        )
    )["id"]


def _media(
    client: ApiClient, user: model.User, content: bytes, tags: list[str] | None = None
) -> int:
    return ok(
        client.post(
            "/posts",
            user=user,
            body={"safety": "unsafe", "tags": tags or []},
            files={"content": content},
        )
    )["id"]


@pytest.mark.parametrize("book", ["shared", "new", "none"])
def test_replace_book_links_and_version_zero(
    site: Site, user: model.User, book: str
) -> None:
    client = site(["cards"])
    post_id = upload(client, user, cards.v2_card())
    post = posts.get_post_by_id(post_id)
    original_book = documents.get(post).data["lorebooks"][0]
    original_version = documents.get_version(post, 0).data
    new_book = (
        dict(cards.LOREBOOK, name="New coast") if book == "new" else cards.LOREBOOK
    )
    if book == "none":
        new_book = {}
    ok(
        replace(
            client,
            user,
            post_id,
            cards.png_card(cards.v2_card(name="New", character_book=new_book)),
        )
    )
    current = documents.get(post).data["lorebooks"]
    if book == "shared":
        assert current == [original_book]
    elif book == "new":
        assert len(current) == 1 and current[0] != original_book
        assert (
            documents.get(posts.get_post_by_id(current[0])).data["book"]["name"]
            == "New coast"
        )
    else:
        assert current == []
    assert documents.get_version(post, 0).data == original_version
    assert json.loads(zlib.decompress(original_version))["lorebooks"] == [original_book]
    assert posts.get_post_by_id(original_book).kind == "lorebook"


def test_replacement_book_uses_nsfw_side_and_inherits_safety(
    site: Site, user: model.User
) -> None:
    client = site(["cards"])
    safe_id = upload(client, user, cards.v2_card(name="Safe"), shade=1)
    hidden_id = upload(
        client,
        user,
        cards.v2_card(name="Hidden", character_book={}),
        tags=["nsfw"],
        safety="unsafe",
        shade=2,
    )
    safe_book = documents.get(posts.get_post_by_id(safe_id)).data["lorebooks"][0]
    ok(
        replace(
            client,
            user,
            hidden_id,
            cards.png_card(cards.v2_card(name="Hidden new"), shade=2),
        )
    )
    hidden_book = documents.get(posts.get_post_by_id(hidden_id)).data["lorebooks"][0]
    assert hidden_book != safe_book
    book = posts.get_post_by_id(hidden_book)
    assert book.safety == "unsafe" and [tag.first_name for tag in book.tags] == ["nsfw"]
    assert posts.get_post_by_id(safe_book).safety == "safe"


@pytest.mark.parametrize(
    "keep,shade,status", [(True, 0, 200), (False, 80, 200), (True, 80, 403)]
)
def test_typed_relation_privilege_only_when_preserving_picture(
    site: Site, user: model.User, keep: bool, shade: int, status: int
) -> None:
    client = site(["cards"])
    config.config["privileges"]["posts:edit:typed_relations"] = "administrator"
    post_id = upload(client, user, cards.v2_card())
    before = _disk()
    response = replace(
        client,
        user,
        post_id,
        cards.png_card(cards.v2_card(name="New"), shade=shade),
        keepOldPicture=keep,
    )
    assert response.status_code == status, response.text
    if status == 403:
        assert _disk() == before
        assert documents.get(posts.get_post_by_id(post_id)).version == 0


def test_charx_without_icon_needs_no_relation_privilege(
    site: Site, user: model.User
) -> None:
    client = site(["cards"])
    config.config["privileges"]["posts:edit:typed_relations"] = "administrator"
    post_id = _charx(client, user, None)
    answer = ok(
        replace(client, user, post_id, cards.png_card(cards.v2_card(), shade=80))
    )
    assert answer["keptPostId"] is None and not answer["samePicture"]


def test_write_app_token_replaces_and_keeps_picture(
    site: Site, user: model.User
) -> None:
    client = site(["cards"])
    config.config["privileges"]["app_tokens:create:self"] = "regular"
    post_id = upload(client, user, cards.v2_card())
    headers = _as(_app_token(client, user, ["write"]), user)
    answer = ok(
        client.put(
            f"/modules/cards/post/{post_id}/file",
            headers=headers,
            body={"version": 1},
            files={"content": cards.png_card(cards.v2_card(name="New"), shade=80)},
        )
    )
    assert answer["keptPostId"] is not None
    assert documents.get(posts.get_post_by_id(post_id)).version == 1


def test_existing_icon_is_linked_without_changing_fields_or_duplicate_relation(
    site: Site, user: model.User
) -> None:
    client = site(["cards"])
    icon = cards.picture(30)
    icon_id = _media(client, user, icon, ["manual"])
    icon_post = posts.get_post_by_id(icon_id)
    fields = (icon_post.version, icon_post.listed, icon_post.safety, icon_post.user_id)
    post_id = _charx(client, user, icon)
    post_metadata.create_typed_relation(icon_id, post_id, "avatar-of", None, user)
    db.session.commit()
    count = db.session.query(model.Post).filter_by(kind="media").count()
    answer = ok(
        replace(client, user, post_id, cards.png_card(cards.v2_card(), shade=80))
    )
    assert answer["keptPostId"] == icon_id
    assert db.session.query(model.Post).filter_by(kind="media").count() == count
    assert (
        icon_post.version,
        icon_post.listed,
        icon_post.safety,
        icon_post.user_id,
    ) == fields
    assert [tag.first_name for tag in icon_post.tags] == ["manual"]
    rows = (
        db.session.query(model.PostTypedRelation).filter_by(from_post_id=icon_id).all()
    )
    assert {(row.to_post_id, row.type) for row in rows} == {
        (post_id, "avatar-of"),
        (post_id, "gallery-of"),
    }


def test_existing_nonmedia_icon_is_not_kept(site: Site, user: model.User) -> None:
    client = site(["cards"])
    icon = cards.png_card(cards.v2_card(name="Icon"), shade=30)
    icon_id = _media(client, user, icon)
    assert posts.get_post_by_id(icon_id).kind == "card"
    post_id = _charx(client, user, icon)
    answer = ok(
        replace(client, user, post_id, cards.png_card(cards.v2_card(), shade=80))
    )
    assert answer["keptPostId"] is None
    assert db.session.query(model.PostTypedRelation).count() == 0


def test_existing_hidden_icon_is_skipped(
    site: Site, user: model.User, user_factory: Callable[..., model.User]
) -> None:
    client = site(["cards"])
    icon = cards.picture(30)
    icon_id = _media(client, user, icon, ["nsfw"])
    post_id = _charx(client, user, icon)
    config.config["visibility"] = "nsfw-login"
    config.config["privileges"]["posts:edit:content"] = "anonymous"
    config.config["privileges"]["posts:edit:typed_relations"] = "administrator"
    anonymous = user_factory(rank=model.User.RANK_ANONYMOUS)
    answer = ok(
        replace(
            client,
            anonymous,
            post_id,
            cards.png_card(cards.v2_card(), shade=80),
        )
    )
    assert answer["keptPostId"] is None
    assert (
        db.session.query(model.PostTypedRelation)
        .filter_by(from_post_id=icon_id)
        .count()
        == 0
    )


@pytest.mark.parametrize("failure", ["hook", "extractor", "reject"])
def test_failure_before_storage_keeps_database_and_disk(
    site: Site, user: model.User, failure: str
) -> None:
    client = site(["cards"])
    post_id = upload(client, user, cards.v2_card())
    before = _disk()
    counts = (
        db.session.query(model.Post).count(),
        db.session.query(model.Snapshot).count(),
    )
    modules = registry.modules()

    def fail_write(_post_id: int, _data: registry.Payload) -> None:
        raise errors.ValidationError("Version hook refused.")

    def fail_extract(
        _mime: str, _handle: BinaryIO
    ) -> Iterable[registry.ExtractedContent]:
        if failure == "reject":
            raise registry.FileRejected("File refused.")
        raise RuntimeError("Extractor failed.")

    if failure == "hook":
        changed = [
            replace_dataclass(
                module,
                document_kinds=[
                    replace_dataclass(kind, after_write=fail_write)
                    if kind.name == "card"
                    else kind
                    for kind in module.document_kinds
                ],
            )
            for module in modules
        ]
    else:
        changed = [
            replace_dataclass(
                module,
                extractors=[
                    replace_dataclass(extractor, extract=fail_extract)
                    for extractor in module.extractors
                ],
            )
            for module in modules
        ]
    registry.use(changed)
    response = replace(
        client,
        user,
        post_id,
        cards.png_card(cards.v2_card(name="New"), shade=80),
    )
    assert response.status_code == 400, response.text
    post = posts.get_post_by_id(post_id)
    assert post.version == 1 and documents.get(post).version == 0
    assert _disk() == before
    assert (
        db.session.query(model.Post).count(),
        db.session.query(model.Snapshot).count(),
    ) == counts
    assert db.session.query(model.PostRetiredChecksum).count() == 0


def test_unconverted_card_replacement_is_not_found(
    site: Site, user: model.User
) -> None:
    client = site(["cards"])
    registry.use(
        [
            replace_dataclass(module, after_file_or_kind=None)
            for module in registry.modules()
        ]
    )
    post_id = upload(client, user, cards.v2_card())
    assert db.session.get(model.PostDocument, post_id) is None
    before = _disk()
    response = replace(
        client, user, post_id, cards.png_card(cards.v2_card(name="New"), shade=80)
    )
    assert response.status_code == 404
    assert response.json()["name"] == "CardNotFoundError"
    assert _disk() == before


def test_retired_file_replacement_is_refused(site: Site, user: model.User) -> None:
    client = site(["cards"])
    post_id = upload(client, user, cards.v2_card())
    other_id = _media(client, user, cards.picture(30))
    new = cards.png_card(cards.v2_card(name="New"), shade=80)
    posts.retire_checksum(
        posts.get_post_by_id(other_id), util.get_sha1(new), "replaced"
    )
    db.session.commit()
    before = _disk()
    response = replace(client, user, post_id, new)
    assert response.status_code == 400
    assert response.json()["otherPostId"] == other_id
    assert _disk() == before
    assert documents.get(posts.get_post_by_id(post_id)).version == 0


@pytest.mark.parametrize("hidden", [False, True])
def test_retired_icon_is_skipped_without_exposing_its_owner(
    site: Site,
    user: model.User,
    user_factory: Callable[..., model.User],
    hidden: bool,
) -> None:
    client = site(["cards"])
    icon = cards.picture(30)
    owner_id = _media(client, user, cards.picture(60), ["nsfw"] if hidden else [])
    post_id = _charx(client, user, icon)
    original_checksum = posts.get_post_by_id(post_id).checksum
    posts.retire_checksum(
        posts.get_post_by_id(owner_id), util.get_sha1(icon), "replaced"
    )
    db.session.commit()
    count = db.session.query(model.Post).count()
    actor = user
    if hidden:
        config.config["privileges"]["posts:edit:typed_relations"] = "administrator"
        config.config["visibility"] = "nsfw-login"
        config.config["privileges"]["posts:edit:content"] = "anonymous"
        actor = user_factory(rank=model.User.RANK_ANONYMOUS)
    content = cards.png_card(cards.v3_card(name="Replacement"), shade=80)
    answer = ok(replace(client, actor, post_id, content))
    assert set(answer) == {"post", "keptPostId", "samePicture"}
    assert answer["post"]["id"] == post_id
    assert answer["keptPostId"] is None
    assert answer["samePicture"] is False
    assert db.session.query(model.Post).count() == count
    assert db.session.query(model.PostTypedRelation).count() == 0
    post = posts.get_post_by_id(post_id)
    assert post.version == 2 and documents.get(post).version == 1
    assert (
        db.session.get(model.PostRetiredChecksum, util.get_sha1(icon)).post_id
        == owner_id
    )
    retired_original = db.session.get(model.PostRetiredChecksum, original_checksum)
    assert retired_original.post_id == post_id and retired_original.reason == "replaced"
