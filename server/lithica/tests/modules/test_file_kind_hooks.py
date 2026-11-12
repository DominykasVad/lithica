"""Every public file/kind path reaches the engine's module hook."""

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from lithica import config, db, model, registry
from lithica.func import post_import, posts
from lithica.func.content import Content
from lithica.tests.api.http import ok
from lithica.tests.conftest import ApiClient
from lithica.tests.fixtures.modules import dummy
from lithica.tests.fixtures.modules.dummy.model import DummyHook
from lithica.tests.modules import cards


def _forget(post_id: int) -> None:
    row = db.session.get(DummyHook, post_id)
    assert row is not None
    db.session.delete(row)
    db.session.commit()


def test_request_paths(site, user):
    client = site(["cards"])
    config.config["privileges"]["posts:edit:kind"] = model.User.RANK_REGULAR
    registry.use(
        [
            *(
                replace(module, after_file_or_kind=None)
                for module in registry.modules()
            ),
            dummy.module,
        ]
    )
    result = ok(
        client.post(
            "/posts",
            user=user,
            body={"safety": "safe"},
            files={"content": cards.png_card(cards.v2_card())},
        )
    )
    post_id = result["id"]
    assert db.session.get(DummyHook, post_id).kind == "card"
    _forget(post_id)
    result = ok(
        client.put(
            f"/post/{post_id}/kind",
            user=user,
            body={"version": result["version"], "kind": "media"},
        )
    )
    assert db.session.get(DummyHook, post_id).kind == "media"
    _forget(post_id)
    ok(
        client.put(
            f"/post/{post_id}",
            user=user,
            body={"version": result["version"]},
            files={"content": cards.picture(shade=70)},
        )
    )
    assert db.session.get(DummyHook, post_id).kind == "media"


def test_command_paths(site, user, tmp_path: Path):
    site(["cards"])
    registry.use(
        [
            *(
                replace(module, after_file_or_kind=None)
                for module in registry.modules()
            ),
            dummy.module,
        ]
    )
    path = tmp_path / "card.png"
    path.write_bytes(cards.png_card(cards.v2_card()))
    post = post_import._create_post(Content(str(path)), user, "safe", [])
    db.session.commit()
    _forget(post.post_id)
    post.kind = "media"
    db.session.commit()
    assert posts.update_all_post_kinds() == (1, 0)
    assert db.session.get(DummyHook, post.post_id).kind == "card"
    _forget(post.post_id)
    post.contents = []
    post.kind = "media"
    db.session.commit()
    assert posts.reextract_all_post_contents() == (1, 0)
    assert db.session.get(DummyHook, post.post_id).kind == "card"


def test_raising_hook_does_not_fail_upload(site, user):
    client = site(["cards"])

    def fail(post: model.Post, user: model.User | None) -> None:
        dummy.after_file_or_kind(post, user)
        db.session.flush()
        raise RuntimeError("private payload")

    registry.use([*registry.modules(), replace(dummy.module, after_file_or_kind=fail)])
    result = ok(
        client.post(
            "/posts",
            user=user,
            body={"safety": "safe"},
            files={"content": cards.picture()},
        )
    )
    assert db.session.get(DummyHook, result["id"]) is None


def test_generated_alternate_gets_its_hook(
    site: Callable[[list[str]], ApiClient],
    user: model.User,
    post_factory: Callable[..., model.Post],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site(["cards"])
    registry.use([*registry.modules(), dummy.module])
    config.config["convert"]["gif"]["to_mp4"] = True
    parent = post_factory()
    parent.user = user
    db.session.add(parent)
    db.session.flush()
    alternate = post_factory()
    alternate.user = user

    def create(
        _content: object, _tags: list[str], _user: model.User | None
    ) -> tuple[model.Post, list[model.Tag]]:
        db.session.add(alternate)
        return alternate, []

    monkeypatch.setattr(posts, "create_post", create)
    monkeypatch.setattr(posts.mime, "is_animated_gif", lambda _content: True)
    monkeypatch.setattr(
        posts.images, "Image", lambda _content: SimpleNamespace(to_mp4=lambda: b"mp4")
    )
    assert posts.generate_alternate_formats(parent, b"gif") == [(alternate, [])]
    recorded = db.session.get(DummyHook, alternate.post_id)
    assert recorded is not None
    assert recorded.user_id == user.user_id and recorded.kind == alternate.kind
    assert db.session.get(DummyHook, parent.post_id) is None
