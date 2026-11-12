"""Documents split uploaded books and keep current projections in step."""

from collections.abc import Callable
from copy import deepcopy
from pathlib import Path

import pytest

from lithica import db, model
from lithica.func import documents, posts
from lithica.modules.cards.model import Card, CardLorebook, Lorebook
from lithica.tests.api.http import ok
from lithica.tests.conftest import ApiClient
from lithica.tests.modules import cards


def upload(client, user, card, *, safety="safe", tags=(), shade=0):
    return ok(
        client.post(
            "/posts",
            user=user,
            body={"safety": safety, "tags": list(tags)},
            files={"content": cards.png_card(card, shade=shade)},
        )
    )["id"]


@pytest.mark.parametrize("card", [cards.V1_CARD, cards.v2_card(), cards.v3_card()])
def test_upload_document(site, user, card):
    client = site(["cards"])
    post_id = upload(client, user, card)
    post = posts.get_post_by_id(post_id)
    data = documents.get(post).data
    assert data["spec"] in ("card_v1", "card_v2", "card_v3")
    assert "character_book" not in data["card"].get("data", data["card"])
    assert documents.get_version(post, 0).note == "Read from the file."
    assert db.session.get(Card, post_id).name == "Ada"
    assert len(data["lorebooks"]) == (0 if card is cards.V1_CARD else 1)
    if data["lorebooks"]:
        book_id = data["lorebooks"][0]
        assert db.session.get(Lorebook, book_id).entries == 2
        assert (
            documents.get(posts.get_post_by_id(book_id)).data["book"] == cards.LOREBOOK
        )
        assert [r.lorebook_post_id for r in db.session.query(CardLorebook)] == [book_id]


def test_books_share_by_nsfw_and_raise_safety(site, user):
    client = site(["cards"])
    ids = [
        upload(
            client, user, cards.v2_card(name=str(i)), safety=safety, tags=tags, shade=i
        )
        for i, (safety, tags) in enumerate(
            [("safe", []), ("unsafe", []), ("sketchy", []), ("safe", ["nsfw"])]
        )
    ]
    linked = [documents.get(posts.get_post_by_id(i)).data["lorebooks"][0] for i in ids]
    assert linked[0] == linked[1] == linked[2] != linked[3]
    assert posts.get_post_by_id(linked[0]).safety == "unsafe"
    assert db.session.query(Lorebook).count() == 2
    assert [t.names[0].name for t in posts.get_post_by_id(linked[3]).tags] == ["nsfw"]


def test_book_lookup_uses_document_encoding(
    site: Callable[[list[str]], ApiClient],
    user: model.User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = site(["cards"])
    encode = documents.encode_content

    def changed_encoding(data: object) -> bytes:
        # Simulate an engine encoding change without changing document data.
        return encode(data) + b"\n"

    monkeypatch.setattr(documents, "encode_content", changed_encoding)
    ids = [upload(client, user, cards.v2_card(name=str(i)), shade=i) for i in range(2)]
    linked = [documents.get(posts.get_post_by_id(i)).data["lorebooks"] for i in ids]
    assert linked[0] == linked[1] and len(linked[0]) == 1
    assert db.session.query(Lorebook).count() == 1


def test_empty_book(site, user):
    client = site(["cards"])
    post_id = upload(client, user, cards.v2_card(character_book={}))
    assert documents.get(posts.get_post_by_id(post_id)).data["lorebooks"] == []
    assert db.session.query(Lorebook).count() == 0


def test_restore_drops_deleted_book(site, user):
    client = site(["cards"])
    post_id = upload(client, user, cards.v2_card())
    post = posts.get_post_by_id(post_id)
    original = deepcopy(documents.get(post).data)
    changed = deepcopy(original)
    changed["card"]["data"]["creator"] = "changed"
    documents.write(post, changed, 0, user)
    book = posts.get_post_by_id(original["lorebooks"][0])
    db.session.delete(book)
    db.session.flush()
    restored = documents.restore(post, 0, 1, user)
    assert restored.data["lorebooks"] == []
    assert db.session.query(CardLorebook).count() == 0
    assert db.session.get(Card, post_id).creator == "somebody"


def test_charx_document(site, user):
    client = site(["cards"])
    post_id = ok(
        client.post(
            "/posts",
            user=user,
            body={"safety": "safe"},
            files={"content": cards.charx()},
        )
    )["id"]
    post = posts.get_post_by_id(post_id)
    data = documents.get(post).data
    assert data["spec"] == "card_v3"
    assert "character_book" not in data["card"]["data"]
    assert documents.get_version(post, 0).number == 0
    assert len(data["lorebooks"]) == 1


def test_anonymous_nsfw_tag_created_during_upload(site, user_factory):
    from lithica import config, model

    client = site(["cards"])
    config.config["visibility"] = "nsfw-login"
    config.config["privileges"].update(
        {"posts:create:anonymous": "anonymous", "tags:create": "anonymous"}
    )
    anonymous = user_factory(rank=model.User.RANK_ANONYMOUS)
    result = ok(
        client.post(
            "/posts",
            user=anonymous,
            body={"safety": "safe", "tags": ["nsfw"], "anonymous": True},
            files={"content": cards.png_card(cards.v2_card())},
        )
    )
    # End request visibility before inspecting a deliberately hidden upload.
    from lithica.func import visibility

    visibility.set_viewer(user_factory(rank=model.User.RANK_ADMINISTRATOR))
    post = posts.get_post_by_id(result["id"])
    book_id = documents.get(post).data["lorebooks"][0]
    assert visibility.is_nsfw(posts.get_post_by_id(book_id))


def test_document_owns_uploaded_card_kind_and_file(site, user):
    from lithica import config

    client = site(["cards"])
    config.config["privileges"]["posts:edit:kind"] = "regular"
    post_id = upload(client, user, cards.v2_card())
    post = posts.get_post_by_id(post_id)
    kind = client.put(
        f"/post/{post_id}/kind",
        user=user,
        body={"version": post.version, "kind": "media"},
    )
    assert kind.status_code == 400
    assert kind.json()["name"] == "InvalidPostKindError"
    replacement = client.put(
        f"/post/{post_id}",
        user=user,
        body={"version": post.version},
        files={"content": cards.picture(shade=99)},
    )
    assert replacement.status_code == 400
    assert (
        replacement.json()["description"]
        == "Replacing the file of a post with a document comes later."
    )
    assert documents.get(post).version == 0


def test_conversion_reads_metadata_after_waiting_for_post_lock(
    config_injector: Callable[..., None],
    tmp_path: Path,
    committing_session: None,
    user_factory: Callable[..., model.User],
    tag_category_factory: Callable[..., model.TagCategory],
) -> None:
    from concurrent.futures import Future, ThreadPoolExecutor
    from threading import Event

    import sqlalchemy as sa
    import sqlalchemy.event as sa_event

    from lithica import registry
    from lithica.func import util, visibility
    from lithica.modules.cards import uploads
    from lithica.tests.api.http import shipped_config

    config_injector(shipped_config(str(tmp_path), modules=["cards"]))
    registry.load_configured()
    with db.session_scope():
        user = user_factory()
        db.session.add_all([user, tag_category_factory(name="default", default=True)])
        db.session.flush()
        post = posts.create_fileless_post("card", user)
        post.contents = [
            model.PostContent(
                kind="card_v2",
                schema_version=3,
                extracted_at=util.utcnow(),
                payload={"card": cards.v2_card(), "format": "png"},
            )
        ]
        db.session.flush()
        post_id = post.post_id
        db.session.commit()
    ready, release, reached = Event(), Event(), Event()

    def record(
        connection: sa.Connection,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _many: bool,
    ) -> None:
        if (
            connection.info.get("card_conversion_observer")
            and "FOR UPDATE" in statement
        ):
            reached.set()

    def edit() -> None:
        with db.session_scope():
            post = db.session.get(model.Post, post_id)
            assert post is not None
            db.session.execute(
                sa.select(model.Post.post_id)
                .where(model.Post.post_id == post_id)
                .with_for_update()
            )
            posts.update_post_safety(post, "unsafe")
            posts.update_post_tags(post, ["nsfw"])
            db.session.flush()
            ready.set()
            assert release.wait(10)
            db.session.commit()

    def convert() -> None:
        with db.session_scope():
            post = db.session.get(model.Post, post_id)
            assert post is not None and post.safety == "safe" and not post.tags
            info = db.session.connection().info
            info["card_conversion_observer"] = True
            try:
                uploads.convert(post, post.user)
                db.session.commit()
            finally:
                info.pop("card_conversion_observer", None)

    sa_event.listen(sa.engine.Engine, "before_cursor_execute", record)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            editor = pool.submit(edit)
            converter: Future[None] | None = None
            try:
                assert ready.wait(10)
                converter = pool.submit(convert)
                assert reached.wait(10)
            finally:
                release.set()
            editor.result()
            assert converter is not None
            converter.result()
    finally:
        sa_event.remove(sa.engine.Engine, "before_cursor_execute", record)
    with db.session_scope():
        document = db.session.get(model.PostDocument, post_id)
        assert document is not None
        book = db.session.get(model.Post, document.data["lorebooks"][0])
        assert book is not None and book.safety == "unsafe"
        assert visibility.is_nsfw(book)
        assert {tag.first_name for tag in book.tags} == {"nsfw"}
