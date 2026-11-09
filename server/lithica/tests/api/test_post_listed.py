"""Listed affects post searches, not access or site-wide bookkeeping."""

from collections.abc import Callable
from typing import Any

import pytest

from lithica import config, db, model, registry
from lithica.func import posts, util
from lithica.tests.api.http import ok, shipped_config

# Fixture adapters return heterogeneous HTTP JSON and fixture factories.
Factory = Callable[..., Any]


@pytest.fixture
def listed_site(
    config_injector: Factory,
    tmp_path: Any,
    post_factory: Factory,
    user_factory: Factory,
    pool_factory: Factory,
    tag_factory: Factory,
) -> dict[str, Any]:
    config_injector(shipped_config(str(tmp_path), modules=["cards"]))
    registry.load_configured()
    user = user_factory(name="owner", rank=model.User.RANK_ADMINISTRATOR)
    visible, unlisted, last = [post_factory(id=i) for i in (1, 2, 3)]
    unlisted.listed = False
    unlisted.user = user
    tag = tag_factory(names=["test"])
    unlisted.tags = [tag]
    unlisted.favorited_by = [model.PostFavorite(user=user, time=util.utcnow())]
    pool = pool_factory(names=["test"])
    pool.posts = [unlisted]
    db.session.add_all([user, visible, unlisted, last, pool])
    db.session.flush()
    return dict(user=user, unlisted=unlisted, pool=pool, tag=tag)


@pytest.mark.parametrize(
    "query,ids",
    [
        ("", [1, 3]),
        ("listed:yes", [1, 3]),
        ("listed:no", [2]),
        ("listed:any", [1, 2, 3]),
        ("-listed:yes", [2]),
        ("-listed:no", [1, 3]),
        ("uploader:owner", []),
        ("uploader:owner listed:any", [2]),
        ("fav:owner", []),
        ("fav:owner listed:any", [2]),
    ],
)
def test_search(
    client: Any, listed_site: dict[str, Any], query: str, ids: list[int]
) -> None:
    result = ok(
        client.get(
            "/posts", user=listed_site["user"], query={"query": query, "fields": "id"}
        )
    )
    assert sorted(p["id"] for p in result["results"]) == ids
    assert result["total"] == len(ids)
    assert result["query"] == query


@pytest.mark.parametrize(
    "query",
    [
        "listed:yes listed:no",
        "listed:any listed:any",
        "-listed:any",
        "listed:bad",
        "listed:yes,no",
        "listed:yes..no",
    ],
)
def test_invalid(client: Any, listed_site: dict[str, Any], query: str) -> None:
    for path in ("/posts", "/post/2/around"):
        response = client.get(path, user=listed_site["user"], query={"query": query})
        assert response.status_code == 400
        assert response.json()["name"] == "SearchError"


def test_around(client: Any, listed_site: dict[str, Any]) -> None:
    user = listed_site["user"]
    assert ok(client.get("/post/1/around", user=user, query={"fields": "id"})) == {
        "prev": {"id": 3},
        "next": None,
    }
    assert ok(client.get("/post/2/around", user=user, query={"fields": "id"})) == {
        "prev": {"id": 3},
        "next": {"id": 1},
    }
    assert ok(
        client.get(
            "/post/1/around", user=user, query={"fields": "id", "query": "listed:any"}
        )
    )["prev"] == {"id": 2}


def test_access_and_counts(client: Any, listed_site: dict[str, Any]) -> None:
    user = listed_site["user"]
    assert ok(client.get("/post/2", user=user))["listed"] is False
    pool = ok(client.get(f"/pool/{listed_site['pool'].pool_id}", user=user))
    assert [p["id"] for p in pool["posts"]] == [2]
    info = ok(client.get("/info", user=user))
    assert info["postCount"] == 3
    owner = ok(client.get("/user/owner", user=user))
    assert owner["uploadedPostCount"] == 1
    assert owner["favoritePostCount"] == 1
    tag = ok(client.get("/tag/test", user=user))
    assert tag["usages"] == 1
    db.session.add(
        model.PostFeature(post=listed_site["unlisted"], user=user, time=util.utcnow())
    )
    db.session.flush()
    assert ok(client.get("/featured-post", user=user))["id"] == 2
    assert ok(client.get("/info", user=user))["featuredPost"]["id"] == 2
    relation = model.PostTypedRelation(
        from_post_id=2, to_post_id=1, type="gallery-of", creation_time=util.utcnow()
    )
    db.session.add(relation)
    db.session.flush()
    related = ok(client.get("/post/1/typed-relations", user=user))
    assert related["results"][0]["post"]["id"] == 2
    for suffix, expected in [("", []), (" listed:any", [2])]:
        found = ok(
            client.get(
                "/posts",
                user=user,
                query={
                    "query": f"pool:{listed_site['pool'].pool_id}{suffix}",
                    "fields": "id",
                },
            )
        )
        assert [p["id"] for p in found["results"]] == expected


def test_reverse_search(
    client: Any, listed_site: dict[str, Any], read_asset: Factory
) -> None:
    post = listed_site["unlisted"]
    content = read_asset("jpeg.jpg")
    post.checksum = util.get_sha1(content)
    posts.generate_post_signature(post, content)
    db.session.flush()
    result = ok(
        client.post(
            "/posts/reverse-search",
            user=listed_site["user"],
            files={"content": content},
            query={"fields": "id"},
        )
    )
    assert result["exactPost"]["id"] == 2
    assert result["similarPosts"][0]["post"]["id"] == 2


def test_visibility(
    client: Any, listed_site: dict[str, Any], tag_factory: Factory
) -> None:
    config.config["visibility"] = "nsfw-login"
    listed_site["unlisted"].tags = [tag_factory(names=["nsfw"])]
    db.session.flush()
    result = ok(client.get("/posts", query={"query": "listed:any", "fields": "id"}))
    assert sorted(p["id"] for p in result["results"]) == [1, 3]
    assert result["total"] == 2


@pytest.mark.parametrize("target_listed", [True, False])
def test_merge(
    listed_site: dict[str, Any], target_listed: bool, post_factory: Factory
) -> None:
    target = db.session.get(model.Post, 1)
    target.listed = target_listed
    source = post_factory(id=4)
    db.session.add(source)
    source.listed = not target_listed
    db.session.commit()
    posts.merge_posts(source, target, False)
    db.session.flush()
    assert target.listed is target_listed


def test_creation_stays_listed(
    client: Any,
    config_injector: Factory,
    tmp_path: Any,
    user_factory: Factory,
    read_asset: Factory,
    tag_category_factory: Factory,
) -> None:
    config_injector(shipped_config(str(tmp_path)))
    db.session.add(tag_category_factory(name="default", default=True))
    db.session.flush()
    user = user_factory(rank=model.User.RANK_ADMINISTRATOR)
    result = ok(
        client.post(
            "/posts",
            user=user,
            body={"safety": "safe", "listed": False},
            files={"content": read_asset("png.png")},
        )
    )
    assert result["listed"] is True
