"""
The site's `visibility`: what anonymous users see in nsfw-login and in login.

The NSFW posts of nsfw-login do not exist for anonymous users. The tests
walk every route of the engine and of the modules with an anonymous user
who has every privilege, on a site where hidden posts have comments,
snapshots, a card, a pool, a relation, the featured spot and a merge, and
fail if any answer holds a hidden post's id, the names of its files, its
checksum, its card or its comments; a request that names a hidden post
must be refused as for a post that is not there.
"""

import re
from collections.abc import Mapping, Sequence
from typing import Any, cast
from unittest.mock import patch

import pytest
import sqlalchemy as sa
import sqlalchemy.orm as sa_orm
import yaml

from lithica import config, db, model, registry
from lithica.api.post_api import _search_executor
from lithica.app import create_app
from lithica.func import auth, posts, snapshots, util, visibility
from lithica.tests.conftest import ApiClient
from lithica.tests.modules import cards

HIDDEN = [9100001, 9100002, 9100003]
CARD_NAME = "Velvet Hidden Name"
HIDDEN_COMMENT = "hush about the hidden one"


def _all_privileges(rank: str) -> dict[str, str]:
    with open("config.yaml.dist") as handle:
        privileges = yaml.safe_load(handle)["privileges"]
    return {name: rank for name in privileges}


@pytest.fixture(autouse=True)
def no_mail():
    with patch("lithica.func.mailer.send_mail"):
        yield


@pytest.fixture
def start(config_injector, tmpdir, tag_category_factory, read_asset):
    """A site of this visibility: returns the client of its application."""

    def start(visibility: str, privileges: dict[str, str] | None = None) -> ApiClient:
        with open("config.yaml.dist") as handle:
            defaults = yaml.safe_load(handle)
        config_injector(
            defaults
            | {
                "modules": ["cards"],
                "visibility": visibility,
                "nsfw_tag": "nsfw",
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
                "tag_category_name_regex": r"^\S+$",
                "pool_name_regex": r"^\S+$",
                "pool_category_name_regex": r"^\S+$",
                "user_name_regex": r"^\S+$",
                "password_regex": r"^.{5,}$",
                "default_rank": "regular",
                "webhooks": [],
                # a site that sends mail (no_mail catches it): password reset works
                "smtp": defaults["smtp"] | {"host": "mail.example.com"},
                "privileges": privileges or _all_privileges(model.User.RANK_ANONYMOUS),
            }
        )
        db.session.add(tag_category_factory(name="default", default=True))
        db.session.flush()
        registry.load_configured()
        return ApiClient(create_app())

    return start


class Site:
    """What the walk needs to know of the site, and what must not come out."""

    def __init__(self) -> None:
        self.visible = 0
        self.pool = 0
        self.visible_comment = 0
        self.hidden_comment = 0
        self.admin = ""
        self.hidden_content = b""
        self.markers: list[re.Pattern[str]] = []


def _make_hidden_post(
    post_id: int, content: bytes, tags: list[str], user: model.User
) -> model.Post:
    # as posts.create_post makes it, with an id of its own, to be found in
    # any answer, before anything of it is written
    post = model.Post()
    post.post_id = post_id
    post.user = user
    post.safety = model.Post.SAFETY_UNSAFE
    post.creation_time = util.utcnow()
    post.flags = []
    post.type = ""
    post.checksum = ""
    post.mime_type = ""
    posts.update_post_content(post, content)
    new_tags = posts.update_post_tags(post, tags)
    db.session.add(post)
    posts.update_post_auto_tags(post)
    db.session.flush()
    for tag in new_tags:
        snapshots.create(tag, user)
    snapshots.create(post, user)
    db.session.flush()
    return post


@pytest.fixture
def nsfw_site(start, user_factory, read_asset) -> tuple[ApiClient, Site]:
    client = start("nsfw-login")
    admin = user_factory(name="the_admin", rank=model.User.RANK_ADMINISTRATOR)
    db.session.add(admin)
    db.session.flush()
    site = Site()
    site.admin = admin.name

    def as_admin(method: str, path: str, **kwargs: Any) -> Any:
        response = client.request(method, path, user=admin, **kwargs)
        assert response.status_code == 200, response.text
        return response.json()

    card = cards.png_card(
        cards.v2_card(name=CARD_NAME, creator="Hidden Maker", tags=["velvet"]), shade=7
    )
    site.hidden_content = card
    first = _make_hidden_post(HIDDEN[0], card, ["nsfw"], admin)
    # hidden through implications: one, and two steps away
    as_admin(
        "POST",
        "/tags",
        body={"names": ["explicit"], "category": "default", "implications": ["nsfw"]},
    )
    as_admin(
        "POST",
        "/tags",
        body={
            "names": ["very_explicit"],
            "category": "default",
            "implications": ["explicit"],
        },
    )
    _make_hidden_post(HIDDEN[1], read_asset("webp.webp"), ["explicit"], admin)
    _make_hidden_post(HIDDEN[2], read_asset("bmp.bmp"), ["very_explicit"], admin)

    visible = as_admin(
        "POST",
        "/posts",
        body={"safety": "safe", "tags": ["safe_one"], "relations": [HIDDEN[0]]},
        files={"content": read_asset("png.png")},
    )
    site.visible = visible["id"]
    site.visible_comment = as_admin(
        "POST",
        "/comments",
        body={"postId": site.visible, "text": "about the visible one"},
    )["id"]
    site.hidden_comment = as_admin(
        "POST", "/comments", body={"postId": HIDDEN[0], "text": HIDDEN_COMMENT}
    )["id"]
    as_admin("POST", "/pool-categories", body={"name": "default", "color": "red"})
    site.pool = as_admin(
        "POST",
        "/pool",
        body={
            "names": ["the_pool"],
            "category": "default",
            "posts": [site.visible, HIDDEN[0]],
        },
    )["id"]
    as_admin("POST", "/featured-post", body={"id": HIDDEN[0]})
    as_admin("PUT", "/post/%d/score" % HIDDEN[0], body={"score": 1})
    as_admin("POST", "/post/%d/favorite" % HIDDEN[0])
    merged = as_admin(
        "POST",
        "/posts",
        body={"safety": "safe", "tags": []},
        files={"content": read_asset("jpeg.jpg")},
    )
    target = as_admin("GET", "/post/%d" % HIDDEN[0])
    as_admin(
        "POST",
        "/post-merge",
        body={
            "remove": merged["id"],
            "mergeTo": HIDDEN[0],
            "removeVersion": merged["version"],
            "mergeToVersion": target["version"],
            "replaceContent": False,
        },
    )

    for post_id in HIDDEN:
        site.markers.append(re.compile(r"(?<![0-9])%d(?![0-9])" % post_id))
        site.markers.append(
            re.compile(re.escape(posts.get_post_security_hash(post_id)))
        )
    site.markers.append(re.compile(re.escape(first.checksum)))
    site.markers.append(re.compile(re.escape(CARD_NAME)))
    site.markers.append(re.compile(re.escape("Hidden Maker")))
    site.markers.append(re.compile(re.escape(HIDDEN_COMMENT)))
    return client, site


def _fresh() -> None:
    """
    As at the start of a request: the server gives each one a session of
    its own, empty; the tests' requests share the test's session, which
    keeps what the site's setup loaded unless it is emptied.
    """
    db.session.flush()
    db.session.expunge_all()


def _leaks(text: str, site: Site) -> list[str]:
    return [marker.pattern for marker in site.markers if marker.search(text)]


def _routes(client: ApiClient) -> set[str]:
    document = client._app.openapi()
    return {
        "%s %s" % (method.upper(), path)
        for path, operations in document["paths"].items()
        for method in operations
        if method in ("get", "post", "put", "delete")
    }


def _gets(site: Site) -> dict[str, Sequence[tuple[str, Mapping[str, Any], bool | str]]]:
    """Every GET route: its requests, and whether each names a hidden post."""
    hidden_posts = [("/post/%d" % post_id, {}, True) for post_id in HIDDEN]
    queries = [
        "",
        "nsfw",
        "explicit",
        "very_explicit",
        "velvet",
        "fav:the_admin",
        "sort:random",
        "comment-count-min:1",
        "type:card",
    ]
    return {
        "GET /info": [("/info", {}, False)],
        "GET /users": [("/users", {}, False)],
        "GET /user/{user_name}": [("/user/the_admin", {}, False)],
        "GET /user-tokens/{user_name}": [("/user-tokens/the_admin", {}, False)],
        "GET /password-reset/{user_name}": [("/password-reset/the_admin", {}, False)],
        "GET /tag-categories": [("/tag-categories", {}, False)],
        "GET /tag-category/{category_name}": [("/tag-category/default", {}, False)],
        "GET /tags": [("/tags", {}, False)],
        "GET /tag/{tag_name}": [
            ("/tag/%s" % name, {}, False)
            for name in ("nsfw", "explicit", "safe_one", "velvet")
        ],
        "GET /tag-siblings/{tag_name}": [
            ("/tag-siblings/%s" % name, {}, False)
            for name in ("nsfw", "safe_one", "velvet")
        ],
        "GET /pool-categories": [("/pool-categories", {}, False)],
        "GET /pool-category/{category_name}": [("/pool-category/default", {}, False)],
        "GET /pools": [("/pools", {}, False)],
        "GET /pool/{pool_id}": [("/pool/%d" % site.pool, {}, False)],
        "GET /comments": [
            ("/comments", {"query": query}, False)
            for query in ("", "post:%d" % site.visible)
        ]
        + [("/comments", {"query": "post:%d" % HIDDEN[0]}, "empty")],
        "GET /comment/{comment_id}": [
            ("/comment/%d" % site.visible_comment, {}, False),
            ("/comment/%d" % site.hidden_comment, {}, True),
        ],
        "GET /snapshots": [
            ("/snapshots", {"query": query, "limit": 100}, False)
            for query in ("", "type:post", "type:pool")
        ],
        "GET /posts": [
            ("/posts", {"query": query, "limit": 100}, False) for query in queries
        ],
        "GET /post/{post_id}": [("/post/%d" % site.visible, {}, False), *hidden_posts],
        "GET /post/{post_id}/content": [("/post/%d/content" % site.visible, {}, False)]
        + [("/post/%d/content" % post_id, {}, True) for post_id in HIDDEN],
        "GET /featured-post": [("/featured-post", {}, False)],
        "GET /post/{post_id}/around": [
            ("/post/%d/around" % site.visible, {"query": query}, False)
            for query in ("", "nsfw")
        ]
        + [("/post/%d/around" % post_id, {}, True) for post_id in HIDDEN],
        "GET /modules/cards/post/{post_id}": [
            ("/modules/cards/post/%d" % post_id, {}, True) for post_id in HIDDEN
        ],
        "GET /modules/cards/post/{post_id}/download": [
            ("/modules/cards/post/%d/download" % post_id, {}, True)
            for post_id in HIDDEN
        ],
    }


def _writes(site: Site, read_asset: Any) -> dict[str, list[dict[str, Any]]]:
    """Every other route: its requests, and whether each names a hidden post."""
    h = HIDDEN[0]
    merge = {"removeVersion": 1, "mergeToVersion": 1, "replaceContent": False}
    hidden_posts = [("/post/%d" % post_id) for post_id in HIDDEN]
    return {
        "POST /users": [{"body": {"name": "newbie", "password": "newbie_pw1"}}],
        "PUT /user/{user_name}": [
            {"path": "/user/the_admin", "body": {"version": 999}}
        ],
        "DELETE /user/{user_name}": [
            {"path": "/user/the_admin", "body": {"version": 999}}
        ],
        "POST /user-token/{user_name}": [{"path": "/user-token/the_admin", "body": {}}],
        "PUT /user-token/{user_name}/{user_token}": [
            {"path": "/user-token/the_admin/nope", "body": {"version": 1}}
        ],
        "DELETE /user-token/{user_name}/{user_token}": [
            {"path": "/user-token/the_admin/nope", "body": {"version": 1}}
        ],
        "POST /password-reset/{user_name}": [
            {
                "path": "/password-reset/the_admin",
                "body": {"token": "nope", "password": "pw_new_1"},
            }
        ],
        "POST /tag-categories": [
            {"body": {"name": "newcat", "color": "red", "order": 5}}
        ],
        "PUT /tag-category/{category_name}": [
            {"path": "/tag-category/default", "body": {"version": 999}}
        ],
        "DELETE /tag-category/{category_name}": [
            {"path": "/tag-category/default", "body": {"version": 999}}
        ],
        "PUT /tag-category/{category_name}/default": [
            {"path": "/tag-category/default/default", "body": {}}
        ],
        "POST /tags": [{"body": {"names": ["brand_new"], "category": "default"}}],
        "PUT /tag/{tag_name}": [{"path": "/tag/nsfw", "body": {"version": 999}}],
        "DELETE /tag/{tag_name}": [{"path": "/tag/safe_one", "body": {"version": 999}}],
        "POST /tag-merge": [
            {
                "body": {
                    "remove": "safe_one",
                    "mergeTo": "explicit",
                    "removeVersion": 999,
                    "mergeToVersion": 999,
                }
            }
        ],
        "POST /pool-categories": [{"body": {"name": "newpools", "color": "red"}}],
        "PUT /pool-category/{category_name}": [
            {"path": "/pool-category/default", "body": {"version": 999}}
        ],
        "DELETE /pool-category/{category_name}": [
            {"path": "/pool-category/default", "body": {"version": 999}}
        ],
        "PUT /pool-category/{category_name}/default": [
            {"path": "/pool-category/default/default", "body": {}}
        ],
        "POST /pool": [
            {
                "body": {
                    "names": ["second_pool"],
                    "category": "default",
                    "posts": [site.visible],
                }
            },
            {
                "body": {"names": ["third_pool"], "category": "default", "posts": [h]},
                "hidden": True,
            },
        ],
        "PUT /pool/{pool_id}": [
            {"path": "/pool/%d" % site.pool, "body": {"version": 999}},
            {
                "path": "/pool/%d" % site.pool,
                "body": {"version": 999, "posts": [site.visible, h]},
                "hidden": True,
            },
        ],
        "DELETE /pool/{pool_id}": [
            {"path": "/pool/%d" % site.pool, "body": {"version": 999}}
        ],
        "POST /pool-merge": [
            {
                "body": {
                    "remove": site.pool,
                    "mergeTo": site.pool,
                    "removeVersion": 999,
                    "mergeToVersion": 999,
                }
            }
        ],
        "POST /comments": [
            {"body": {"postId": site.visible, "text": "a word"}},
            *(
                {"body": {"postId": post_id, "text": "a word"}, "hidden": True}
                for post_id in HIDDEN
            ),
        ],
        "PUT /comment/{comment_id}": [
            {
                "path": "/comment/%d" % site.visible_comment,
                "body": {"version": 999, "text": "x"},
            },
            {
                "path": "/comment/%d" % site.hidden_comment,
                "body": {"version": 1, "text": "x"},
                "hidden": True,
            },
        ],
        "DELETE /comment/{comment_id}": [
            {
                "path": "/comment/%d" % site.hidden_comment,
                "body": {"version": 1},
                "hidden": True,
            }
        ],
        "PUT /comment/{comment_id}/score": [
            {
                "path": "/comment/%d/score" % site.hidden_comment,
                "body": {"score": 1},
                "hidden": True,
            }
        ],
        "DELETE /comment/{comment_id}/score": [
            {"path": "/comment/%d/score" % site.hidden_comment, "hidden": True}
        ],
        "POST /uploads": [{"files": {"content": read_asset("gif.gif")}}],
        # the hidden card again: that it is on the site is all an answer may say
        "POST /posts": [
            {
                "body": {"safety": "safe", "tags": []},
                "files": {"content": site.hidden_content},
            }
        ],
        "POST /posts/reverse-search": [{"files": {"content": site.hidden_content}}],
        "PUT /post/{post_id}": [
            {
                "path": "/post/%d" % site.visible,
                "body": {"version": 999, "source": "x"},
            },
            *(
                {"path": path, "body": {"version": 1, "source": "x"}, "hidden": True}
                for path in hidden_posts
            ),
        ],
        "DELETE /post/{post_id}": [
            {"path": path, "body": {"version": 1}, "hidden": True}
            for path in hidden_posts
        ],
        "POST /post-merge": [
            {"body": {"remove": site.visible, "mergeTo": h, **merge}, "hidden": True},
            {"body": {"remove": h, "mergeTo": site.visible, **merge}, "hidden": True},
        ],
        "POST /featured-post": [
            {"body": {"id": post_id}, "hidden": True} for post_id in HIDDEN
        ],
        "PUT /post/{post_id}/score": [
            {"path": path + "/score", "body": {"score": 1}, "hidden": True}
            for path in hidden_posts
        ],
        "DELETE /post/{post_id}/score": [
            {"path": path + "/score", "hidden": True} for path in hidden_posts
        ],
        "POST /post/{post_id}/favorite": [
            {"path": path + "/favorite", "hidden": True} for path in hidden_posts
        ],
        "DELETE /post/{post_id}/favorite": [
            {"path": path + "/favorite", "hidden": True} for path in hidden_posts
        ],
    }


def test_every_route_is_walked(nsfw_site, read_asset):
    client, site = nsfw_site
    walked = set(_gets(site)) | set(_writes(site, read_asset))
    assert sorted(_routes(client) - walked) == []
    assert sorted(walked - _routes(client)) == []


def test_no_answer_to_an_anonymous_user_holds_a_hidden_post(nsfw_site, read_asset):
    client, site = nsfw_site
    problems = []
    for route, requests in _gets(site).items():
        for path, query, names_hidden in requests:
            _fresh()
            response = client.get(path, query=query)
            if names_hidden == "empty":
                # a search for it: finds nothing, though it says what it was asked
                found = response.json()
                if (found.get("total"), found.get("results")) != (0, []):
                    problems.append(
                        "%s %s: found %s" % (route, query, found.get("total"))
                    )
                continue
            if names_hidden:
                if response.status_code != 404:
                    problems.append(
                        "%s %s: %d, not 404" % (route, path, response.status_code)
                    )
                continue
            if response.status_code >= 500:
                problems.append("%s %s: %d" % (route, path, response.status_code))
            leaks = _leaks(response.text, site)
            if leaks:
                problems.append("%s %s %s: %s" % (route, path, query, leaks))
    for route, requests in _writes(site, read_asset).items():
        method, template = route.split(" ", 1)
        for request in requests:
            _fresh()
            response = client.request(
                method,
                request.get("path", template),
                body=request.get("body"),
                files=request.get("files"),
            )
            label = "%s %s" % (route, request.get("path", ""))
            if response.status_code >= 500:
                problems.append("%s: %d" % (label, response.status_code))
            if request.get("hidden"):
                if response.status_code < 400:
                    problems.append(
                        "%s: %d, not refused" % (label, response.status_code)
                    )
                # an error may say the id it was given back; nothing else
                continue
            leaks = _leaks(response.text, site)
            if leaks:
                problems.append("%s: %s" % (label, leaks))
    assert problems == []


def test_a_search_naming_a_hidden_post_finds_nothing(nsfw_site):
    client, _site = nsfw_site
    for post_id in HIDDEN:
        _fresh()
        found = client.get("/posts", query={"query": "id:%d" % post_id}).json()
        assert (found["total"], found["results"]) == (0, [])


def test_a_request_naming_a_hidden_post_finds_nothing(nsfw_site):
    client, _site = nsfw_site
    for path in (
        "/post/%d",
        "/post/%d/around",
        "/modules/cards/post/%d",
        "/modules/cards/post/%d/download",
    ):
        for post_id in HIDDEN:
            response = client.get(path % post_id)
            assert response.status_code == 404, (path, response.text)
            assert response.json()["name"] == "PostNotFoundError"


def test_the_duplicate_of_a_hidden_post_says_only_that_it_is_there(nsfw_site):
    client, site = nsfw_site
    response = client.post(
        "/posts",
        body={"safety": "safe", "tags": []},
        files={"content": site.hidden_content},
    )
    body = response.json()
    assert response.status_code == 400
    assert body["name"] == "PostAlreadyUploadedError"
    assert "otherPostId" not in body and "otherPostUrl" not in body
    # and no second copy was made
    checksum = db.session.get(model.Post, HIDDEN[0]).checksum
    assert (
        db.session.query(model.Post).filter(model.Post.checksum == checksum).count()
        == 1
    )


def test_what_the_duplicate_check_loaded_stays_hidden_in_its_request(nsfw_site):
    # one anonymous request, in the functions: the upload's duplicate check
    # looks at every post, the hidden one too; whatever that query loaded
    # must not come back to anything later in the same request
    _client, site = nsfw_site
    _fresh()
    # a scope of its own, as the middleware opens; the session is the test's
    token = db.begin_scope()
    try:
        visibility.begin_request()
        anonymous = model.User()
        anonymous.rank = model.User.RANK_ANONYMOUS
        visibility.set_viewer(anonymous)
        assert visibility.hides_nsfw()
        post = model.Post()
        post.post_id = 9100099
        # kept until the end: its traceback holds the check's frame, and with
        # it anything the check loaded, as any reference would (the session
        # itself holds what it loaded only weakly)
        with pytest.raises(posts.PostAlreadyUploadedError) as raised:
            posts.update_post_content(post, site.hidden_content)

        with pytest.raises(posts.PostNotFoundError):
            posts.get_post_by_id(HIDDEN[0])
        assert posts.try_get_post_by_id(HIDDEN[0]) is None
        assert posts.get_posts_by_ids([HIDDEN[0]]) == []
        assert db.session.get(model.Post, HIDDEN[0]) is None
        for query in ("id:%d" % HIDDEN[0], ""):
            _count, found = _search_executor.execute(query, 0, 100, None)
            found_posts = cast(list[model.Post], found)
            assert HIDDEN[0] not in [one.post_id for one in found_posts]
        # a row that points at the post, loaded later: its post is not handed
        # out of the session either
        scores = db.session.query(model.PostScore).all()
        # (the admin's score of it is there: scores are not filtered)
        assert [score.post for score in scores if score.post_id == HIDDEN[0]] == [None]
        # and the error itself names nothing of it
        assert not raised.value.extra_fields
    finally:
        db.end_scope(token)


def test_a_query_of_all_posts_may_not_load_them(nsfw_site):
    # what it loaded would stay in the session (see above): columns only
    _client, _site = nsfw_site
    token = db.begin_scope()
    try:
        visibility.begin_request()
        everything = {visibility.ALL_POSTS: True}
        for statement in (
            sa.select(model.Post),
            sa.select(sa_orm.aliased(model.Post)),
        ):
            with pytest.raises(RuntimeError, match="columns, not entities"):
                db.session.execute(statement, execution_options=everything)
        found = db.session.execute(
            sa.select(model.Post.post_id), execution_options=everything
        ).scalars()
        assert set(HIDDEN) <= set(found)
    finally:
        db.end_scope(token)


def test_a_logged_in_user_sees_them_all(nsfw_site, user_factory):
    client, site = nsfw_site
    user = user_factory(name="member", rank=model.User.RANK_REGULAR)
    db.session.add(user)
    db.session.flush()
    for post_id in HIDDEN:
        response = client.get("/post/%d" % post_id, user=user)
        assert response.status_code == 200, response.text
        assert response.json()["nsfw"] is True
    found = client.get("/posts", user=user, query={"query": "", "limit": 100}).json()
    assert {post["id"] for post in found["results"]} >= set(HIDDEN)
    card = client.get("/modules/cards/post/%d" % HIDDEN[0], user=user)
    assert card.status_code == 200 and card.json()["name"] == CARD_NAME
    visible = client.get("/post/%d" % site.visible, user=user).json()
    assert visible["nsfw"] is False
    assert [relation["id"] for relation in visible["relations"]] == [HIDDEN[0]]


def test_the_counts_of_a_search_leave_them_out(nsfw_site):
    client, site = nsfw_site
    found = client.get("/posts", query={"query": "", "limit": 100}).json()
    assert [post["id"] for post in found["results"]] == [site.visible]
    assert found["total"] == 1
    assert client.get("/info").json()["postCount"] == 1
    assert client.get("/posts", query={"query": "nsfw"}).json()["total"] == 0


def test_an_implication_changed_counts_from_the_next_request(nsfw_site, user_factory):
    client, _site = nsfw_site
    admin = db.session.query(model.User).filter(model.User.name == "the_admin").one()
    explicit = client.get("/tag/explicit", user=admin).json()
    response = client.put(
        "/tag/explicit",
        user=admin,
        body={"version": explicit["version"], "implications": []},
    )
    assert response.status_code == 200, response.text
    # explicit no longer implies nsfw: its posts, and very_explicit's, are shown
    assert client.get("/post/%d" % HIDDEN[1]).status_code == 200
    assert client.get("/post/%d" % HIDDEN[2]).status_code == 200
    assert client.get("/post/%d" % HIDDEN[0]).status_code == 404
    assert client.get("/post/%d" % HIDDEN[1], user=admin).json()["nsfw"] is False


def test_a_cycle_of_implications_ends(nsfw_site):
    client, _site = nsfw_site
    admin = db.session.query(model.User).filter(model.User.name == "the_admin").one()
    nsfw = client.get("/tag/nsfw", user=admin).json()
    response = client.put(
        "/tag/nsfw",
        user=admin,
        body={"version": nsfw["version"], "implications": ["very_explicit"]},
    )
    assert response.status_code == 200, response.text
    for post_id in HIDDEN:
        assert client.get("/post/%d" % post_id).status_code == 404
        assert client.get("/post/%d" % post_id, user=admin).json()["nsfw"] is True


def test_in_open_mode_nothing_is_hidden(start, user_factory, read_asset):
    client = start("open")
    admin = user_factory(name="the_admin", rank=model.User.RANK_ADMINISTRATOR)
    db.session.add(admin)
    db.session.flush()
    created = client.post(
        "/posts",
        user=admin,
        body={"safety": "unsafe", "tags": ["nsfw"]},
        files={"content": read_asset("png.png")},
    ).json()
    shown = client.get("/post/%d" % created["id"])
    assert shown.status_code == 200
    assert shown.json()["nsfw"] is True
    assert client.get("/info").json()["visibility"] == "open"


# login


# what an anonymous user may still do on a site for its users only
LOGIN_OPEN = {
    "GET /info",
    "GET /password-reset/{user_name}",
    "POST /password-reset/{user_name}",
}


def _fill(template: str) -> str:
    return (
        template.replace("{post_id}", "1")
        .replace("{user_name}", "the_admin")
        .replace("{user_token}", "nope")
        .replace("{comment_id}", "1")
        .replace("{pool_id}", "1")
        .replace("{tag_name}", "nsfw")
        .replace("{category_name}", "default")
    )


def test_in_login_mode_an_anonymous_user_may_do_nothing_else(
    start, user_factory, read_asset
):
    client = start("login", _all_privileges(model.User.RANK_ANONYMOUS))
    admin = user_factory(
        name="the_admin", rank=model.User.RANK_ADMINISTRATOR, email="a@example.com"
    )
    db.session.add(admin)
    db.session.flush()
    client.post(
        "/posts",
        user=admin,
        body={"safety": "safe", "tags": ["nsfw"]},
        files={"content": read_asset("png.png")},
    )
    problems = []
    for route in sorted(_routes(client)):
        method, template = route.split(" ", 1)
        files = (
            {"content": read_asset("png.png")}
            if template in ("/uploads", "/posts", "/posts/reverse-search")
            else None
        )
        response = client.request(method, _fill(template), body={}, files=files)
        refused = (
            response.status_code == 403 and response.json().get("name") == "AuthError"
        )
        if route in LOGIN_OPEN:
            if refused:
                problems.append("%s: refused" % route)
        elif not refused:
            problems.append(
                "%s: %d %s" % (route, response.status_code, response.text[:80])
            )
    assert problems == []
    assert client.get("/info").json()["visibility"] == "login"


def test_in_login_mode_a_user_logs_in_and_sees_as_ever(start, user_factory, read_asset):
    client = start("login", None)
    config.config["privileges"]["posts:list"] = model.User.RANK_ANONYMOUS
    user = user_factory(name="member", rank=model.User.RANK_REGULAR)
    user.password_salt = "salt"
    user.password_hash, user.password_revision = auth.get_password_hash(
        "salt", "member_pw1"
    )
    db.session.add(user)
    db.session.flush()
    token = client.post(
        "/user-token/member",
        headers={"Authorization": "Basic bWVtYmVyOm1lbWJlcl9wdzE="},
        body={},
    )
    assert token.status_code == 200, token.text
    assert client.get("/posts", user=user).status_code == 200
    assert client.get("/posts").status_code == 403
