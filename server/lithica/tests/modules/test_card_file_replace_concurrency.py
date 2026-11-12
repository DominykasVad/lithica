"""File replacement shares the post lock with conversion and kind changes."""

from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from threading import Event

import pytest
import sqlalchemy as sa
import sqlalchemy.event as sa_event

from lithica import db, errors, model, registry
from lithica.func import documents, post_kinds, posts, snapshots, versions
from lithica.modules.cards import replacement, uploads
from lithica.tests.api.http import shipped_config
from lithica.tests.modules import cards


@pytest.fixture
def committed_card(
    config_injector: Callable[..., None],
    tmp_path: Path,
    committing_session: None,
    user_factory: Callable[..., model.User],
    tag_category_factory: Callable[..., model.TagCategory],
) -> tuple[int, int, int]:
    config_injector(shipped_config(str(tmp_path), modules=["cards"]))
    registry.load_configured()
    with db.session_scope():
        user = user_factory(rank=model.User.RANK_ADMINISTRATOR)
        db.session.add_all([user, tag_category_factory(name="default", default=True)])
        db.session.flush()
        post, _ = posts.create_post(
            cards.png_card(cards.v2_card(name="Before")), [], user
        )
        db.session.flush()
        uploads.convert(post, user)
        snapshots.create(post, user)
        result = post.post_id, user.user_id, post.version
        db.session.commit()
    return result


def _observe_lock(reached: Event) -> Callable[..., None]:
    def record(
        connection: sa.Connection,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _many: bool,
    ) -> None:
        if connection.info.get("card_replace_observer") and "FOR UPDATE" in statement:
            reached.set()

    return record


def test_replacement_verifies_version_after_waiting_for_post_lock(
    committed_card: tuple[int, int, int],
) -> None:
    post_id, user_id, version = committed_card
    ready, release, reached = Event(), Event(), Event()
    new_file = cards.png_card(cards.v2_card(name="After"), shade=1)

    def edit() -> None:
        with db.session_scope():
            post = posts.get_post_by_id(post_id)
            db.session.execute(
                sa.select(model.Post.post_id)
                .where(model.Post.post_id == post_id)
                .with_for_update()
            )
            versions.bump_version(post)
            db.session.flush()
            ready.set()
            assert release.wait(10)
            db.session.commit()

    def replace_stale() -> None:
        with db.session_scope():
            post = posts.get_post_by_id(post_id)
            user = db.session.get(model.User, user_id)
            assert user is not None and post.version == version
            info = db.session.connection().info
            info["card_replace_observer"] = True
            try:
                with pytest.raises(errors.IntegrityError):
                    replacement.replace(post, new_file, version, False, user)
                db.session.rollback()
            finally:
                info.pop("card_replace_observer", None)

    observer = _observe_lock(reached)
    sa_event.listen(sa.engine.Engine, "before_cursor_execute", observer)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            editor = pool.submit(edit)
            replacer: Future[None] | None = None
            try:
                assert ready.wait(10)
                replacer = pool.submit(replace_stale)
                assert reached.wait(10)
                assert not replacer.done()
            finally:
                release.set()
            editor.result()
            assert replacer is not None
            replacer.result()
    finally:
        sa_event.remove(sa.engine.Engine, "before_cursor_execute", observer)
    with db.session_scope():
        post = posts.get_post_by_id(post_id)
        assert post.version == version + 1
        document = documents.get(post)
        assert (
            document.version == 0 and document.data["card"]["data"]["name"] == "Before"
        )
        assert posts.search_by_image_exact(new_file) is None


@pytest.mark.parametrize("operation", ["convert", "kind"])
def test_conversion_and_kind_change_wait_for_replacement(
    committed_card: tuple[int, int, int], operation: str
) -> None:
    post_id, user_id, version = committed_card
    ready, release, reached = Event(), Event(), Event()
    new_file = cards.png_card(cards.v2_card(name="After"), shade=1)

    def replace() -> None:
        with db.session_scope():
            post = posts.get_post_by_id(post_id)
            user = db.session.get(model.User, user_id)
            assert user is not None
            replacement.replace(post, new_file, version, False, user)
            ready.set()
            assert release.wait(10)
            db.session.commit()

    def contend() -> None:
        with db.session_scope():
            post = posts.get_post_by_id(post_id)
            assert post.version == version
            info = db.session.connection().info
            info["card_replace_observer"] = True
            try:
                if operation == "convert":
                    uploads.convert(post, post.user)
                    document = documents.get(post)
                    assert document.version == 1
                    assert document.data["card"]["data"]["name"] == "After"
                    db.session.commit()
                else:
                    with pytest.raises(post_kinds.InvalidPostKindError):
                        post_kinds.set_kind(post, "media")
                    db.session.rollback()
            finally:
                info.pop("card_replace_observer", None)

    observer = _observe_lock(reached)
    sa_event.listen(sa.engine.Engine, "before_cursor_execute", observer)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            replacer = pool.submit(replace)
            contender: Future[None] | None = None
            try:
                assert ready.wait(10)
                contender = pool.submit(contend)
                assert reached.wait(10)
                assert not contender.done()
            finally:
                release.set()
            replacer.result()
            assert contender is not None
            contender.result()
    finally:
        sa_event.remove(sa.engine.Engine, "before_cursor_execute", observer)
    with db.session_scope():
        post = posts.get_post_by_id(post_id)
        assert post.kind == "card" and post.version == version + 1
        document = documents.get(post)
        assert document.version == 1
        assert document.data["card"]["data"]["name"] == "After"
        assert (
            db.session.query(model.PostDocument).filter_by(post_id=post_id).count() == 1
        )
        assert (
            db.session.query(model.PostDocumentVersion)
            .filter_by(post_id=post_id)
            .count()
            == 2
        )
