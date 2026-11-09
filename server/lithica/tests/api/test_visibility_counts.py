"""
What the numbers say to an anonymous user in `nsfw-login` (doc/API.md,
"Visibility"): which counts leave the hidden posts out, and which still
count them. Each count is pinned here as it is: one that changes, changes
its documentation with it.

The site is lithica.tests.api.rich_posts, committed, with a session per
request as the server runs them. Anonymous users are given the privileges
to see users, and to list tags and pools, so that every count can be read.
"""

from typing import Any

import pytest

from lithica import db, model, registry
from lithica.tests.api import rich_posts
from lithica.tests.api.http import shipped_config

ANONYMOUS_MAY = ("users:view", "users:list", "tags:list", "pools:list")
TAG = "smile"


@pytest.fixture
def site(config_injector, tmpdir, committing_session) -> dict[str, Any]:
    config = shipped_config(str(tmpdir.mkdir("data")), **rich_posts.config_overrides())
    config["privileges"] = config["privileges"] | dict.fromkeys(
        ANONYMOUS_MAY, model.User.RANK_ANONYMOUS
    )
    config_injector(config)
    registry.load_configured()
    client, ids = rich_posts.committed_site(20, 3)

    def get(path: str, who: str | None = None, **query: str) -> Any:
        headers = rich_posts.header(who) if who else None
        response = client.get(path, query=query or None, headers=headers)
        assert response.status_code == 200, response.text
        return response.json()

    listed = get("/posts", limit="100", fields="id")["results"]
    hidden = set(ids) - {post["id"] for post in listed}
    assert hidden, "the site hides some posts"
    return {"get": get, "hidden": hidden}


def _all_and_visible(post_ids: list[int], hidden: set[int]) -> tuple[int, int]:
    """How many: in all, and leaving out the hidden posts."""
    visible = [post_id for post_id in post_ids if post_id not in hidden]
    assert len(visible) < len(post_ids), "the count has hidden posts to leave out"
    return len(post_ids), len(visible)


def _tag_post_ids(name: str) -> list[int]:
    tag_id = db.session.query(model.TagName.tag_id).filter_by(name=name).scalar()
    return [
        post_id
        for (post_id,) in db.session.query(model.PostTag.post_id).filter_by(
            tag_id=tag_id
        )
    ]


def test_tag_usages_count_hidden_posts(site):
    get = site["get"]
    with db.session_scope():
        every, _ = _all_and_visible(_tag_post_ids(TAG), site["hidden"])
    assert get("/tag/%s" % TAG)["usages"] == every
    assert [tag["usages"] for tag in get("/tags", query=TAG)["results"]] == [every]
    in_posts = {
        tag["usages"]
        for post in get("/posts", limit="100", fields="tags")["results"]
        for tag in post["tags"]
        if TAG in tag["names"]
    }
    assert in_posts == {every}


def test_tag_siblings_count_hidden_posts(site):
    get, hidden = site["get"], site["hidden"]
    with db.session_scope():
        with_tag = set(_tag_post_ids(TAG))
        every: dict[str, int] = {}
        for name in ("commission", rich_posts.NSFW):
            together = sorted(with_tag & set(_tag_post_ids(name)))
            every[name], _ = _all_and_visible(together, hidden)
    siblings = {
        sibling["tag"]["names"][0]: sibling["occurrences"]
        for sibling in get("/tag-siblings/%s" % TAG)["results"]
    }
    for name, count in every.items():
        assert siblings[name] == count, name
    # the NSFW tag itself is a sibling: it is on hidden posts only
    assert siblings[rich_posts.NSFW] > 0


def test_a_pool_s_post_count_leaves_hidden_posts_out(site):
    get, hidden = site["get"], site["hidden"]
    with db.session_scope():
        pool = next(
            pool
            for pool in db.session.query(model.Pool).order_by(model.Pool.pool_id)
            if any(row.post_id in hidden for row in pool._posts)
        )
        every, visible = _all_and_visible([row.post_id for row in pool._posts], hidden)
        pool_id = pool.pool_id
    assert get("/pool/%d" % pool_id)["postCount"] == visible
    assert len(get("/pool/%d" % pool_id)["posts"]) == visible
    listed = get("/pools")["results"]
    assert [one["postCount"] for one in listed if one["id"] == pool_id] == [visible]
    in_posts = {
        one["postCount"]
        for post in get("/posts", limit="100", fields="pools")["results"]
        for one in post["pools"]
        if one["id"] == pool_id
    }
    assert in_posts == {visible}
    # a logged-in user is given them all
    assert get("/pool/%d" % pool_id, "bob")["postCount"] == every


def test_a_user_s_upload_and_favourite_counts_count_hidden_posts(site):
    get, hidden = site["get"], site["hidden"]
    with db.session_scope():
        ada = db.session.query(model.User).filter_by(name="ada").one()
        uploads, _ = _all_and_visible(
            [
                post_id
                for (post_id,) in db.session.query(model.Post.post_id).filter_by(
                    user_id=ada.user_id
                )
            ],
            hidden,
        )
        favourites, _ = _all_and_visible(
            [
                post_id
                for (post_id,) in db.session.query(
                    model.PostFavorite.post_id
                ).filter_by(user_id=ada.user_id)
            ],
            hidden,
        )
    user = get("/user/ada")
    assert user["uploadedPostCount"] == uploads
    assert user["favoritePostCount"] == favourites
    listed = get("/users", query="ada")["results"]
    assert [(one["uploadedPostCount"], one["favoritePostCount"]) for one in listed] == [
        (uploads, favourites)
    ]
