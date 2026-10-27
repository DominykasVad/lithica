"""A search that depends on who asks (special:fav) answers for that user only."""

import asyncio
import base64
import threading
from unittest.mock import patch

import httpx2
import pytest

from lithica import db, model, search
from lithica.app import app as lithica_app
from lithica.func import auth, util


@pytest.fixture
def site(config_injector, tmpdir):
    config_injector(
        {
            "data_dir": str(tmpdir.mkdir("data")),
            "data_url": "http://example.com/data/",
            "secret": "test",
            "privileges": {
                "posts:list": model.User.RANK_ANONYMOUS,
                "posts:view": model.User.RANK_ANONYMOUS,
            },
        }
    )


def _user(name: str) -> model.User:
    user = model.User()
    user.name = name
    user.rank = model.User.RANK_REGULAR
    user.creation_time = util.utcnow()
    user.avatar_style = model.User.AVATAR_GRAVATAR
    user.password_salt = "salt"
    user.password_hash, user.password_revision = auth.get_password_hash(
        "salt", name + "_password"
    )
    return user


def _post(post_id: int) -> model.Post:
    post = model.Post()
    post.post_id = post_id
    post.safety = model.Post.SAFETY_SAFE
    post.type = model.Post.TYPE_IMAGE
    post.checksum = "checksum-%d" % post_id
    post.mime_type = "image/png"
    post.creation_time = util.utcnow()
    post.flags = []
    return post


@pytest.fixture
def favourites(site, committing_session):
    """ann favours post 1 only, bob post 2 only, committed."""
    with db.session_scope():
        ann, bob = _user("ann"), _user("bob")
        first, second = _post(1), _post(2)
        db.session.add_all([ann, bob, first, second])
        db.session.flush()
        for user, post in ((ann, first), (bob, second)):
            favourite = model.PostFavorite()
            favourite.user = user
            favourite.post = post
            favourite.time = util.utcnow()
            db.session.add(favourite)
        db.session.commit()


def _basic(name: str) -> str:
    return (
        "Basic " + base64.b64encode(("%s:%s_password" % (name, name)).encode()).decode()
    )


def _search_concurrently(names: list[str]) -> list:
    async def run() -> list:
        transport = httpx2.ASGITransport(app=lithica_app, raise_app_exceptions=False)
        async with httpx2.AsyncClient(
            transport=transport,
            base_url="http://test",
            headers={"Accept": "application/json"},
        ) as client:
            return await asyncio.gather(
                *[
                    client.get(
                        "/posts",
                        params={"query": "special:fav", "fields": "id"},
                        headers={"Authorization": _basic(name)},
                    )
                    for name in names
                ]
            )

    return asyncio.run(run())


def test_two_searches_at_once_each_answer_for_their_own_user(favourites):
    real = search.configs.PostSearchConfig.on_search_query_parsed
    # both searches have been asked, by their two users, before either reads
    # its query: where a user kept in a shared object would be overwritten
    together = threading.Barrier(2)

    def held(self, search_query, user):
        together.wait(timeout=10)
        return real(self, search_query, user)

    with patch.object(search.configs.PostSearchConfig, "on_search_query_parsed", held):
        responses = _search_concurrently(["ann", "bob"])

    assert [response.status_code for response in responses] == [200, 200]
    assert [
        [post["id"] for post in response.json()["results"]] for response in responses
    ] == [
        [1],
        [2],
    ]


def test_an_anonymous_user_may_not_search_their_favourites(favourites):
    async def run() -> httpx2.Response:
        transport = httpx2.ASGITransport(app=lithica_app, raise_app_exceptions=False)
        async with httpx2.AsyncClient(
            transport=transport,
            base_url="http://test",
            headers={"Accept": "application/json"},
        ) as client:
            return await client.get("/posts", params={"query": "special:fav"})

    response = asyncio.run(run())
    assert response.status_code == 400
    assert response.json()["name"] == "SearchError"
    assert response.json()["description"] == "Must be logged in to use this feature."
