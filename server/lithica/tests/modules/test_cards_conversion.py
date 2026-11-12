"""Conversion batches isolate failures and the CLI uses the durable queue."""

import argparse
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from lithica import db, model, registry
from lithica.func import jobs as engine_jobs
from lithica.func import posts, util
from lithica.modules.cards import jobs
from lithica.modules.cards.model import Card, CardLorebook, Lorebook
from lithica.tests.api.http import shipped_config
from lithica.tests.conftest import ApiClient
from lithica.tests.modules import cards
from lithica.tests.modules.test_card_upload_documents import upload
from lithica.tests.test_admin import admin  # noqa: F401

Site = Callable[[list[str]], ApiClient]
# Any: the CLI script is loaded dynamically by its SourceFileLoader fixture.


def test_conversion(site: Site, user: model.User) -> None:
    client = site(["cards"])
    registry.use(
        [replace(module, after_file_or_kind=None) for module in registry.modules()]
    )
    ids = [upload(client, user, cards.v2_card(name=str(i)), shade=i) for i in range(3)]
    db.session.commit()
    jobs.command(argparse.Namespace(count=False))
    assert jobs.command(argparse.Namespace(count=False)) == 1
    from lithica.modules.cards.uploads import convert

    posts.get_post_by_id(ids[1]).safety = "unsafe"
    db.session.commit()

    def sometimes(post: model.Post, user: model.User | None) -> None:
        convert(post, user)
        if post.post_id == ids[1]:
            raise ValueError("private card")

    with (
        patch.object(jobs, "convert", sometimes),
        patch.object(jobs.logger, "warning") as logged,
    ):
        jobs.run({"after": 0})
    logged.assert_called_once_with(
        "Card %d conversion failed: %s", ids[1], "ValueError"
    )
    assert db.session.get(Card, ids[1]) is None
    assert db.session.query(CardLorebook).count() == 2
    book_id = db.session.query(Lorebook.post_id).scalar()
    assert posts.get_post_by_id(book_id).safety == "safe"
    assert jobs.pending().count() == 1
    jobs.run({"after": 0})
    assert jobs.pending().count() == 0
    jobs.run({"after": 0})
    assert db.session.query(Lorebook).count() == 1


def test_conversion_batches(site: Site, user: model.User) -> None:
    site(["cards"])
    for i in range(101):
        post = posts.create_fileless_post("card", user)
        post.contents = [
            model.PostContent(
                kind="card_v1",
                schema_version=3,
                extracted_at=util.utcnow(),
                payload={"card": {**cards.V1_CARD, "name": str(i)}, "format": "png"},
            )
        ]
    db.session.flush()
    ids = [post.post_id for post in jobs.pending().order_by(model.Post.post_id)]
    jobs.run({"after": 0})
    assert jobs.pending().count() == 1
    successor = db.session.query(model.Job).filter_by(type="cards-convert").one()
    assert successor.payload == {"after": ids[99]}
    jobs.run(successor.payload)
    assert jobs.pending().count() == 0
    assert db.session.query(Card).count() == 101
    assert db.session.query(model.Job).count() == 1


@pytest.fixture
def legacy_committed_card(
    config_injector: Callable[..., None],
    tmp_path: Path,
    committing_session: None,
    user_factory: Callable[..., model.User],
    tag_category_factory: Callable[..., model.TagCategory],
) -> int:
    config_injector(shipped_config(str(tmp_path), modules=["cards"]))
    registry.load_configured()
    with db.session_scope():
        user = user_factory()
        db.session.add_all([user, tag_category_factory(name="default", default=True)])
        db.session.flush()
        post = posts.create_fileless_post("card", user)
        post.contents = [
            model.PostContent(
                kind="card_v1",
                schema_version=3,
                extracted_at=util.utcnow(),
                payload={"card": cards.V1_CARD, "format": "png"},
            )
        ]
        db.session.flush()
        post_id = post.post_id
        db.session.commit()
    return post_id


def test_cli_count_refusal_and_worker(
    admin: Any,  # noqa: F811
    legacy_committed_card: int,
    capsys: pytest.CaptureFixture[str],
) -> None:
    post_id = legacy_committed_card
    assert admin.main(["cards", "convert", "--count"]) == 0
    assert "1 cards without a document" in capsys.readouterr().out
    with db.session_scope():
        assert db.session.query(model.Job).count() == 0
    assert admin.main(["cards", "convert"]) == 0
    with db.session_scope():
        job = db.session.query(model.Job).one()
        assert job.payload == {"after": 0} and job.status == "queued"
    assert admin.main(["cards", "convert"]) == 1
    assert "queued or running" in capsys.readouterr().err
    with db.session_scope():
        job = db.session.query(model.Job).one()
        job.status = "running"
        db.session.commit()
    assert admin.main(["cards", "convert"]) == 1
    assert admin.main(["cards", "convert", "--count"]) == 0
    with db.session_scope():
        job = db.session.query(model.Job).one()
        job.status = "queued"
        db.session.commit()
    assert engine_jobs.work_once()
    with db.session_scope():
        assert db.session.query(model.Job).one().status == "done"
        assert db.session.get(model.PostDocument, post_id).version == 0
    assert admin.main(["cards", "convert"]) == 0
    with db.session_scope():
        assert db.session.query(model.Job).count() == 1


def test_concurrent_starts(legacy_committed_card: int) -> None:
    def start() -> int:
        with db.session_scope():
            return jobs.command(argparse.Namespace(count=False))

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [
            future.result() for future in [pool.submit(start), pool.submit(start)]
        ]
    assert sorted(results) == [0, 1]
    with db.session_scope():
        assert db.session.query(model.Job).count() == 1
