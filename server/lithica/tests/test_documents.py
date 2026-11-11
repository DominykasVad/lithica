"""Document history is atomic and independent of the post's metadata history."""

import json
import zlib
from collections.abc import Callable
from pathlib import Path

import pytest

from lithica import config, db, errors, model, registry
from lithica.func import documents, posts
from lithica.tests.api.http import enabled_config
from lithica.tests.fixtures.modules import dummy
from lithica.tests.fixtures.modules.dummy.model import DummyText


@pytest.fixture
def document_post(
    config_injector: Callable[..., None],
    tmp_path: Path,
    user_factory: Callable[..., model.User],
    tag_category_factory: Callable[..., model.TagCategory],
) -> tuple[model.Post, model.User]:
    config_injector(enabled_config({"data_dir": str(tmp_path)}))
    registry.use([dummy.module])
    user = user_factory()
    db.session.add(tag_category_factory(name="default", default=True))
    db.session.add(user)
    db.session.flush()
    post = posts.create_fileless_post("dummy_document", user)
    db.session.commit()
    return post, user


def test_history(document_post: tuple[model.Post, model.User]) -> None:
    post, user = document_post
    original = (post.version, post.last_edit_time)
    created = documents.create(
        post, "dummy_document", {"text": "first", "n": 1}, user, "Imported"
    )
    assert created.version == 0
    row = documents.get_version(post, 0)
    assert json.loads(zlib.decompress(row.data)) == created.data
    assert row.size == len(zlib.decompress(row.data))
    assert documents.write(post, {"n": 1, "text": "first"}, 0, user).version == 0
    assert documents.write(post, {"text": "second"}, 0, user).version == 1
    for value in ({"text": "third"}, {"text": "second"}):
        with pytest.raises(errors.IntegrityError):
            documents.write(post, value, 0, user)
    restored = documents.restore(post, 0, 1, user)
    assert restored.version == 2 and restored.data["text"] == "first"
    assert documents.get_version(post, 2).note == "Restored from version 0."
    assert documents.restore(post, 0, 2, user).version == 2
    assert (post.version, post.last_edit_time) == original
    assert db.session.query(model.Snapshot).count() == 0
    assert db.session.get(DummyText, post.post_id).text == "first"
    assert documents.list_versions(post, 1, 1, user)["results"][0]["number"] == 1
    assert documents.list_versions(post, 0, 100, user)["total"] == 3


@pytest.mark.parametrize(
    "data",
    [
        [],
        "text",
        {"text": "reject"},
        {"text": "\x00"},
        {"\x00": "value"},
        {"text": "\ud800"},
        {"text": float("nan")},
        {"text": "x" * (registry.DEFAULT_MAX_PAYLOAD_SIZE + 1)},
    ],
)
def test_invalid(document_post: tuple[model.Post, model.User], data: object) -> None:
    post, user = document_post
    with pytest.raises(errors.ValidationError):
        documents.create(post, "dummy_document", data, user)
    assert db.session.query(model.PostDocument).count() == 0
    assert db.session.query(model.PostDocumentVersion).count() == 0
    assert db.session.query(DummyText).count() == 0


@pytest.mark.parametrize("kept", [0, 1, 2])
def test_retention(document_post: tuple[model.Post, model.User], kept: int) -> None:
    post, user = document_post
    config.config["document_versions_kept"] = kept
    documents.create(post, "dummy_document", {"text": "0"}, user)
    for number in range(1, 6):
        documents.write(post, {"text": str(number)}, number - 1, user)
    expected = list(range(6)) if kept == 0 else [0, *range(6 - kept, 6)]
    assert [
        row.number
        for row in db.session.query(model.PostDocumentVersion).order_by(
            model.PostDocumentVersion.number
        )
    ] == expected
    if kept:
        with pytest.raises(documents.DocumentNotFoundError):
            documents.get_version(post, 1)


def test_rollback_and_delete(document_post: tuple[model.Post, model.User]) -> None:
    post, user = document_post
    post_id = post.post_id
    documents.create(post, "dummy_document", {"text": "first"}, user)
    db.session.commit()
    documents.write(post, {"text": "second"}, 0, user)
    db.session.rollback()
    assert documents.get(post).version == 0
    assert db.session.get(DummyText, post_id).text == "first"
    posts.delete(post)
    db.session.flush()
    assert db.session.query(model.PostDocument).count() == 0
    assert db.session.query(model.PostDocumentVersion).count() == 0


def test_unloaded(document_post: tuple[model.Post, model.User]) -> None:
    post, user = document_post
    documents.create(post, "dummy_document", {"text": "first"}, user)
    registry.use([])
    with pytest.raises(documents.DocumentNotFoundError):
        documents.get(post)
    with pytest.raises(documents.DocumentNotFoundError):
        documents.write(post, {"text": "second"}, 0, user)
    with pytest.raises(documents.DocumentNotFoundError):
        documents.restore(post, 0, 0, user)


def test_document_blocks_merge_and_kind(
    document_post: tuple[model.Post, model.User], post_factory: Callable[[], model.Post]
) -> None:
    from lithica.func import post_kinds

    post, user = document_post
    # A file-backed post can carry a document too.
    post.type, post.mime_type, post.checksum = "image", "image/png", "hash"
    documents.create(post, "dummy_document", {"text": "first"}, user)
    for reverse in (False, True):
        for replace in (False, True):
            other = post_factory()
            db.session.add(other)
            db.session.flush()
            with pytest.raises(errors.ValidationError):
                posts.merge_posts(
                    other if reverse else post, post if reverse else other, replace
                )
    with pytest.raises(errors.ValidationError):
        post_kinds.set_kind(post, "media")


def test_concurrent_writes(
    config_injector: Callable[..., None],
    tmp_path: Path,
    committing_session: None,
    user_factory: Callable[..., model.User],
    tag_category_factory: Callable[..., model.TagCategory],
) -> None:
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    config_injector(enabled_config({"data_dir": str(tmp_path)}))
    registry.use([dummy.module])
    with db.session_scope():
        user = user_factory()
        db.session.add_all([user, tag_category_factory(name="default", default=True)])
        db.session.flush()
        post = posts.create_fileless_post("dummy_document", user)
        documents.create(post, "dummy_document", {"text": "first"}, user)
        post_id, user_id = post.post_id, user.user_id
        db.session.commit()
    barrier = Barrier(2)

    def worker(text: str) -> int:
        with db.session_scope():
            post = posts.get_post_by_id(post_id)
            user = db.session.get(model.User, user_id)
            # Both read the same current version before either locks for writing.
            assert documents.get(post).version == 0
            barrier.wait(timeout=10)
            try:
                result = documents.write(post, {"text": text}, 0, user)
                db.session.commit()
                return result.version
            except errors.IntegrityError:
                db.session.rollback()
                return 409

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(worker, ["one", "two"])) == [1, 409]
    with db.session_scope():
        assert db.session.query(model.PostDocumentVersion).count() == 2


def test_lower_retention_waits_for_write(
    document_post: tuple[model.Post, model.User],
) -> None:
    post, user = document_post
    documents.create(post, "dummy_document", {"text": "0"}, user)
    for number in range(1, 4):
        documents.write(post, {"text": str(number)}, number - 1, user)
    config.config["document_versions_kept"] = 1
    assert documents.list_versions(post, 0, 100, user)["total"] == 4
    documents.write(post, {"text": "4"}, 3, user)
    assert [
        row["number"] for row in documents.list_versions(post, 0, 100, user)["results"]
    ] == [4, 0]


def test_restore_revalidates(document_post: tuple[model.Post, model.User]) -> None:
    import dataclasses

    post, user = document_post
    documents.create(post, "dummy_document", {"text": "old"}, user)
    documents.write(post, {"text": "new"}, 0, user)

    def reject_old(data: registry.Payload) -> registry.Payload:
        if data["text"] == "old":
            raise registry.DocumentRejected("Old data no longer valid.")
        return data

    kind = dataclasses.replace(dummy.module.document_kinds[0], validate=reject_old)
    registry.use([dataclasses.replace(dummy.module, document_kinds=[kind])])
    with pytest.raises(errors.ValidationError, match="Old data"):
        documents.restore(post, 0, 1, user)
    assert documents.get(post).version == 1
    assert db.session.query(model.PostDocumentVersion).count() == 2


def test_identical_write_applies_retention(
    document_post: tuple[model.Post, model.User],
) -> None:
    post, user = document_post
    documents.create(post, "dummy_document", {"text": "0"}, user)
    for number in range(1, 4):
        documents.write(post, {"text": str(number)}, number - 1, user)
    config.config["document_versions_kept"] = 1
    assert documents.write(post, {"text": "3"}, 3, user).version == 3
    assert documents.list_versions(post, 0, 100, user)["total"] == 2
