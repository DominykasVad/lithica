"""
A site of posts that have everything a post can have, for the tests of the
post lists: tags in several categories (one of which implies the NSFW tag),
relations, notes, pools in two categories, favourites, scores, comments with
scores, featurings, card content and a custom thumbnail. In `nsfw-login`,
about one post in five is hidden from anonymous users, through the NSFW tag
or a tag that implies it, and hidden posts are related to and pooled with
shown ones.
"""

import base64
from datetime import datetime, timedelta
from typing import Any

import sqlalchemy.orm as sa_orm

from lithica import db, model
from lithica.app import create_app
from lithica.func import site_settings, user_tokens
from lithica.tests.api.http import ok
from lithica.tests.conftest import ApiClient
from lithica.tests.modules import cards

NSFW = "nsfw"
IMPLIES_NSFW = "lewd"
# a tag of each category, used round the posts
CATEGORY_TAGS = {
    "default": ["outdoor", "smile", "long_hair", "hat", "sword", "night"],
    "character": ["ada", "bryn", "cass", "dov"],
    "series": ["first_series", "second_series"],
    "meta": ["highres", "commission", "sketch"],
}
START = datetime(2026, 1, 1)


def _user(name: str, rank: str) -> model.User:
    user = model.User()
    user.name = name
    user.password_salt = "dummy"
    user.password_hash = "dummy"
    user.email = "%s@example.com" % name
    user.rank = rank
    user.creation_time = START
    user.avatar_style = model.User.AVATAR_GRAVATAR
    db.session.add(user)
    return user


def users() -> dict[str, model.User]:
    """The uploader (an administrator) and two regular users."""
    found = {
        "ada": _user("ada", model.User.RANK_ADMINISTRATOR),
        "bob": _user("bob", model.User.RANK_REGULAR),
        "cy": _user("cy", model.User.RANK_REGULAR),
    }
    db.session.flush()
    return found


def _tags_of(index: int) -> list[str]:
    names: list[str] = []
    for category, tags in CATEGORY_TAGS.items():
        names.append(tags[index % len(tags)])
        if category == "default":
            names.append(tags[(index * 7 + 3) % len(tags)])
    if index % 5 == 2:
        names.append(NSFW)
    if index % 11 == 4:
        names.append(IMPLIES_NSFW)
    return sorted(set(names))


def build(
    client: ApiClient,
    people: dict[str, model.User],
    count: int,
    headers: dict[str, str] | None = None,
    uploads: int | None = None,
) -> list[int]:
    """
    `count` posts of ada's; their ids, oldest first. The first `uploads`
    (all, by default) are cards uploaded through the API, as ada's requests
    or, with `headers`, requests with those (ada's credentials, for requests
    that run in sessions of their own). The others are made directly, with
    a copy of the first one's extracted content: an upload takes a while.
    """
    ada, bob, cy = people["ada"], people["bob"], people["cy"]
    uploads = count if uploads is None else min(uploads, count)
    if db.session.query(model.TagCategory).filter_by(default=True).first() is None:
        default = model.TagCategory("default")
        default.color = "default"
        default.order = 1
        default.default = True
        db.session.add(default)
        db.session.flush()
    ids: list[int] = []
    for index in range(uploads):
        files = {"content": cards.png_card(cards.v2_card(name="Card %d" % index))}
        if index % 9 == 0:
            files["thumbnail"] = cards.picture(shade=index % 200)
        created = ok(
            client.post(
                "/posts",
                user=None if headers else ada,
                headers=headers,
                body={"safety": "safe", "tags": _tags_of(index)},
                files=files,
            )
        )
        ids.append(created["id"])
    db.session.expire_all()
    contents = (
        db.session.query(model.PostContent)
        .filter(model.PostContent.post_id == ids[0])
        .options(sa_orm.undefer(model.PostContent.payload))
        .all()
        if ids
        else []
    )
    default_category = db.session.query(model.TagCategory).filter_by(default=True).one()
    for index in range(uploads, count):
        post = model.Post()
        post.user = ada
        post.safety = model.Post.SAFETY_SAFE
        post.type = model.Post.TYPE_IMAGE
        post.mime_type = "image/png"
        post.checksum = "made-%d" % index
        post.flags = []
        post.creation_time = START
        post.tags = [_tag_or_new(name, default_category) for name in _tags_of(index)]
        db.session.add(post)
        db.session.flush()
        for content in contents:
            db.session.add(
                model.PostContent(
                    post_id=post.post_id,
                    kind=content.kind,
                    schema_version=content.schema_version,
                    payload=content.payload,
                    extracted_at=content.extracted_at,
                )
            )
        ids.append(post.post_id)
    db.session.flush()

    # the tags into their categories, and one that implies the NSFW tag
    colors = {"character": "green", "series": "purple", "meta": "gray"}
    for name, color in colors.items():
        category = model.TagCategory(name)
        category.color = color
        category.order = len(name)
        db.session.add(category)
        db.session.flush()
        for tag_name in CATEGORY_TAGS[name]:
            tag = _tag(tag_name)
            if tag is not None:
                tag.category = category
    nsfw, lewd = _tag(NSFW), _tag(IMPLIES_NSFW)
    if nsfw is not None and lewd is not None:
        db.session.add(model.TagImplication(lewd.tag_id, nsfw.tag_id))

    posts = {post.post_id: post for post in db.session.query(model.Post).all()}
    for position, post_id in enumerate(ids):
        post = posts[post_id]
        when = START + timedelta(hours=position)
        # fixed times: two sites built alike give the same answers
        post.creation_time = when
        post.external_ids = [
            model.PostExternalId(
                host="test-home",
                external_id="Post / %d:Mixed" % position,
                creation_time=when,
                user_id=ada.user_id,
            )
        ]
        # relations: to the one before and to one three ahead, both ways, as
        # the API stores them
        for other in (position - 1, position + 3):
            if 0 <= other < len(ids) and other != position:
                related = posts[ids[other]]
                if related not in post.relations:
                    post.relations.append(related)
                if post not in related.relations:
                    related.relations.append(post)
        if position % 2 == 0:
            for corner in range(2):
                note = model.PostNote()
                note.post = post
                note.polygon = [[0.1 * corner, 0.1], [0.5, 0.1], [0.5, 0.5]]
                note.text = "note %d of %d" % (corner, position)
                db.session.add(note)
        for user, score in ((bob, 1), (cy, -1 if position % 3 else 1)):
            if (position + user.user_id) % 2 == 0:
                db.session.add(
                    model.PostScore(post=post, user=user, score=score, time=when)
                )
        for user in (ada, bob):
            if position % (3 if user is ada else 4) == 0:
                db.session.add(model.PostFavorite(post=post, user=user, time=when))
        for number, user in enumerate((bob, cy)):
            if (position + number) % 3 != 2:
                comment = model.Comment()
                comment.post = post
                comment.user = user
                comment.text = "comment %d on %d" % (number, position)
                comment.creation_time = when + timedelta(minutes=number)
                db.session.add(comment)
                db.session.flush()
                db.session.add(
                    model.CommentScore(comment=comment, user=ada, score=1, time=when)
                )
        if position % 25 == 1:
            db.session.add(model.PostFeature(post=post, user=ada, time=when))

    pool_categories = []
    for name, color in (("default", "blue"), ("collection", "red")):
        category = db.session.query(model.PoolCategory).filter_by(name=name).first()
        if category is None:
            category = model.PoolCategory(name)
            category.color = color
            category.default = name == "default"
            db.session.add(category)
        pool_categories.append(category)
    for number in range(5):
        pool = model.Pool()
        pool.names = [model.PoolName("pool_%d" % number, 0)]
        pool.description = "Pool %d" % number
        pool.category = pool_categories[number % 2]
        pool.creation_time = START + timedelta(days=number)
        db.session.add(pool)
        db.session.flush()
        members = ids[number::5] + ids[number + 1 :: 7]
        for order, post_id in enumerate(dict.fromkeys(members)):
            pool_post = model.PoolPost(posts[post_id])
            pool_post.pool = pool
            pool_post.order = order
            db.session.add(pool_post)
    db.session.flush()
    db.session.expire_all()
    return ids


def _tag_or_new(name: str, category: model.TagCategory) -> model.Tag:
    tag = _tag(name)
    if tag is None:
        tag = model.Tag()
        tag.names = [model.TagName(name, 0)]
        tag.category = category
        tag.creation_time = START
        db.session.add(tag)
        db.session.flush()
    return tag


def _tag(name: str) -> model.Tag | None:
    row = db.session.query(model.TagName).filter(model.TagName.name == name).first()
    return db.session.get(model.Tag, row.tag_id) if row is not None else None


def every_field() -> list[str]:
    """The name of every post field the site has, the requested ones too."""
    from lithica import registry
    from lithica.func import posts

    names = set(posts.get_engine_post_field_names())
    names |= set(registry.post_fields()) | set(registry.requested_post_fields())
    return sorted(names)


def config_overrides() -> dict[str, Any]:
    return {
        "features": dict.fromkeys(site_settings.FEATURES, True),
        "visibility": "nsfw-login",
        "nsfw_tag": NSFW,
        "modules": ["cards"],
    }


def header(name: str) -> dict[str, str]:
    """The Authorization header of one of the users (see `committed_site`)."""
    value = "%s:%s-token" % (name, name)
    return {"Authorization": "Token " + base64.b64encode(value.encode()).decode()}


def committed_site(count: int, uploads: int) -> tuple[ApiClient, list[int]]:
    """
    The site, committed, for requests that each run in a session of their
    own (the `committing_session` fixture), as the server runs them: each
    user has a login token, sent with `header`. The configuration (with
    `config_overrides`) and the modules are the caller's to set first.
    """
    with db.session_scope():
        people = users()
        for user in people.values():
            db.session.add(
                user_tokens.new_token(
                    user, True, model.UserToken.KIND_LOGIN, "%s-token" % user.name
                )
            )
        # committed before the uploads, which look for it in their own sessions
        default = model.TagCategory("default")
        default.color = "default"
        default.order = 1
        default.default = True
        db.session.add(default)
        db.session.commit()
    with db.session_scope():
        people = {user.name: user for user in db.session.query(model.User).all()}
        client = ApiClient(create_app())
        ids = build(client, people, count, headers=header("ada"), uploads=uploads)
        db.session.commit()
    return client, ids
