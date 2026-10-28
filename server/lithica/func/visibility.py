"""
Who sees which posts: the site's `visibility` setting.

In `nsfw-login`, the posts that carry the NSFW tag, or a tag that implies
it, do not exist for anonymous users. That is decided here, once, for
everything: every query the ORM runs in a request of an anonymous user
gets the criteria that leave those posts out, and with them their comments,
their snapshots, their place in pools and their featuring. Searches and
their counts, lookups by id, `around`, the featured post, a pool's posts, a
post's relations and the modules' routes all load posts that way, so none
of them needs to know.

What a query cannot leave out, the ids in a snapshot's data, is left out
when a snapshot is serialized (`redact_snapshot_data`).

Fail closed: a request is filtered until its user has been authenticated
as somebody (`set_viewer`). Work outside a request (the admin command, a
background job) is never filtered.

In `login`, anonymous users have no privileges at all (lithica.func.auth).
"""

from collections.abc import Iterable
from typing import Any

import sqlalchemy as sa
import sqlalchemy.event as sa_event
import sqlalchemy.orm as sa_orm

from lithica import config, db, model

OPEN = "open"
NSFW_LOGIN = "nsfw-login"
LOGIN = "login"

# a query that must see every post (the duplicate check of an upload) says
# so. It selects columns only: an entity it loaded would stay in the session,
# and a lookup by primary key or a many-to-one relationship later in the
# request takes it from there without a query, so without the criteria
ALL_POSTS = "lithica_all_posts"

_REQUEST = "visibility.request"
_SEES_ALL = "visibility.sees_all"
_HIDING_TAGS = "visibility.hiding_tags"
_WORKING = "visibility.working"


def mode() -> str:
    return config.config.get("visibility") or OPEN


def nsfw_tag() -> str:
    return config.config.get("nsfw_tag") or "nsfw"


def nsfw_hides_names() -> bool:
    """Whether clients hide a NSFW card's name and creator as its picture."""
    return config.config.get("nsfw_hide_names") is True


def begin_request() -> None:
    """A request starts: nobody is known yet, so it sees what anonymous users see."""
    values = db.scope_values()
    if values is not None:
        values[_REQUEST] = True


def set_viewer(user: model.User) -> None:
    """The request's user is known: a logged-in one sees what their privileges allow."""
    values = db.scope_values()
    if values is not None:
        values[_SEES_ALL] = user.rank != model.User.RANK_ANONYMOUS


def hides_nsfw() -> bool:
    """Whether NSFW posts are left out of what this unit of work sees."""
    if mode() != NSFW_LOGIN:
        return False
    values = db.scope_values()
    if values is None or not values.get(_REQUEST):
        return False
    return not values.get(_SEES_ALL, False)


def _compute_hiding_tag_ids() -> frozenset[int]:
    name = nsfw_tag().lower()
    found = set(
        db.session.execute(
            sa.select(model.TagName.tag_id).where(
                sa.func.lower(model.TagName.name) == name
            )
        ).scalars()
    )
    # every tag that implies one of them, however far: a walk over the
    # implications, each tag once, so that a cycle ends it too
    frontier = set(found)
    while frontier:
        parents = set(
            db.session.execute(
                sa.select(model.TagImplication.parent_id).where(
                    model.TagImplication.child_id.in_(sorted(frontier))
                )
            ).scalars()
        )
        frontier = parents - found
        found |= frontier
    return frozenset(found)


def hiding_tag_ids() -> frozenset[int]:
    """
    The tags that make a post NSFW: the NSFW tag and every tag that implies
    it, directly or through others. Worked out once per request (an
    implication changed is seen by the next one).
    """
    values = db.scope_values()
    if values is not None and _HIDING_TAGS in values:
        return values[_HIDING_TAGS]
    if values is not None:
        values[_WORKING] = True
    try:
        ids = _compute_hiding_tag_ids()
    finally:
        if values is not None:
            values.pop(_WORKING, None)
    if values is not None:
        values[_HIDING_TAGS] = ids
    return ids


def is_nsfw(post: model.Post) -> bool:
    """Whether the post carries the NSFW tag or a tag that implies it."""
    ids = hiding_tag_ids()
    return any(tag.tag_id in ids for tag in post.tags)


def hidden_post_ids(post_ids: Iterable[int]) -> set[int]:
    """Of these posts, those this unit of work may not see."""
    wanted = sorted({post_id for post_id in post_ids if isinstance(post_id, int)})
    if not wanted or not hides_nsfw():
        return set()
    tag_ids = sorted(hiding_tag_ids())
    if not tag_ids:
        return set()
    return set(
        db.session.execute(
            sa.select(model.PostTag.post_id)
            .where(model.PostTag.post_id.in_(wanted))
            .where(model.PostTag.tag_id.in_(tag_ids)),
            execution_options={ALL_POSTS: True},
        ).scalars()
    )


@sa_event.listens_for(sa_orm.Session, "do_orm_execute")
def _leave_out_hidden_posts(state: sa_orm.ORMExecuteState) -> None:
    if not state.is_select or state.is_column_load or state.is_relationship_load:
        return
    if state.execution_options.get(ALL_POSTS):
        if _loads_entities(state.statement):
            raise RuntimeError("A query of all posts selects columns, not entities.")
        return
    values = db.scope_values()
    # the tags' own queries, while the hiding tags are worked out
    if values is not None and values.get(_WORKING):
        return
    if not hides_nsfw():
        return
    # a list, used in the lambdas as it is: SQLAlchemy caches the criteria
    # and takes the list as a parameter of each statement, never baked in
    tag_ids = sorted(hiding_tag_ids())

    # the criteria go with the statement to everything it loads later
    # (relationships, lazily or not); aliases of the entities are covered
    state.statement = state.statement.options(
        sa_orm.with_loader_criteria(
            model.Post,
            lambda cls: (
                ~sa.exists()
                .where(model.PostTag.post_id == cls.post_id)
                .where(model.PostTag.tag_id.in_(tag_ids))
            ),
            include_aliases=True,
        ),
        # the rows that tie a post to a pool, and the featuring of a post
        sa_orm.with_loader_criteria(
            model.PoolPost,
            lambda cls: (
                ~sa.exists()
                .where(model.PostTag.post_id == cls.post_id)
                .where(model.PostTag.tag_id.in_(tag_ids))
            ),
            include_aliases=True,
        ),
        sa_orm.with_loader_criteria(
            model.PostFeature,
            lambda cls: (
                ~sa.exists()
                .where(model.PostTag.post_id == cls.post_id)
                .where(model.PostTag.tag_id.in_(tag_ids))
            ),
            include_aliases=True,
        ),
        sa_orm.with_loader_criteria(
            model.Comment,
            lambda cls: (
                ~sa.exists()
                .where(model.PostTag.post_id == cls.post_id)
                .where(model.PostTag.tag_id.in_(tag_ids))
            ),
            include_aliases=True,
        ),
        sa_orm.with_loader_criteria(
            model.Snapshot,
            lambda cls: (
                ~sa.and_(
                    cls.resource_type == "post",
                    sa.exists()
                    .where(model.PostTag.post_id == cls.resource_pkey)
                    .where(model.PostTag.tag_id.in_(tag_ids)),
                )
            ),
            include_aliases=True,
        ),
    )


def _loads_entities(statement: Any) -> bool:
    # an entity (or an alias of one) is described as its own entity; a
    # column as an expression of one
    return any(
        one.get("entity") is not None and one.get("expr") is one.get("entity")
        for one in getattr(statement, "column_descriptions", [])
    )


def _redact_ids(value: Any, hidden: set[int]) -> Any:
    if isinstance(value, list):
        return [one for one in value if one not in hidden]
    if isinstance(value, dict):
        return {key: _redact_ids(inner, hidden) for key, inner in value.items()}
    return value


def redact_snapshot_data(snapshot: model.Snapshot) -> Any:
    """
    A snapshot's data without the ids of posts this unit of work may not
    see: a pool's posts, a post's relations (a diff's lists as much as a
    whole record's), and the post a post was merged into.
    """
    data = snapshot.data
    if not hides_nsfw() or data is None:
        return data
    if snapshot.operation == model.Snapshot.OPERATION_MERGED:
        if isinstance(data, list) and len(data) == 2 and data[0] == "post":
            # the post merged into, by its name: a post's is its id
            target = str(data[1])
            if target.isdigit() and hidden_post_ids([int(target)]):
                return ["post", None]
        return data
    key = {"pool": "posts", "post": "relations"}.get(snapshot.resource_type)
    if key is None or not isinstance(data, dict):
        return data
    ids = _ids_under(data, key)
    hidden = hidden_post_ids(ids)
    if not hidden:
        return data
    return _redact_under(data, key, hidden)


def _ids_under(data: Any, key: str) -> list[int]:
    found: list[int] = []

    def walk(value: Any, under: bool) -> None:
        if isinstance(value, dict):
            for inner_key, inner in value.items():
                walk(inner, under or inner_key == key)
        elif isinstance(value, list):
            for inner in value:
                if under and isinstance(inner, int):
                    found.append(inner)
                else:
                    walk(inner, under)

    walk(data, False)
    return found


def _redact_under(data: Any, key: str, hidden: set[int]) -> Any:
    if isinstance(data, dict):
        return {
            inner_key: (
                _redact_ids(inner, hidden)
                if inner_key == key
                else _redact_under(inner, key, hidden)
            )
            for inner_key, inner in data.items()
        }
    return data
