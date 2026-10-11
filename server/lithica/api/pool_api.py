from typing import Annotated, Any

from fastapi import Depends

from lithica import db, model, search
from lithica.api import resources
from lithica.api.dependencies import (
    CurrentUser,
    Fields,
    PageParams,
    read_body,
    require,
)
from lithica.api.dependencies import search as run_search
from lithica.api.routing import ApiRouter
from lithica.api.schemas import (
    Int,
    IntList,
    RequestModel,
    Str,
    StrList,
    VersionOnly,
    optional,
    request_body,
    required,
)
from lithica.func import auth, pools, snapshots, util, versions

router = ApiRouter(tags=["Pools"])

_search_executor = search.Executor(search.configs.PoolSearchConfig())


class PoolCreate(RequestModel):
    names: StrList = required()
    category: Str = required()
    description: Str = ""
    posts: IntList = []


class PoolUpdate(RequestModel):
    version: Int = required()
    names: StrList = optional()
    category: Str = optional()
    description: Str = optional()
    posts: IntList = optional()


class PoolMerge(RequestModel):
    remove: Int = required()
    merge_to: Int = required()
    remove_version: Int = required()
    merge_to_version: Int = required()


# Any: the serializer's output, which the response model describes
def _serialize(pool: model.Pool, fields: list[str]) -> Any:
    return pools.serialize_pool(pool, options=fields)


def _get_pool(pool_id: str) -> model.Pool:
    try:
        return pools.get_pool_by_id(int(pool_id))
    except ValueError:
        # not a number, so not the id of any pool
        raise pools.PoolNotFoundError("Pool %r not found." % pool_id) from None


@router.get(
    "/pools", response_model=resources.Paged[resources.Pool], summary="List pools"
)
def get_pools(
    _user: Annotated[model.User, Depends(require("pools:list"))],
    fields: Fields,
    page: PageParams,
) -> Any:
    return run_search(_search_executor, page, lambda pool: _serialize(pool, fields))


@router.post(
    "/pool",
    response_model=resources.Pool,
    summary="Create a pool",
    openapi_extra=request_body(PoolCreate),
)
def create_pool(
    auth_user: Annotated[model.User, Depends(require("pools:create"))],
    fields: Fields,
    body: Annotated[PoolCreate, Depends(read_body(PoolCreate))],
) -> Any:
    names = body.require("names")
    category = body.require("category")

    pool = pools.create_pool(names, category, body.posts)
    pool.last_edit_time = util.utcnow()
    pools.update_pool_description(pool, body.description)
    db.session.add(pool)
    db.session.flush()
    snapshots.create(pool, auth_user)
    db.session.commit()
    return _serialize(pool, fields)


@router.get("/pool/{pool_id}", response_model=resources.Pool, summary="Get a pool")
def get_pool(
    pool_id: str,
    _user: Annotated[model.User, Depends(require("pools:view"))],
    fields: Fields,
) -> Any:
    pool = _get_pool(pool_id)
    return _serialize(pool, fields)


@router.put(
    "/pool/{pool_id}",
    response_model=resources.Pool,
    summary="Update a pool",
    openapi_extra=request_body(PoolUpdate),
)
def update_pool(
    pool_id: str,
    auth_user: CurrentUser,
    fields: Fields,
    body: Annotated[PoolUpdate, Depends(read_body(PoolUpdate))],
) -> Any:
    """Only the fields that are sent are changed."""
    pool = _get_pool(pool_id)
    versions.verify_version(pool, body.require("version"))
    versions.bump_version(pool)
    if body.has("names"):
        auth.verify_privilege(auth_user, "pools:edit:names")
        pools.update_pool_names(pool, body.names)
    if body.has("category"):
        auth.verify_privilege(auth_user, "pools:edit:category")
        pools.update_pool_category_name(pool, body.category)
    if body.has("description"):
        auth.verify_privilege(auth_user, "pools:edit:description")
        pools.update_pool_description(pool, body.description)
    if body.has("posts"):
        auth.verify_privilege(auth_user, "pools:edit:posts")
        pools.update_pool_posts(pool, body.posts)
    pool.last_edit_time = util.utcnow()
    db.session.flush()
    snapshots.modify(pool, auth_user)
    db.session.commit()
    return _serialize(pool, fields)


@router.delete(
    "/pool/{pool_id}",
    response_model=resources.Empty,
    summary="Delete a pool",
    openapi_extra=request_body(VersionOnly),
)
def delete_pool(
    pool_id: str,
    auth_user: CurrentUser,
    body: Annotated[VersionOnly, Depends(read_body(VersionOnly))],
) -> Any:
    pool = _get_pool(pool_id)
    versions.verify_version(pool, body.require("version"))
    auth.verify_privilege(auth_user, "pools:delete")
    snapshots.delete(pool, auth_user)
    pools.delete(pool)
    db.session.commit()
    return {}


@router.post(
    "/pool-merge",
    response_model=resources.Pool,
    summary="Merge one pool into another",
    openapi_extra=request_body(PoolMerge),
)
def merge_pools(
    auth_user: CurrentUser,
    fields: Fields,
    body: Annotated[PoolMerge, Depends(read_body(PoolMerge))],
) -> Any:
    """
    Remove the pool `remove` and add its posts to the pool `mergeTo`, which
    is returned.
    """
    source_pool_id = body.require("remove")
    target_pool_id = body.require("merge_to")
    source_pool = pools.get_pool_by_id(source_pool_id)
    target_pool = pools.get_pool_by_id(target_pool_id)
    versions.verify_version(source_pool, body.require("remove_version"))
    versions.verify_version(target_pool, body.require("merge_to_version"))
    versions.bump_version(target_pool)
    auth.verify_privilege(auth_user, "pools:merge")
    pools.merge_pools(source_pool, target_pool)
    snapshots.merge(source_pool, target_pool, auth_user)
    db.session.commit()
    return _serialize(target_pool, fields)
