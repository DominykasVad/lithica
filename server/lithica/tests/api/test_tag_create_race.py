"""Two requests that create the same new tag at the same time."""

import asyncio
import json
import threading
from unittest.mock import patch

import httpx2
import pytest
import sqlalchemy.exc as sa_exc
import sqlalchemy.orm as sa_orm

from lithica import db, model
from lithica.app import app as lithica_app
from lithica.func import tags


@pytest.fixture
def site(config_injector, tmpdir):
    config_injector(
        {
            "data_dir": str(tmpdir.mkdir("data")),
            "data_url": "http://example.com/data/",
            "secret": "test",
            "allow_broken_uploads": False,
            "delete_source_files": True,
            "thumbnails": {
                "post_width": 300,
                "post_height": 300,
                "avatar_width": 30,
                "avatar_height": 30,
            },
            "convert": {"gif": {"to_mp4": False, "to_webm": False}},
            "tag_name_regex": r"^\S+$",
            "webhooks": [],
            "privileges": {
                "posts:create:anonymous": model.User.RANK_ANONYMOUS,
                "tags:create": model.User.RANK_ANONYMOUS,
                "uploads:use_downloader": model.User.RANK_ADMINISTRATOR,
            },
        }
    )


@pytest.fixture
def committing_db(transacted_postgresql_db, postgresql_db, _pg_engine):
    """
    Each request with a session of its own, as the server runs, on tables
    whose rows are committed: what one request commits the other sees. The
    test's own transaction is given up first; its uncommitted tables would
    hold up the ones made here.
    """
    transacted_postgresql_db.reset_db()
    postgresql_db.create_table(*model.Base.metadata.sorted_tables)
    test_session = db.session
    # the server's scoped session, on the test database
    db.session = sa_orm.scoped_session(
        sa_orm.sessionmaker(_pg_engine, autoflush=False),
        scopefunc=db._current_scope,
    )
    try:
        with db.session_scope():
            category = model.TagCategory("default")
            category.color = "dummy"
            category.order = 1
            category.default = True
            db.session.add(category)
            db.session.commit()
        yield
    finally:
        db.session = test_session


def _post_concurrently(contents: list[bytes], tag_names: list[str]) -> list:
    async def run() -> list:
        transport = httpx2.ASGITransport(app=lithica_app, raise_app_exceptions=False)
        async with httpx2.AsyncClient(
            transport=transport,
            base_url="http://test",
            headers={"Accept": "application/json"},
        ) as client:
            return await asyncio.gather(
                *[
                    client.post(
                        "/posts",
                        data={
                            "metadata": json.dumps(
                                {
                                    "safety": "safe",
                                    "tags": tag_names,
                                    "anonymous": True,
                                }
                            )
                        },
                        files={"content": ("content", content)},
                    )
                    for content in contents
                ]
            )

    return asyncio.run(run())


def test_two_posts_with_the_same_new_tag_both_succeed(site, committing_db, read_asset):
    real = tags.get_tags_by_names
    # both requests look for the tag before either creates it
    together = threading.Barrier(2)

    def look_together(names):
        found = real(names)
        if names == ["race"]:
            together.wait(timeout=10)
        return found

    with patch.object(tags, "get_tags_by_names", look_together):
        responses = _post_concurrently(
            [read_asset("png.png"), read_asset("jpeg.jpg")], ["race"]
        )

    assert [response.status_code for response in responses] == [200, 200]
    with db.session_scope():
        names = db.session.query(model.TagName).filter(model.TagName.name == "race")
        assert names.count() == 1
        tag_id = names.one().tag_id
        posts = db.session.query(model.Post).all()
        assert len(posts) == 2
        assert all([tag.tag_id for tag in post.tags] == [tag_id] for post in posts)


def test_a_tag_created_meanwhile_is_taken_as_it_is(tag_factory):
    tag = tag_factory(names=["taken"])
    db.session.add(tag)
    db.session.flush()

    # the lookup ran before the other request committed the tag
    with patch.object(tags, "get_tags_by_names", return_value=[]):
        existing, created = tags.get_or_create_tags_by_names(["taken", "fresh"])

    assert [found.tag_id for found in existing] == [tag.tag_id]
    assert [new.first_name for new in created] == ["fresh"]
    assert db.session.query(model.TagName).count() == 2


def test_another_conflict_is_not_taken_for_a_tag_created_meanwhile(
    tag_category_factory,
):
    category = tag_category_factory(name="default", default=True)
    db.session.add(category)
    db.session.flush()
    gone = model.TagCategory("gone")
    gone.tag_category_id = category.tag_category_id + 1000

    # a category that is not there: the insert fails on its foreign key
    with (
        patch("lithica.func.tag_categories.get_category_by_name", return_value=gone),
        pytest.raises(sa_exc.IntegrityError),
    ):
        tags.get_or_create_tags_by_names(["orphan"])

    # only the savepoint was rolled back: the request can go on
    assert db.session.query(model.TagName).count() == 0
    assert db.session.query(model.TagCategory).count() == 1
