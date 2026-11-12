"""
An edit (PUT) that names nothing to change, only the `version`, still bumps
the version, and of most resources the edit time and a snapshot. With an app
token it must be refused (auth.verify_app_token_changed_something): the
token may change only what a privilege it was granted allows.

The walk takes every PUT route of the application as it is built, the
engine's and those of every module in lithica/modules (registry.available()),
from the application's routes themselves. Each route needs an entry in
RESOURCES, which makes one resource for it: a new PUT route fails the test
until it is added there, so it cannot skip the guard silently.

The requests run as the server runs them, each with a session of its own on
committed tables, so a refused request is rolled back and what is checked
afterwards is what was committed.
"""

import base64
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pytest
import sqlalchemy as sa
from fastapi.routing import iter_route_contexts
from fastapi.testclient import TestClient

from lithica import db, errors, model, registry
from lithica.app import create_app
from lithica.func import (
    auth,
    file_uploads,
    post_content,
    posts,
    site_settings,
    user_tokens,
    util,
)
from lithica.tests.api.http import assert_error, shipped_config
from lithica.tests.conftest import get_unique_name
from lithica.tests.modules import cards

WALKER = "walker"


def _header(value: str) -> dict[str, str]:
    credentials = base64.b64encode(("%s:%s" % (WALKER, value)).encode()).decode()
    return {"Authorization": "Token %s" % credentials, "Accept": "application/json"}


def _walker() -> model.User:
    return db.session.scalars(
        sa.select(model.User).where(model.User.name == WALKER)
    ).one()


def _post() -> model.Post:
    post = model.Post()
    post.safety = model.Post.SAFETY_SAFE
    post.type = model.Post.TYPE_IMAGE
    post.checksum = get_unique_name()
    post.flags = []
    post.mime_type = "image/png"
    post.creation_time = util.utcnow()
    return post


def _make_post() -> tuple[str, Any]:
    post = _post()
    db.session.add(post)
    db.session.flush()
    return "/post/%d" % post.post_id, post


def _make_post_kind() -> tuple[str, Any]:
    path, post = _make_post()
    return path + "/kind", post


CARD_FILE_REPLACEMENT = cards.png_card(cards.v2_card(name="New walker"))


def _make_card_file() -> tuple[str, Any]:
    post, _ = posts.create_post(
        cards.png_card(cards.v2_card(name="Walker")), [], _walker()
    )
    db.session.flush()
    post_content.after_file_or_kind(post, _walker())
    file_uploads.save(CARD_FILE_REPLACEMENT)
    return "/modules/cards/post/%d/file" % post.post_id, post


def _make_external_ids() -> tuple[str, Any]:
    path, post = _make_post()
    return path + "/external-ids", post


def _make_typed_relation() -> tuple[str, Any]:
    _, source = _make_post()
    _, target = _make_post()
    row = model.PostTypedRelation(
        from_post_id=source.post_id,
        to_post_id=target.post_id,
        type="gallery-of",
        creation_time=util.utcnow(),
    )
    db.session.add(row)
    db.session.flush()
    return "/typed-relation/%d" % row.typed_relation_id, row


def _make_user() -> tuple[str, Any]:
    user = model.User()
    user.name = get_unique_name()
    user.password_salt = "dummy"
    user.password_hash = "dummy"
    user.email = "dummy"
    user.rank = model.User.RANK_REGULAR
    user.creation_time = util.utcnow()
    user.avatar_style = model.User.AVATAR_GRAVATAR
    db.session.add(user)
    db.session.flush()
    return "/user/%s" % user.name, user


def _make_user_token() -> tuple[str, Any]:
    token = user_tokens.new_token(
        _walker(), True, model.UserToken.KIND_LOGIN, get_unique_name()
    )
    db.session.add(token)
    db.session.flush()
    return "/user-token/%s/%d" % (WALKER, token.user_token_id), token


def _make_app_token() -> tuple[str, Any]:
    token = user_tokens.new_token(
        _walker(), True, model.UserToken.KIND_APP, get_unique_name()
    )
    token.note = "an app"
    token.rights = ["read"]
    db.session.add(token)
    db.session.flush()
    return "/app-token/%s/%d" % (WALKER, token.user_token_id), token


def _tag_category() -> model.TagCategory:
    category = model.TagCategory(get_unique_name())
    category.color = "dummy"
    category.order = 1
    db.session.add(category)
    db.session.flush()
    return category


def _make_tag() -> tuple[str, Any]:
    tag = model.Tag()
    name = get_unique_name()
    tag.names = [model.TagName(name, 0)]
    tag.category = _tag_category()
    tag.creation_time = util.utcnow()
    db.session.add(tag)
    db.session.flush()
    return "/tag/%s" % name, tag


def _make_tag_category() -> tuple[str, Any]:
    category = _tag_category()
    return "/tag-category/%s" % category.name, category


def _make_tag_category_default() -> tuple[str, Any]:
    category = _tag_category()
    return "/tag-category/%s/default" % category.name, category


def _pool_category() -> model.PoolCategory:
    category = model.PoolCategory(get_unique_name())
    category.color = "dummy"
    db.session.add(category)
    db.session.flush()
    return category


def _make_pool() -> tuple[str, Any]:
    pool = model.Pool()
    pool.names = [model.PoolName(get_unique_name(), 0)]
    pool.category = _pool_category()
    pool.creation_time = util.utcnow()
    db.session.add(pool)
    db.session.flush()
    return "/pool/%d" % pool.pool_id, pool


def _make_pool_category() -> tuple[str, Any]:
    category = _pool_category()
    return "/pool-category/%s" % category.name, category


def _make_pool_category_default() -> tuple[str, Any]:
    category = _pool_category()
    return "/pool-category/%s/default" % category.name, category


def _comment() -> model.Comment:
    post = _post()
    db.session.add(post)
    comment = model.Comment()
    comment.user = _walker()
    comment.post = post
    comment.text = "a comment"
    comment.creation_time = util.utcnow()
    db.session.add(comment)
    db.session.flush()
    return comment


def _make_comment() -> tuple[str, Any]:
    comment = _comment()
    return "/comment/%d" % comment.comment_id, comment


def _make_post_score() -> tuple[str, Any]:
    path, post = _make_post()
    return path + "/score", post


def _make_comment_score() -> tuple[str, Any]:
    path, comment = _make_comment()
    return path + "/score", comment


@dataclass(frozen=True)
class Entry:
    """
    What makes one resource for a PUT route: the path to send to, and the
    resource whose state is checked. `needs` is what the route takes besides
    the version (the text of a comment, a score): such a route refuses a
    version-only body of a login token as incomplete, as it always has, and
    is sent the complete body as well. `refused_with` is how it refuses the
    read-only app token's version-only body: AuthError, but for a route that
    asks for the missing field before the privilege. `incomplete_with` names
    the login token's missing-input error when a route requires a file.
    """

    make: Callable[[], tuple[str, Any]]
    needs: dict[str, Any] | None = None
    refused_with: type[Exception] = errors.AuthError
    incomplete_with: type[Exception] = errors.MissingRequiredParameterError


# every PUT route of the application (without the trailing slash, which each
# also answers to, and without a path converter)
def _make_site_settings() -> tuple[str, Any]:
    return "/site-settings", db.session.get(model.SiteSettingsVersion, 1)


RESOURCES: dict[str, Entry] = {
    "/site-settings": Entry(_make_site_settings, {"values": {}}),
    "/modules/cards/post/{post_id}/file": Entry(
        _make_card_file,
        {"contentToken": util.get_sha1(CARD_FILE_REPLACEMENT), "keepOldPicture": False},
        incomplete_with=errors.MissingRequiredFileError,
    ),
    "/post/{post_id}": Entry(_make_post),
    "/post/{post_id}/external-ids": Entry(_make_external_ids, {"externalIds": []}),
    "/typed-relation/{relation_id}": Entry(_make_typed_relation, {"label": None}),
    "/post/{post_id}/kind": Entry(_make_post_kind, {"kind": "media"}),
    "/post/{post_id}/score": Entry(_make_post_score, {"score": 1}),
    "/user/{user_name}": Entry(_make_user),
    "/user-token/{user_name}/{token_id}": Entry(_make_user_token),
    "/app-token/{user_name}/{token_id}": Entry(_make_app_token),
    "/tag/{tag_name}": Entry(_make_tag),
    "/tag-category/{category_name}": Entry(_make_tag_category),
    "/tag-category/{category_name}/default": Entry(_make_tag_category_default),
    "/pool/{pool_id}": Entry(_make_pool),
    "/pool-category/{category_name}": Entry(_make_pool_category),
    "/pool-category/{category_name}/default": Entry(_make_pool_category_default),
    # asks for the text before the privilege
    "/comment/{comment_id}": Entry(
        _make_comment, {"text": "changed"}, errors.MissingRequiredParameterError
    ),
    "/comment/{comment_id}/score": Entry(_make_comment_score, {"score": 1}),
}

CONVERTER = re.compile(r":[^}]+\}")


def _raw_put_paths(app: Any) -> set[str]:
    found: set[str] = set()
    for route in iter_route_contexts(app.routes):
        path = getattr(route, "path", None)
        if path and "PUT" in (getattr(route, "methods", None) or set()):
            found.add(path)
    return found


def _put_routes(app: Any) -> list[str]:
    return sorted(
        {CONVERTER.sub("}", path).rstrip("/") for path in _raw_put_paths(app)}
    )


def _state(cls: type, key: Any) -> dict[str, Any]:
    """What a version-only edit would change: committed, read afresh."""
    with db.session_scope():
        resource = db.session.get(cls, key)
        assert resource is not None
        return {
            "version": getattr(resource, "version", None),
            "label": getattr(resource, "label", None),
            "lastEditTime": getattr(resource, "last_edit_time", None),
            "snapshots": db.session.scalar(
                sa.select(sa.func.count()).select_from(model.Snapshot)
            ),
        }


@pytest.fixture
def site(config_injector, tmpdir, committing_session) -> dict[str, Any]:
    settings = shipped_config(str(tmpdir.mkdir("data")))
    settings["features"] = dict.fromkeys(site_settings.FEATURES, True)
    config_injector(settings)
    registry.use(registry.available())
    with db.session_scope():
        category = model.TagCategory("default")
        category.color = "dummy"
        category.order = 1
        category.default = True
        db.session.add(category)
        pool_category = model.PoolCategory("default")
        pool_category.color = "dummy"
        pool_category.default = True
        db.session.add(pool_category)
        walker = model.User()
        walker.name = WALKER
        walker.password_salt = "dummy"
        walker.password_hash = "dummy"
        walker.email = "dummy"
        walker.rank = model.User.RANK_ADMINISTRATOR
        walker.creation_time = util.utcnow()
        walker.avatar_style = model.User.AVATAR_GRAVATAR
        db.session.add(walker)
        login_value = get_unique_name()
        app_value = auth.generate_app_token()
        login = user_tokens.new_token(
            walker, True, model.UserToken.KIND_LOGIN, login_value
        )
        app_token = user_tokens.new_token(
            walker, True, model.UserToken.KIND_APP, app_value
        )
        app_token.note = "read only"
        app_token.rights = ["read"]
        db.session.add_all([login, app_token])
        db.session.commit()
    return {"login": login_value, "app": app_value}


def test_every_put_route_is_in_the_table(site):
    routes = _put_routes(create_app())
    # the walk sees the routes, not an empty list
    assert "/post/{post_id}" in routes
    new = [route for route in routes if route not in RESOURCES]
    assert new == [], "new PUT route: add it here: %s" % new
    gone = [route for route in RESOURCES if route not in routes]
    assert gone == [], "no such PUT route any more: %s" % gone


@pytest.mark.parametrize("template", sorted(RESOURCES))
def test_a_version_only_put(site, template):
    entry = RESOURCES[template]
    client = TestClient(create_app(), follow_redirects=False)
    with db.session_scope():
        path, resource = entry.make()
        cls = type(resource)
        key = sa.inspect(resource).identity[0]
        db.session.commit()
    before = _state(cls, key)
    version_only = {"version": before["version"]}

    # a read-only app token: refused, and nothing changed; on the path with
    # the trailing slash too, where the route has that twin (a tag's name
    # may hold a slash: its route has none)
    spellings = [path]
    if template + "/" in _raw_put_paths(client.app):
        spellings.append(path + "/")
    for spelling in spellings:
        refused = client.put(spelling, headers=_header(site["app"]), json=version_only)
        assert_error(refused, entry.refused_with)
        assert _state(cls, key) == before, spelling
    if entry.needs is not None:
        complete = version_only | entry.needs
        refused = client.put(path, headers=_header(site["app"]), json=complete)
        assert_error(refused, errors.AuthError)
        assert _state(cls, key) == before

    # a login token: as before
    answer = client.put(path, headers=_header(site["login"]), json=version_only)
    if entry.needs is None:
        assert answer.status_code == 200, answer.text
    else:
        assert_error(answer, entry.incomplete_with)
        assert _state(cls, key) == before
        answer = client.put(
            path, headers=_header(site["login"]), json=version_only | entry.needs
        )
        assert answer.status_code == 200, answer.text
