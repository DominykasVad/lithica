from collections.abc import Callable
from typing import Any

from lithica import db, errors, model
from lithica.func import util


class InvalidFavoriteTargetError(errors.ValidationError):
    pass


# The auxiliary table and its key column depend on the kind of entity, which
# is only known at run time, so both are typed loosely.
AuxTableInfo = tuple[Any, Callable[[Any], Any]]


def _get_table_info(entity: model.Base) -> AuxTableInfo:
    assert entity
    resource_type, _, _ = model.util.get_resource_info(entity)
    if resource_type == "post":
        return model.PostFavorite, lambda table: table.post_id
    raise InvalidFavoriteTargetError()


def _get_fav_entity(entity: model.Base, user: model.User) -> Any:
    assert entity
    assert user
    return model.util.get_aux_entity(db.session, _get_table_info, entity, user)


def has_favorited(entity: model.Base, user: model.User) -> bool:
    assert entity
    assert user
    return _get_fav_entity(entity, user) is not None


def unset_favorite(entity: model.Base, user: model.User | None) -> None:
    assert entity
    assert user
    fav_entity = _get_fav_entity(entity, user)
    if fav_entity:
        db.session.delete(fav_entity)


def set_favorite(entity: model.Base, user: model.User | None) -> None:
    from lithica.func import scores

    assert entity
    assert user
    try:
        scores.set_score(entity, user, 1)
    except scores.InvalidScoreTargetError:
        pass
    fav_entity = _get_fav_entity(entity, user)
    if not fav_entity:
        table, get_column = _get_table_info(entity)
        fav_entity = table()
        setattr(fav_entity, get_column(table).name, get_column(entity))
        fav_entity.user = user
        fav_entity.time = util.utcnow()
        db.session.add(fav_entity)
