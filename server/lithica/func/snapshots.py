from collections.abc import Callable
from typing import Any

import sqlalchemy.orm as sa_orm

from lithica import db, model
from lithica.func import diff, net, users, util


def get_tag_category_snapshot(category: model.TagCategory) -> dict[str, Any]:
    assert category
    return {
        "name": category.name,
        "color": category.color,
        "default": True if category.default else False,
    }


def get_tag_snapshot(tag: model.Tag) -> dict[str, Any]:
    assert tag
    return {
        "names": [tag_name.name for tag_name in tag.names],
        "category": tag.category.name,
        "suggestions": sorted(rel.first_name for rel in tag.suggestions),
        "implications": sorted(rel.first_name for rel in tag.implications),
    }


def get_pool_category_snapshot(category: model.PoolCategory) -> dict[str, Any]:
    assert category
    return {
        "name": category.name,
        "color": category.color,
        "default": True if category.default else False,
    }


def get_pool_snapshot(pool: model.Pool) -> dict[str, Any]:
    assert pool
    return {
        "names": [pool_name.name for pool_name in pool.names],
        "category": pool.category.name,
        "posts": [post.post_id for post in pool.posts],
    }


def get_post_snapshot(post: model.Post) -> dict[str, Any]:
    assert post
    return {
        "source": post.source,
        "safety": post.safety,
        "checksum": post.checksum,
        "flags": post.flags,
        "featured": post.is_featured,
        "tags": sorted([tag.first_name for tag in post.tags]),
        "relations": sorted([rel.post_id for rel in post.relations]),
        "notes": sorted(
            [
                {
                    "polygon": [[point[0], point[1]] for point in note.polygon],
                    "text": note.text,
                }
                for note in post.notes
            ],
            key=lambda x: x["polygon"],
        ),
    }


# keyed by resource type; each factory takes the model of its own type
_snapshot_factories: dict[str, Callable[[Any], dict[str, Any]]] = {
    # lambdas allow mocking target functions in the tests
    "tag_category": lambda entity: get_tag_category_snapshot(entity),
    "tag": lambda entity: get_tag_snapshot(entity),
    "post": lambda entity: get_post_snapshot(entity),
    "pool_category": lambda entity: get_pool_category_snapshot(entity),
    "pool": lambda entity: get_pool_snapshot(entity),
}


def serialize_snapshot(
    snapshot: model.Snapshot, auth_user: model.User
) -> dict[str, Any]:
    assert snapshot
    return {
        "operation": snapshot.operation,
        "type": snapshot.resource_type,
        "id": snapshot.resource_name,
        "user": users.serialize_micro_user(snapshot.user, auth_user),
        "data": snapshot.data,
        "time": snapshot.creation_time,
    }


def _post_to_webhooks(snapshot: model.Snapshot) -> None:
    # an anonymous user: the name is left unset, which reads as None
    webhook_user = model.User()
    webhook_user.rank = "anonymous"
    net.post_to_webhooks(serialize_snapshot(snapshot, webhook_user))


def _create(
    operation: str, entity: model.Base, auth_user: model.User | None
) -> model.Snapshot:
    resource_type, resource_pkey, resource_name = model.util.get_resource_info(entity)

    if auth_user and not auth_user.name:
        auth_user = None

    snapshot = model.Snapshot()
    snapshot.creation_time = util.utcnow()
    snapshot.operation = operation
    snapshot.resource_type = resource_type
    snapshot.resource_pkey = resource_pkey
    snapshot.resource_name = resource_name
    snapshot.user = auth_user
    return snapshot


def create(entity: model.Base, auth_user: model.User | None) -> None:
    assert entity
    snapshot = _create(model.Snapshot.OPERATION_CREATED, entity, auth_user)
    snapshot_factory = _snapshot_factories[snapshot.resource_type]
    snapshot.data = snapshot_factory(entity)
    db.session.add(snapshot)
    _post_to_webhooks(snapshot)


def modify(entity: model.Base, auth_user: model.User | None) -> None:
    assert entity

    snapshot = _create(model.Snapshot.OPERATION_MODIFIED, entity, auth_user)
    snapshot_factory = _snapshot_factories[snapshot.resource_type]

    detached_session = sa_orm.sessionmaker(bind=db.session.get_bind())()
    detached_entity = detached_session.get(type(entity), snapshot.resource_pkey)
    assert detached_entity, "Entity not found in DB, have you committed it?"
    detached_snapshot = snapshot_factory(detached_entity)
    detached_session.close()

    active_snapshot = snapshot_factory(entity)

    snapshot.data = diff.get_dict_diff(detached_snapshot, active_snapshot)
    if not snapshot.data:
        return
    db.session.add(snapshot)
    _post_to_webhooks(snapshot)


def delete(entity: model.Base, auth_user: model.User | None) -> None:
    assert entity
    snapshot = _create(model.Snapshot.OPERATION_DELETED, entity, auth_user)
    snapshot_factory = _snapshot_factories[snapshot.resource_type]
    snapshot.data = snapshot_factory(entity)
    db.session.add(snapshot)
    _post_to_webhooks(snapshot)


def merge(
    source_entity: model.Base,
    target_entity: model.Base,
    auth_user: model.User | None,
) -> None:
    assert source_entity
    assert target_entity
    snapshot = _create(model.Snapshot.OPERATION_MERGED, source_entity, auth_user)
    (
        resource_type,
        _resource_pkey,
        resource_name,
    ) = model.util.get_resource_info(target_entity)
    snapshot.data = [resource_type, resource_name]
    db.session.add(snapshot)
    _post_to_webhooks(snapshot)
