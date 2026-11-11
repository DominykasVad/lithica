"""Conversion and file/kind edits serialize on post rows across sessions."""

from collections.abc import Callable, Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from threading import Event

import pytest
import sqlalchemy as sa
import sqlalchemy.event as sa_event

from lithica import db, errors, model, registry
from lithica.func import documents, post_kinds, posts
from lithica.tests.api.http import shipped_config
from lithica.tests.fixtures.modules import dummy


@pytest.fixture
def owned_posts(
    config_injector: Callable[..., None],
    tmp_path: Path,
    committing_session: None,
    user_factory: Callable[..., model.User],
    post_factory: Callable[..., model.Post],
) -> tuple[int, int]:
    config_injector(shipped_config(str(tmp_path)))
    registry.use([dummy.module])
    with db.session_scope():
        user = user_factory()
        post, other = post_factory(), post_factory(checksum="other")
        post.user = user
        post.kind = "dummy_document"
        db.session.add_all([user, post, other])
        db.session.flush()
        ids = post.post_id, other.post_id
        db.session.commit()
    return ids


@contextmanager
def observed_lock(reached: Event) -> Iterator[None]:
    def record(
        connection: sa.Connection,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _many: bool,
    ) -> None:
        if connection.info.get("document_guard_observer") and (
            "FOR UPDATE" in statement or statement.upper().startswith("UPDATE POST")
        ):
            reached.set()

    sa_event.listen(sa.engine.Engine, "before_cursor_execute", record)
    try:
        yield
    finally:
        sa_event.remove(sa.engine.Engine, "before_cursor_execute", record)


@pytest.mark.parametrize("operation", ["kind", "file", "derive", "merge"])
def test_creation_blocks_edits(
    owned_posts: tuple[int, int],
    read_asset: Callable[[str], bytes],
    operation: str,
) -> None:
    post_id, other_id = owned_posts
    ready, release, reached = Event(), Event(), Event()

    def create() -> None:
        with db.session_scope():
            post = db.session.get(model.Post, post_id)
            assert post is not None
            documents.create(post, "dummy_document", {"text": "original"}, None)
            ready.set()
            assert release.wait(10)
            db.session.commit()

    def edit() -> str:
        with db.session_scope():
            info = db.session.connection().info
            info["document_guard_observer"] = True
            try:
                post = db.session.get(model.Post, post_id)
                assert post is not None
                try:
                    if operation == "kind":
                        post_kinds.set_kind(post, "media")
                    elif operation == "file":
                        posts.update_post_content(post, read_asset("png.png"))
                    elif operation == "derive":
                        post_kinds.derive_existing(post)
                        if post.kind == "dummy_document":
                            return "refused"
                    else:
                        other = db.session.get(model.Post, other_id)
                        assert other is not None
                        posts.merge_posts(other, post, False)
                except errors.ValidationError:
                    return "refused"
                db.session.flush()
                db.session.commit()
                return "changed"
            finally:
                info.pop("document_guard_observer", None)
                reached.set()

    with observed_lock(reached), ThreadPoolExecutor(max_workers=2) as pool:
        creator = pool.submit(create)
        editor: Future[str] | None = None
        try:
            assert ready.wait(10)
            editor = pool.submit(edit)
            assert reached.wait(10)
        finally:
            release.set()
        creator.result()
        assert editor is not None and editor.result() == "refused"
    with db.session_scope():
        assert db.session.get(model.Post, post_id).kind == "dummy_document"
        assert db.session.get(model.PostDocument, post_id).kind == "dummy_document"
        assert db.session.get(model.Post, other_id) is not None


def test_creation_rechecks_kind_after_wait(owned_posts: tuple[int, int]) -> None:
    post_id, _ = owned_posts
    ready, release, reached = Event(), Event(), Event()

    def edit() -> None:
        with db.session_scope():
            post = db.session.get(model.Post, post_id)
            assert post is not None
            assert post_kinds.set_kind(post, "media")
            db.session.flush()
            ready.set()
            assert release.wait(10)
            db.session.commit()

    def create() -> str:
        with db.session_scope():
            info = db.session.connection().info
            info["document_guard_observer"] = True
            try:
                post = db.session.get(model.Post, post_id)
                assert post is not None and post.kind == "dummy_document"
                try:
                    documents.create(post, "dummy_document", {"text": "old"}, None)
                except errors.ValidationError:
                    return "refused"
                db.session.commit()
                return "created"
            finally:
                info.pop("document_guard_observer", None)
                reached.set()

    with observed_lock(reached), ThreadPoolExecutor(max_workers=2) as pool:
        editor = pool.submit(edit)
        creator: Future[str] | None = None
        try:
            assert ready.wait(10)
            creator = pool.submit(create)
            assert reached.wait(10)
        finally:
            release.set()
        editor.result()
        assert creator is not None and creator.result() == "refused"
    with db.session_scope():
        assert db.session.get(model.PostDocument, post_id) is None
        assert db.session.get(model.Post, post_id).kind == "media"
