"""Data imports inherit metadata only after acquiring the post writer lock."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
import sqlalchemy as sa
import sqlalchemy.event as sa_event

from lithica import config, db, model
from lithica.func import documents, file_uploads, post_metadata, posts, visibility
from lithica.modules.cards import data_creation, media, related_images
from lithica.tests.modules import cards
from lithica.tests.modules.test_card_file_replace_concurrency import (
    _observe_lock,
    committed_card,  # noqa: F401
)


def test_update_inherits_metadata_after_waiting(
    committed_card: tuple[int, int, int],  # noqa: F811
) -> None:
    post_id, user_id, _version = committed_card
    with db.session_scope():
        user = db.session.get(model.User, user_id)
        assert user is not None
        post_metadata.replace_external_ids(
            posts.get_post_by_id(post_id), [("test", "concurrent")], user
        )
        uploaded = file_uploads.save(cards.picture(80))
        db.session.commit()
    ready, release, reached = Event(), Event(), Event()

    def edit_metadata() -> None:
        with db.session_scope():
            post = posts.get_post_by_id(post_id)
            db.session.execute(
                sa.select(model.Post.post_id)
                .where(model.Post.post_id == post_id)
                .with_for_update()
            )
            post.safety = "unsafe"
            posts.update_post_tags(post, ["nsfw"])
            db.session.flush()
            ready.set()
            assert release.wait(15)
            db.session.commit()

    def import_data() -> int:
        assert ready.wait(15)
        with db.session_scope():
            post = posts.get_post_by_id(post_id)
            assert post.safety == "safe"
            user = db.session.get(model.User, user_id)
            assert user is not None
            prepared = related_images.prepare(
                [related_images.Image("avatar", token=uploaded)], user
            )
            info = db.session.connection().info
            info["card_replace_observer"] = True
            try:
                updated, outcome, skipped, created = data_creation.create_card(
                    cards.v2_card(name="After"),
                    user,
                    data_creation.Options(external_ids=[("test", "concurrent")]),
                    [],
                    prepared,
                )
                assert outcome == "updated" and not skipped
                media.release(created)
                avatar = documents.get(updated).data["avatar"]
                db.session.commit()
                return avatar
            finally:
                info.pop("card_replace_observer", None)

    observer = _observe_lock(reached)
    sa_event.listen(sa.engine.Engine, "before_cursor_execute", observer)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            editor = pool.submit(edit_metadata)
            try:
                importer = pool.submit(import_data)
                assert reached.wait(15)
            finally:
                release.set()
            editor.result(20)
            avatar_id = importer.result(20)
    finally:
        sa_event.remove(sa.engine.Engine, "before_cursor_execute", observer)
    with db.session_scope():
        post = posts.get_post_by_id(post_id)
        image = posts.get_post_by_id(avatar_id)
        book = posts.get_post_by_id(documents.get(post).data["lorebooks"][0])
        assert image.safety == book.safety == "unsafe"
        assert visibility.is_nsfw(image) and visibility.is_nsfw(book)


def test_document_lock_rechecks_visibility_after_new_nsfw_tag(
    committed_card: tuple[int, int, int],  # noqa: F811
) -> None:
    post_id, _user_id, _version = committed_card
    config.config["visibility"] = "nsfw-login"
    ready, release, reached = Event(), Event(), Event()

    def hide_post() -> None:
        with db.session_scope():
            post = posts.get_post_by_id(post_id)
            db.session.execute(
                sa.select(model.Post.post_id)
                .where(model.Post.post_id == post_id)
                .with_for_update()
            )
            posts.update_post_tags(post, ["nsfw"])
            db.session.flush()
            ready.set()
            assert release.wait(15)
            db.session.commit()

    def document_request() -> None:
        assert ready.wait(15)
        with db.session_scope():
            visibility.begin_request()
            visibility.set_viewer(model.User(rank=model.User.RANK_ANONYMOUS))
            post = posts.get_post_by_id(post_id)
            assert not visibility.hiding_tag_ids()
            info = db.session.connection().info
            info["card_replace_observer"] = True
            try:
                with pytest.raises(documents.DocumentNotFoundError):
                    documents.get(post, lock=True)
                assert not any(
                    isinstance(row, model.PostDocument)
                    for row in db.session.identity_map.values()
                )
            finally:
                info.pop("card_replace_observer", None)
                db.session.rollback()

    observer = _observe_lock(reached)
    sa_event.listen(sa.engine.Engine, "before_cursor_execute", observer)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            editor = pool.submit(hide_post)
            try:
                reader = pool.submit(document_request)
                assert reached.wait(15)
            finally:
                release.set()
            editor.result(20)
            reader.result(20)
    finally:
        sa_event.remove(sa.engine.Engine, "before_cursor_execute", observer)
