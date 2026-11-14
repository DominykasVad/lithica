"""Module hooks isolate partial writes without swallowing caller failures."""

import logging
from dataclasses import replace

import pytest

from lithica import db, model, registry
from lithica.func import documents, post_content, post_kinds, posts
from lithica.tests.fixtures.modules import dummy
from lithica.tests.fixtures.modules.dummy.model import DummyHook


def test_hook_savepoint(post_factory, user_factory, caplog):
    caplog.set_level(logging.WARNING, logger=post_content.__name__)
    post, user = post_factory(), user_factory()
    db.session.add_all([post, user])
    registry.use([dummy.module])
    post_content.after_file_or_kind(post, user)
    db.session.commit()
    assert db.session.get(DummyHook, post.post_id).user_id == user.user_id
    db.session.delete(db.session.get(DummyHook, post.post_id))
    db.session.commit()

    def fail(post: model.Post, user: model.User | None) -> None:
        dummy.after_file_or_kind(post, user)
        db.session.flush()
        post.source = "secret card text"
        raise ValueError("secret card text")

    registry.use([replace(dummy.module, after_file_or_kind=fail)])
    post.source = "caller writes"
    post_content.after_file_or_kind(post, user)
    db.session.commit()
    assert db.session.get(DummyHook, post.post_id) is None
    assert post.source == "caller writes"
    assert "ValueError" in caplog.text
    assert "secret card text" not in caplog.text


def test_document_kind_and_content_rules(post_factory):
    registry.use([dummy.module])
    post = post_factory()
    post.kind = "dummy_document"
    db.session.add(post)
    db.session.flush()
    documents.create(post, "dummy_document", {"text": "original"}, None)
    post_kinds.derive_existing(post)
    assert post.kind == "dummy_document"
    post_content.reextract_post_contents(post, b"not a dummy file")
    assert post.kind == "dummy_document"
    with pytest.raises(posts.InvalidPostContentError, match="comes later"):
        posts.update_post_content(post, b"replacement")
