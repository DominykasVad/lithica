"""Typed relations and installation-scoped external IDs on posts."""

import re
import unicodedata
from typing import Any

import sqlalchemy as sa
import sqlalchemy.orm as sa_orm
from sqlalchemy.exc import IntegrityError

from lithica import db, errors, model, registry
from lithica.func import posts, util, visibility
from lithica.search import criteria
from lithica.search.configs.util import unescape
from lithica.search.typing import SaQuery


class InvalidTypedRelationError(errors.ValidationError):
    pass


class TypedRelationAlreadyExistsError(errors.IntegrityError):
    pass


class TypedRelationNotFoundError(errors.NotFoundError):
    pass


class InvalidExternalIdError(errors.ValidationError):
    pass


class ExternalIdTakenError(errors.IntegrityError):
    pass


class ExternalIdNotFoundError(errors.NotFoundError):
    pass


def external_pairs(values: list[dict[str, str]]) -> list[tuple[str, str]]:
    if any("host" not in pair or "id" not in pair for pair in values):
        raise InvalidExternalIdError("Each external ID needs host and id.")
    return [(pair["host"], pair["id"]) for pair in values]


def valid_host(host: str) -> bool:
    return len(host) <= 64 and re.fullmatch(r"[a-z0-9][a-z0-9._-]*", host) is not None


def _has_controls(value: str) -> bool:
    return any(unicodedata.category(char) in {"Cc", "Cs"} for char in value)


def validate_external_id(host: str, external_id: str) -> None:
    if (
        not valid_host(host)
        or not 1 <= len(external_id) <= 256
        or external_id != external_id.strip()
        or _has_controls(external_id)
    ):
        raise InvalidExternalIdError("Invalid external ID or installation host.")


def clean_label(label: str | None) -> str | None:
    if label is None:
        return None
    if _has_controls(label):
        raise InvalidTypedRelationError("A label cannot contain control characters.")
    label = label.strip()
    if len(label) > 128:
        raise InvalidTypedRelationError("A label must be at most 128 characters.")
    return label or None


def relation_type(name: str) -> registry.RelationType:
    for item in registry.relation_types():
        if item.name == name:
            return item
    raise InvalidTypedRelationError("Unknown typed relation type %r." % name)


def get_typed_relation(relation_id: int) -> model.PostTypedRelation:
    row = (
        db.session.query(model.PostTypedRelation)
        .filter_by(typed_relation_id=relation_id)
        .one_or_none()
    )
    if row is None:
        raise TypedRelationNotFoundError("Typed relation not found.")
    return row


def create_typed_relation(
    from_id: int, to_id: int, type_name: str, label: str | None, user: model.User
) -> model.PostTypedRelation:
    source, target = posts.get_post_by_id(from_id), posts.get_post_by_id(to_id)
    item = relation_type(type_name)
    if from_id == to_id:
        raise InvalidTypedRelationError("A typed relation must have distinct posts.")
    for post, allowed in ((source, item.from_kinds), (target, item.to_kinds)):
        if allowed is not None and post.kind not in allowed:
            raise InvalidTypedRelationError(
                "Allowed kinds: %s." % ", ".join(sorted(allowed))
            )
    label = clean_label(label)
    # Serialize concurrent creates touching either end; column-only queries
    # count hidden rows as well, so visibility cannot evade the per-post cap.
    db.session.execute(
        sa.select(model.Post.post_id)
        .where(model.Post.post_id.in_(sorted({from_id, to_id})))
        .order_by(model.Post.post_id)
        .with_for_update(),
        execution_options={visibility.ALL_POSTS: True},
    ).all()
    table = model.PostTypedRelation
    duplicate = (
        db.session.query(table.typed_relation_id)
        .filter_by(from_post_id=from_id, to_post_id=to_id, type=type_name)
        .execution_options(**{visibility.ALL_POSTS: True})
        .first()
    )
    if duplicate:
        raise TypedRelationAlreadyExistsError("Typed relation already exists.")
    for post_id in (from_id, to_id):
        count = (
            db.session.query(sa.func.count(table.typed_relation_id))
            .filter(sa.or_(table.from_post_id == post_id, table.to_post_id == post_id))
            .execution_options(**{visibility.ALL_POSTS: True})
            .scalar()
        )
        if count is not None and count >= 1000:
            raise InvalidTypedRelationError(
                "A post may have at most 1000 typed relations."
            )
    row = table(
        from_post_id=from_id,
        to_post_id=to_id,
        type=type_name,
        label=label,
        creation_time=util.utcnow(),
        user_id=user.user_id,
    )
    db.session.add(row)
    db.session.flush()
    return row


OTHER_FIELDS = [
    "id",
    "kind",
    "type",
    "mimeType",
    "safety",
    "nsfw",
    "contentUrl",
    "thumbnailUrl",
]


def serialize_typed_relations(
    rows: list[model.PostTypedRelation], post_id: int, user: model.User
) -> list[dict[str, Any]]:
    other_ids = [
        row.to_post_id if row.from_post_id == post_id else row.from_post_id
        for row in rows
    ]
    found = {
        post.post_id: post
        for post in db.session.query(model.Post)
        .options(sa_orm.lazyload("*"))
        .filter(model.Post.post_id.in_(other_ids))
    }
    others = [found[other_id] for other_id in other_ids]
    serialized = posts.serialize_posts(others, user, OTHER_FIELDS)
    return [
        dict(
            id=row.typed_relation_id,
            type=row.type,
            label=row.label,
            direction="out" if row.from_post_id == post_id else "in",
            creationTime=row.creation_time,
            post=post,
        )
        for row, post in zip(rows, serialized, strict=True)
    ]


def list_typed_relations(
    post_id: int, type_name: str | None, direction: str
) -> list[model.PostTypedRelation]:
    posts.get_post_by_id(post_id)
    if direction not in {"out", "in", "any"}:
        raise InvalidTypedRelationError("Unknown typed relation direction.")
    if type_name is not None:
        relation_type(type_name)
    table = model.PostTypedRelation
    query = db.session.query(table)
    if direction == "out":
        query = query.filter(table.from_post_id == post_id)
    elif direction == "in":
        query = query.filter(table.to_post_id == post_id)
    else:
        query = query.filter(
            sa.or_(table.from_post_id == post_id, table.to_post_id == post_id)
        )
    if type_name is not None:
        query = query.filter(table.type == type_name)
    return query.order_by(
        table.type, table.creation_time, table.typed_relation_id
    ).all()


def replace_external_ids(
    post: model.Post, pairs: list[tuple[str, str]], user: model.User
) -> None:
    wanted = set(pairs)
    for host, external_id in wanted:
        validate_external_id(host, external_id)
    # Lock the post so two replacements cannot interleave. The unique key
    # arbitrates concurrent claims by different posts in the savepoint below.
    db.session.execute(
        sa.select(model.Post.post_id)
        .where(model.Post.post_id == post.post_id)
        .with_for_update()
    ).all()
    table = model.PostExternalId
    for host, external_id in wanted:
        owner = (
            db.session.query(table.post_id)
            .filter_by(host=host, external_id=external_id)
            .execution_options(**{visibility.ALL_POSTS: True})
            .scalar()
        )
        if owner is not None and owner != post.post_id:
            raise ExternalIdTakenError("External ID is already taken.")
    try:
        with db.session.begin_nested():
            current = {(row.host, row.external_id): row for row in post.external_ids}
            for pair, row in current.items():
                if pair not in wanted:
                    post.external_ids.remove(row)
            for host, external_id in sorted(wanted - current.keys()):
                post.external_ids.append(
                    table(
                        host=host,
                        external_id=external_id,
                        creation_time=util.utcnow(),
                        user_id=user.user_id,
                    )
                )
            db.session.flush()
    except IntegrityError as ex:
        raise ExternalIdTakenError("External ID is already taken.") from ex


def lookup_external_id(host: str, external_id: str) -> model.Post:
    validate_external_id(host, external_id)
    row = (
        db.session.query(model.PostExternalId)
        .filter_by(host=host, external_id=external_id)
        .one_or_none()
    )
    if row is None:
        raise ExternalIdNotFoundError("External ID not found.")
    return posts.get_post_by_id(row.post_id)


def external_host_filter(
    query: SaQuery, criterion: criteria.BaseCriterion | None, negated: bool
) -> SaQuery:
    if not isinstance(criterion, criteria.PlainCriterion):
        raise errors.SearchError("Expected a valid external installation host.")
    host = unescape(criterion.value)
    if not valid_host(host):
        raise errors.SearchError("Expected a valid external installation host.")
    table = model.PostExternalId
    expr = (
        sa.exists().where(table.post_id == model.Post.post_id).where(table.host == host)
    )
    return query.filter(~expr if negated else expr)


def merge_metadata(source: model.Post, target: model.Post) -> None:
    # Load both directions before deletion and flush drops before moves to
    # avoid transient unique conflicts. Preserve creator and creation time.
    table = model.PostTypedRelation
    rows = (
        db.session.query(table)
        .filter(
            sa.or_(
                table.from_post_id.in_([source.post_id, target.post_id]),
                table.to_post_id.in_([source.post_id, target.post_id]),
            )
        )
        .order_by(table.typed_relation_id)
        .all()
    )
    existing = {
        (row.from_post_id, row.to_post_id, row.type)
        for row in rows
        if source.post_id not in (row.from_post_id, row.to_post_id)
    }
    moves: list[tuple[model.PostTypedRelation, int, int]] = []
    for row in rows:
        if source.post_id not in (row.from_post_id, row.to_post_id):
            continue
        from_id = (
            target.post_id if row.from_post_id == source.post_id else row.from_post_id
        )
        to_id = target.post_id if row.to_post_id == source.post_id else row.to_post_id
        key = (from_id, to_id, row.type)
        if from_id == to_id or key in existing:
            db.session.delete(row)
        else:
            existing.add(key)
            moves.append((row, from_id, to_id))
    db.session.flush()
    for row, from_id, to_id in moves:
        row.from_post_id, row.to_post_id = from_id, to_id
    for row in list(source.external_ids):
        source.external_ids.remove(row)
        target.external_ids.append(row)
    db.session.flush()
    # Relationships already read by a caller must not cascade-delete moved rows.
    db.session.expire(source, ["typed_relations_out", "typed_relations_in"])
