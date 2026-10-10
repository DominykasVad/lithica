from collections.abc import Callable
from typing import Any

import sqlalchemy as sa

from lithica.model.base import Base
from lithica.model.user import User


def get_resource_info(entity: Base) -> tuple[Any, Any, str]:
    # each serializer reads an attribute only its own kind of entity has
    serializers: dict[str, Callable[[Any], Any]] = {
        "tag": lambda tag: tag.first_name,
        "tag_category": lambda category: category.name,
        "comment": lambda comment: comment.comment_id,
        "post": lambda post: post.post_id,
        "pool": lambda pool: pool.pool_id,
        "pool_category": lambda category: category.name,
    }

    resource_type = entity.__tablename__
    assert resource_type in serializers

    primary_key: Any = sa.inspection.inspect(entity).identity
    assert primary_key is not None
    assert len(primary_key) == 1

    resource_name: str = str(serializers[resource_type](entity))
    assert resource_name

    resource_pkey: Any = primary_key[0]
    assert resource_pkey

    return (resource_type, resource_pkey, resource_name)


def get_aux_entity(
    session: Any,
    # the auxiliary table depends on the kind of entity, see the callers
    get_table_info: Callable[[Base], tuple[Any, Callable[[Any], Any]]],
    entity: Base,
    user: User,
) -> Any:
    table, get_column = get_table_info(entity)
    return (
        session.query(table)
        .filter(get_column(table) == get_column(entity))
        .filter(table.user_id == user.user_id)
        .one_or_none()
    )
