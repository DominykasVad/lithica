"""
What the numbers say to an anonymous user in `nsfw-login` (doc/API.md,
"Visibility"): which counts leave the hidden posts out (tag siblings, a
post's relationCount, a pool's postCount), and which still count them (tag
usages, a user's upload, favourite and comment counts). Each count is
pinned here as it is: one that changes, changes its documentation with it.

The site is lithica.tests.api.rich_posts, committed, with a session per
request as the server runs them. Anonymous users are given the privileges
to see users, and to list tags and pools, so that every count can be read.
"""

from typing import Any

import pytest
import sqlalchemy.event as sa_event

from lithica import db, model, registry
from lithica.func import posts
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


def _expected_siblings(hidden: set[int], leave_out_hidden: bool) -> dict[str, int]:
    """The siblings of TAG by name, counted over all posts or the visible ones."""
    with db.session_scope():
        with_tag = {
            post_id
            for post_id in _tag_post_ids(TAG)
            if not leave_out_hidden or post_id not in hidden
        }
        rows = (
            db.session.query(model.PostTag.post_id, model.TagName.name)
            .join(model.TagName, model.TagName.tag_id == model.PostTag.tag_id)
            .filter(model.TagName.order == 0)
            .filter(model.PostTag.post_id.in_(sorted(with_tag)))
        )
        found: dict[str, int] = {}
        for _, name in rows:
            if name != TAG:
                found[name] = found.get(name, 0) + 1
    return found


def _siblings(get: Any, who: str | None) -> dict[str, int]:
    return {
        sibling["tag"]["names"][0]: sibling["occurrences"]
        for sibling in get("/tag-siblings/%s" % TAG, who)["results"]
    }


def test_tag_siblings_come_from_visible_posts_only(site):
    get, hidden = site["get"], site["hidden"]
    expected = _expected_siblings(hidden, leave_out_hidden=True)
    every = _expected_siblings(hidden, leave_out_hidden=False)
    # the site has tags that only hidden posts carry, and counts they change
    only_on_hidden = set(every) - set(expected)
    assert {rich_posts.NSFW, rich_posts.IMPLIES_NSFW} <= only_on_hidden
    assert any(every[name] > count for name, count in expected.items())

    siblings = _siblings(get, None)
    assert siblings == expected
    assert not set(siblings) & only_on_hidden
    # a logged-in user is given them all, as before
    assert _siblings(get, "bob") == every


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


def test_a_user_s_comment_count_counts_comments_on_hidden_posts(site):
    get, hidden = site["get"], site["hidden"]
    with db.session_scope():
        bob = db.session.query(model.User).filter_by(name="bob").one()
        every, _ = _all_and_visible(
            [
                post_id
                for (post_id,) in db.session.query(model.Comment.post_id).filter_by(
                    user_id=bob.user_id
                )
            ],
            hidden,
        )
    assert get("/user/bob")["commentCount"] == every
    assert get("/user/bob", "bob")["commentCount"] == every


def test_relation_count_is_the_relations_the_viewer_sees(site, _pg_engine):
    get, hidden = site["get"], site["hidden"]
    fields = "id,relations,relationCount"
    by_bob = get("/posts", "bob", limit="100", fields=fields)["results"]
    post_id = next(
        post["id"]
        for post in by_bob
        if post["id"] not in hidden
        and {relation["id"] in hidden for relation in post["relations"]}
        == {True, False}
    )
    lengths = {}
    for who in (None, "bob"):
        listed = get("/posts", who, limit="100", fields=fields)["results"]
        one = get("/post/%d" % post_id, who, fields=fields)
        for post in [*listed, one]:
            assert post["relationCount"] == len(post["relations"]), (who, post)
        lengths[who] = one["relationCount"]
    # the hidden relations are left out of the count, for anonymous users only
    assert 0 < lengths[None] < lengths["bob"]

    # loaded for the page at once: as many queries for 2 posts as for 20
    counted: list[int] = []

    def count(*_args: Any) -> None:
        counted.append(1)

    queries = {}
    sa_event.listen(_pg_engine, "after_cursor_execute", count)
    try:
        for limit in ("2", "20"):
            counted.clear()
            get("/posts", None, limit=limit, fields="id,relationCount")
            queries[limit] = len(counted)
    finally:
        sa_event.remove(_pg_engine, "after_cursor_execute", count)
    assert queries["20"] == queries["2"], queries


def _make_related(who_relates: dict[int, list[int]]) -> dict[int, int]:
    """
    New posts of ada's, related as asked (by index, through
    update_post_relations, both ways): index -> post id.
    """
    with db.session_scope():
        ada = db.session.query(model.User).filter_by(name="ada").one()
        made = {}
        for index in sorted({*who_relates, *sum(who_relates.values(), [])}):
            post = model.Post()
            post.user = ada
            post.safety = model.Post.SAFETY_SAFE
            post.type = model.Post.TYPE_IMAGE
            post.mime_type = "image/png"
            post.checksum = "related-%d" % index
            post.flags = []
            post.creation_time = rich_posts.START
            db.session.add(post)
            db.session.flush()
            made[index] = post
        for index, others in who_relates.items():
            posts.update_post_relations(
                made[index], [made[other].post_id for other in others]
            )
        db.session.commit()
        return {index: post.post_id for index, post in made.items()}


def test_relation_count_search_token_counts_related_posts_once(site):
    get = site["get"]
    # 0 is related to 1; 2 to 3 and 4
    made = _make_related({0: [1], 2: [3, 4]})
    for who in (None, "bob"):
        one = {
            post["id"]
            for post in get(
                "/posts", who, query="relation-count:1", limit="100", fields="id"
            )["results"]
        }
        two = {
            post["id"]
            for post in get(
                "/posts", who, query="relation-count:2", limit="100", fields="id"
            )["results"]
        }
        assert {made[0], made[1], made[3], made[4]} <= one, who
        assert made[2] not in one, who
        assert made[2] in two and made[0] not in two, who


def test_sorting_by_relation_count_follows_the_field(site):
    get, hidden = site["get"], site["hidden"]
    counts = {}
    for who in (None, "bob"):
        listed = get(
            "/posts",
            who,
            query="sort:relation-count",
            limit="100",
            fields="id,relationCount,relations",
        )["results"]
        numbers = [post["relationCount"] for post in listed]
        assert numbers == sorted(numbers, reverse=True), who
        assert all(
            post["relationCount"] == len(post["relations"]) for post in listed
        ), who
        counts[who] = {post["id"]: post["relationCount"] for post in listed}
    # anonymous users: the token and the sort count the visible relations
    # only, as the field does
    differs = [
        post_id
        for post_id, number in counts[None].items()
        if number != counts["bob"][post_id]
    ]
    assert differs, "some posts are related to hidden ones"
    post_id = differs[0]
    anonymous_count, bob_count = counts[None][post_id], counts["bob"][post_id]
    for who, number, found in (
        (None, anonymous_count, True),
        (None, bob_count, False),
        ("bob", bob_count, True),
    ):
        listed = get(
            "/posts",
            who,
            query="relation-count:%d" % number,
            limit="100",
            fields="id",
        )["results"]
        assert (post_id in {post["id"] for post in listed}) is found, (who, number)
    assert not hidden & set(counts[None])
