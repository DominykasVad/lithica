"""
The post lists load what their fields need for the whole page at once
(posts.preload_posts, pools.preload_pools), not post by post.

On a site of posts that have everything (lithica.tests.api.rich_posts), in
`nsfw-login`, with requests that each run in a session of their own as the
server runs them:

- the answers are the ones the post-by-post way gives, byte for byte;
- the number of queries does not grow with the number of posts on a page,
  nor with how much one post has (and the same for pools and comments);
- a post this request may not see does not come back through a batch load:
  not as a relation, not as a pool's post.
"""

from collections.abc import Iterator
from typing import Any
from unittest.mock import patch

import pytest
import sqlalchemy.event as sa_event

from lithica import db, model, registry
from lithica.func import comments, pools, posts
from lithica.tests.api import rich_posts
from lithica.tests.api.http import shipped_config

COUNT = 100
# uploaded through the API; the others are made directly (faster)
UPLOADS = 5


class Queries:
    """Counts the statements sent to the database."""

    def __init__(self) -> None:
        self.count = 0

    def __call__(self, *_args: Any) -> None:
        self.count += 1


@pytest.fixture
def queries(_pg_engine: Any) -> Iterator[Queries]:
    counter = Queries()
    sa_event.listen(_pg_engine, "after_cursor_execute", counter)
    try:
        yield counter
    finally:
        sa_event.remove(_pg_engine, "after_cursor_execute", counter)


@pytest.fixture
def site(config_injector, tmpdir, committing_session) -> dict[str, Any]:
    config_injector(
        shipped_config(str(tmpdir.mkdir("data")), **rich_posts.config_overrides())
    )
    registry.load_configured()
    client, ids = rich_posts.committed_site(COUNT, UPLOADS)
    every = ",".join(rich_posts.every_field())

    def get(path: str, who: str | None, **query: str) -> Any:
        headers = rich_posts.header(who) if who else None
        response = client.get(path, query=query or None, headers=headers)
        assert response.status_code == 200, response.text
        return response

    shown = {
        post["id"]
        for post in get("/posts", None, limit=str(COUNT), fields="id").json()["results"]
    }
    hidden = set(ids) - shown
    # a post anonymous users see that is related to one they do not, and
    # to one they do
    seen_by_bob = get("/posts", "bob", limit=str(COUNT), fields="id,relations")
    related_to_hidden = next(
        post["id"]
        for post in seen_by_bob.json()["results"]
        if post["id"] in shown
        and {relation["id"] in hidden for relation in post["relations"]}
        == {True, False}
    )
    with db.session_scope():
        pool_ids = [pool.pool_id for pool in db.session.query(model.Pool).all()]
    assert hidden and shown and pool_ids
    return {
        "get": get,
        "ids": ids,
        "every": every,
        "hidden": hidden,
        "related_to_hidden": related_to_hidden,
        "pool_ids": sorted(pool_ids),
    }


def _requests(site: dict[str, Any]) -> list[tuple[str, str | None, dict[str, str]]]:
    every, post = site["every"], site["related_to_hidden"]
    found: list[tuple[str, str | None, dict[str, str]]] = []
    for who in (None, "bob"):
        found += [
            ("/posts", who, {"limit": str(COUNT)}),
            ("/posts", who, {"limit": str(COUNT), "fields": every}),
            ("/posts", who, {"limit": "10", "offset": "30", "fields": every}),
            ("/post/%d" % post, who, {"fields": every}),
            ("/post/%d" % post, who, {}),
            ("/post/%d/around" % post, who, {"fields": every}),
            ("/featured-post", who, {}),
        ]
        found += [("/pool/%d" % pool_id, who, {}) for pool_id in site["pool_ids"]]
    found.append(("/pools", "bob", {}))
    found.append(("/comments", "bob", {"limit": str(COUNT)}))
    return found


def _one_by_one_comments(found: Any, auth_user: Any, options: Any = None) -> Any:
    return [comments.serialize_comment(one, auth_user, options) for one in found]


def test_the_answers_are_those_of_post_by_post(site, queries):
    """
    Each request, as it is answered, and as it is answered with nothing
    loaded beforehand (each post asks for what it needs as it is
    serialized, as before the batch loads): the same bytes. The order of
    `favoritedBy` is the serializer's own, the same both ways (by the time
    of favouriting, then by user: decided with the batch loads, as the
    database gave no order to keep).
    """
    get = site["get"]
    for path, who, query in _requests(site):
        queries.count = 0
        batched = get(path, who, **query)
        batched_queries = queries.count
        with (
            patch.object(posts, "preload_posts", lambda *_: posts.Preloaded()),
            patch.object(pools, "preload_pools", lambda *_: None),
            patch.object(comments, "serialize_comments", _one_by_one_comments),
        ):
            queries.count = 0
            one_by_one = get(path, who, **query)
            one_by_one_queries = queries.count
        label = "%s %s as %s" % (path, query, who)
        assert batched.content == one_by_one.content, label
        if path in ("/posts", "/comments") and query.get("limit") == str(COUNT):
            # the comparison is with the slow way, not with itself
            assert one_by_one_queries > 5 * batched_queries, label


def test_a_page_of_posts_runs_the_same_queries_for_10_posts_as_for_100(site, queries):
    get, every = site["get"], site["every"]
    for who in (None, "bob"):
        counts = {}
        for limit in ("10", str(COUNT)):
            for fields in (every, None):
                queries.count = 0
                if fields:
                    get("/posts", who, limit=limit, fields=fields)
                else:
                    get("/posts", who, limit=limit)
                counts[limit, bool(fields)] = queries.count
        for fields in (True, False):
            # a constant: which kinds of row a page happens to have
            assert counts[str(COUNT), fields] <= counts["10", fields] + 2, counts


def test_a_page_of_comments_runs_the_same_queries_for_10_as_for_100(site, queries):
    get = site["get"]
    counts = {}
    for limit in ("10", str(COUNT)):
        queries.count = 0
        answer = get("/comments", "bob", limit=limit).json()
        assert len(answer["results"]) == int(limit)
        counts[limit] = queries.count
    assert counts[str(COUNT)] <= counts["10"] + 1, counts


def test_a_page_of_pools_runs_the_same_queries_for_1_pool_as_for_all(site, queries):
    get = site["get"]
    counts = {}
    for limit in ("1", "100"):
        queries.count = 0
        get("/pools", "bob", limit=limit)
        counts[limit] = queries.count
    assert counts["100"] <= counts["1"] + 1, counts
    # one pool: the same however many posts it has
    sizes = {}
    for pool_id in site["pool_ids"]:
        queries.count = 0
        answer = get("/pool/%d" % pool_id, "bob").json()
        sizes[len(answer["posts"])] = queries.count
    assert len(sizes) > 1, sizes
    assert max(sizes.values()) <= min(sizes.values()) + 1, sizes


def test_one_post_runs_the_same_queries_however_much_it_has(site, queries):
    get, every = site["get"], site["every"]
    post_id = site["related_to_hidden"]

    def count() -> dict[str, int]:
        found = {}
        for path in ("/post/%d" % post_id, "/post/%d/around" % post_id):
            for who in (None, "bob"):
                queries.count = 0
                get(path, who, fields=every)
                found["%s as %s" % (path, who)] = queries.count
        return found

    before = count()
    with db.session_scope():
        post = db.session.get(model.Post, post_id)
        people = {user.name: user for user in db.session.query(model.User).all()}
        others = [
            one for one in db.session.query(model.Post).all() if one.post_id != post_id
        ]
        for number in range(20):
            comment = model.Comment()
            comment.post = post
            comment.user = people["bob" if number % 2 else "cy"]
            comment.text = "one more %d" % number
            comment.creation_time = rich_posts.START
            db.session.add(comment)
        for other in others[:15]:
            if other not in post.relations:
                post.relations.append(other)
        for other in others[:12]:
            note = model.PostNote()
            note.post = post
            note.polygon = [[0.2, 0.2], [0.3, 0.2], [0.3, 0.3]]
            note.text = "note on %d" % other.post_id
            db.session.add(note)
        db.session.commit()
    after = count()
    for label, queries_before in before.items():
        assert after[label] <= queries_before + 2, (label, before, after)


def test_relations_and_pools_leave_out_what_anonymous_users_may_not_see(site):
    get, hidden = site["get"], site["hidden"]
    post_id = site["related_to_hidden"]
    # the hidden posts' thumbnails, as a logged-in user is given them
    hidden_thumbnails = [
        get("/post/%d" % hidden_id, "bob", fields="thumbnailUrl").json()["thumbnailUrl"]
        for hidden_id in sorted(hidden)
    ]

    listed = get("/posts", None, limit=str(COUNT), fields="id,relations")
    in_list = next(post for post in listed.json()["results"] if post["id"] == post_id)
    one = get("/post/%d" % post_id, None, fields="id,relations")
    assert in_list["relations"] == one.json()["relations"]
    assert in_list["relations"], "the post has relations anonymous users see"
    around = get("/post/%d/around" % post_id, None, fields="id,relations")
    pools_seen = [get("/pool/%d" % pool_id, None) for pool_id in site["pool_ids"]]
    answers = [(listed, False), (one, True), (around, False)]
    answers += [(pool, False) for pool in pools_seen]
    for response, is_post in answers:
        ids_in = set(_post_ids(response.json(), is_post))
        assert not ids_in & hidden, (response.url, sorted(ids_in & hidden))
        for thumbnail in hidden_thumbnails:
            assert thumbnail not in response.text, response.url


def _post_ids(value: Any, is_post: bool) -> Iterator[int]:
    """Every post id in an answer: of posts, relations, a pool's posts."""
    if isinstance(value, dict):
        if is_post and isinstance(value.get("id"), int):
            yield value["id"]
        for key, inner in value.items():
            if key in ("results", "relations", "posts", "prev", "next"):
                yield from _post_ids(inner, True)
    elif isinstance(value, list):
        for inner in value:
            yield from _post_ids(inner, is_post)
