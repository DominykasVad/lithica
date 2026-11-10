"""Every feature route is enumerated; fields, searches and batching follow switches."""

import re
from unittest.mock import patch

import pytest
from fastapi.routing import iter_route_contexts

from lithica import config, db, errors, model
from lithica.app import create_app
from lithica.func import posts, site_settings
from lithica.search import Executor
from lithica.search.configs import PostSearchConfig
from lithica.tests.api.http import shipped_config

ROUTES = {
    ("GET", "/pools"): ("pools",),
    ("POST", "/pool"): ("pools",),
    ("GET", "/pool/{pool_id}"): ("pools",),
    ("PUT", "/pool/{pool_id}"): ("pools",),
    ("DELETE", "/pool/{pool_id}"): ("pools",),
    ("POST", "/pool-merge"): ("pools",),
    ("GET", "/pool-categories"): ("pools",),
    ("POST", "/pool-categories"): ("pools",),
    ("GET", "/pool-category/{category_name}"): ("pools",),
    ("PUT", "/pool-category/{category_name}"): ("pools",),
    ("DELETE", "/pool-category/{category_name}"): ("pools",),
    ("PUT", "/pool-category/{category_name}/default"): ("pools",),
    ("GET", "/comments"): ("comments",),
    ("POST", "/comments"): ("comments",),
    ("GET", "/comment/{comment_id}"): ("comments",),
    ("PUT", "/comment/{comment_id}"): ("comments",),
    ("DELETE", "/comment/{comment_id}"): ("comments",),
    ("PUT", "/comment/{comment_id}/score"): ("comments", "scores"),
    ("DELETE", "/comment/{comment_id}/score"): ("comments", "scores"),
    ("PUT", "/post/{post_id}/score"): ("scores",),
    ("DELETE", "/post/{post_id}/score"): ("scores",),
    ("POST", "/post/{post_id}/favorite"): ("favorites",),
    ("DELETE", "/post/{post_id}/favorite"): ("favorites",),
}


@pytest.fixture
def site(
    config_injector, tmpdir, user_factory, post_factory, comment_factory, pool_factory
):
    settings = shipped_config(str(tmpdir.mkdir("feature-data")))
    settings["features"] = dict.fromkeys(site_settings.FEATURES, True)
    config_injector(settings)
    category = model.TagCategory("default")
    category.color = "default"
    category.default = True
    category.order = 1
    db.session.add(category)
    user = user_factory(name="walker", rank=model.User.RANK_ADMINISTRATOR)
    post = post_factory()
    comment = comment_factory(user=user, post=post)
    pool = pool_factory()
    db.session.add_all([user, post, comment, pool])
    db.session.flush()
    return user, post, comment, pool


def test_walk_covers_every_feature_route():
    found = set()
    for route in iter_route_contexts(create_app().routes):
        path = re.sub(r":[^}]+\}", "}", getattr(route, "path", "")).rstrip("/")
        if any(part in path for part in ("pool", "comment", "/score", "/favorite")):
            for method in getattr(route, "methods", ()):
                found.add((method, path))
    assert found == set(ROUTES)


@pytest.mark.parametrize("entry", sorted(ROUTES))
def test_route_switch(client, site, entry):
    user, post, comment, pool = site
    method, template = entry
    path = template.format(
        post_id=post.post_id,
        comment_id=comment.comment_id,
        pool_id=pool.pool_id,
        category_name=pool.category.name,
    )
    kwargs = {"body": {}} if method != "GET" else {}
    for feature in ROUTES[entry]:
        config.config["features"][feature] = False
        for spelling in (path, path + "/"):
            result = client.request(method, spelling, user=user, **kwargs)
            assert result.status_code == 404, result.text
            assert result.json()["name"] == "FeatureDisabledError"
            assert feature in result.json()["description"]
        config.config["features"][feature] = True
    result = client.request(method, path, user=user, **kwargs)
    assert result.status_code != 404, result.text
    assert result.status_code < 500, result.text


@pytest.mark.parametrize("resource", ["post", "user", "comment"])
@pytest.mark.parametrize("explicit", [False, True])
def test_disabled_fields(client, site, resource, explicit):
    user, post, comment, _ = site
    mapping = site_settings.FEATURE_FIELDS[resource]
    for feature, fields in mapping.items():
        config.config["features"][feature] = False
        path = {
            "post": f"/post/{post.post_id}",
            "user": f"/user/{user.name}",
            "comment": f"/comment/{comment.comment_id}",
        }[resource]
        answer = client.get(
            path, user=user, query={"fields": ",".join(fields)} if explicit else None
        )
        assert answer.status_code == 200, answer.text
        assert not (set(answer.json()) & fields)
        config.config["features"][feature] = True


@pytest.mark.parametrize(
    "feature,tokens",
    [
        (
            "scores",
            [
                "score:1",
                "liked:x",
                "disliked:x",
                "sort:score",
                "special:liked",
                "special:disliked",
                "special:tumbleweed",
            ],
        ),
        (
            "favorites",
            [
                "fav:x",
                "fav-count:1",
                "fav-date:today",
                "fav-time:today",
                "sort:fav-count",
                "sort:fav-date",
                "sort:fav-time",
                "special:fav",
                "special:tumbleweed",
            ],
        ),
        (
            "comments",
            [
                "comment:x",
                "comment-count:1",
                "comment-date:today",
                "comment-time:today",
                "sort:comment-count",
                "sort:comment-date",
                "sort:comment-time",
                "special:tumbleweed",
            ],
        ),
        ("notes", ["note-count:1", "note-text:x", "sort:note-count"]),
        ("pools", ["pool:x"]),
    ],
)
def test_search_refuses_disabled_feature(site, feature, tokens):
    config.config["features"][feature] = False
    for token in tokens:
        with pytest.raises(errors.SearchError, match=feature):
            Executor(PostSearchConfig()).execute(token, 0, 10, site[0])


def test_notes_dependency(client, site):
    user, post, _, _ = site
    config.config["features"]["notes"] = False
    for method, path, notes in [
        ("PUT", f"/post/{post.post_id}", []),
        ("POST", "/posts", [{"text": "x"}]),
    ]:
        answer = client.request(method, path, user=user, body={"notes": notes})
        assert answer.status_code == 404
        assert answer.json()["name"] == "FeatureDisabledError"
    for body in ({}, {"notes": []}):
        assert client.post("/posts", user=user, body=body).status_code != 404


def test_batch_does_not_load_disabled_fields(site):
    user, post, _, _ = site
    config.config["features"] = dict.fromkeys(site_settings.FEATURES, False)
    disabled = set().union(*site_settings.FEATURE_FIELDS["post"].values())
    for fields in ([], list(disabled)):
        assert not (posts._fields_asked(fields) & disabled)
        with (
            patch(
                "lithica.func.posts._relationship_loaders",
                wraps=posts._relationship_loaders,
            ) as loaders,
            patch("lithica.func.comments.load_comment_scores") as scores,
        ):
            posts.preload_posts([post], user, fields)
            assert not (loaders.call_args.args[0] & disabled)
            scores.assert_not_called()


def test_shipped_defaults_and_info(client, site):
    config.config["features"] = config._file_config("config.yaml.dist")["features"]
    assert config.config["features"] == {
        "pools": True,
        "favorites": True,
        "scores": False,
        "notes": True,
        "comments": False,
    }
    info = client.get("/info", user=site[0]).json()
    assert info["features"] == config.config["features"]
