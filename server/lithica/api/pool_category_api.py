from typing import Annotated, Any

from fastapi import Depends

from lithica import db, model
from lithica.api import resources
from lithica.api.dependencies import CurrentUser, fields_of, read_body, require
from lithica.api.routing import ApiRouter
from lithica.api.schemas import (
    Int,
    RequestModel,
    Str,
    VersionOnly,
    optional,
    request_body,
    required,
)
from lithica.func import auth, pool_categories, snapshots, versions

# checked before the endpoint runs (see fields_of)
CheckedFields = Annotated[
    list[str], Depends(fields_of(pool_categories.PoolCategorySerializer))
]

router = ApiRouter(tags=["Pool categories"])


class PoolCategoryCreate(RequestModel):
    name: Str = required()
    color: Str = required()


class PoolCategoryUpdate(RequestModel):
    version: Int = required()
    name: Str = optional()
    color: Str = optional()


# Any: the serializer's output, which the response model describes
def _serialize(category: model.PoolCategory, fields: list[str]) -> Any:
    return pool_categories.serialize_category(category, options=fields)


@router.get(
    "/pool-categories",
    response_model=resources.Unpaged[resources.PoolCategory],
    summary="List pool categories",
)
def get_pool_categories(
    _user: Annotated[model.User, Depends(require("pool_categories:list"))],
    fields: CheckedFields,
) -> Any:
    """
    Lists all pool categories. Doesn't use paging.

    Errors:

    - privileges are too low
    """
    categories = pool_categories.get_all_categories()
    return {
        "results": [_serialize(category, fields) for category in categories],
    }


@router.post(
    "/pool-categories",
    response_model=resources.PoolCategory,
    summary="Create a pool category",
    openapi_extra=request_body(PoolCategoryCreate),
)
def create_pool_category(
    auth_user: Annotated[model.User, Depends(require("pool_categories:create"))],
    fields: CheckedFields,
    body: Annotated[PoolCategoryCreate, Depends(read_body(PoolCategoryCreate))],
) -> Any:
    """
    Creates a new pool category using specified parameters. Name must match
    `pool_category_name_regex` from server's configuration. First category
    created becomes the default category.

    Errors:

    - the name is used by an existing pool category (names are case insensitive)
    - the name is invalid or missing
    - the color is invalid or missing
    - privileges are too low
    """
    name = body.require("name")
    color = body.require("color")
    category = pool_categories.create_category(name, color)
    db.session.add(category)
    db.session.flush()
    snapshots.create(category, auth_user)
    db.session.commit()
    return _serialize(category, fields)


@router.get(
    "/pool-category/{category_name}",
    response_model=resources.PoolCategory,
    summary="Get a pool category",
)
def get_pool_category(
    category_name: str,
    _user: Annotated[model.User, Depends(require("pool_categories:view"))],
    fields: CheckedFields,
) -> Any:
    """
    Retrieves information about an existing pool category.

    Errors:

    - the pool category does not exist
    - privileges are too low
    """
    category = pool_categories.get_category_by_name(category_name)
    return _serialize(category, fields)


@router.put(
    "/pool-category/{category_name}",
    response_model=resources.PoolCategory,
    summary="Update a pool category",
    openapi_extra=request_body(PoolCategoryUpdate),
)
def update_pool_category(
    category_name: str,
    auth_user: CurrentUser,
    fields: CheckedFields,
    body: Annotated[PoolCategoryUpdate, Depends(read_body(PoolCategoryUpdate))],
) -> Any:
    """
    Updates an existing pool category using specified parameters. Name must
    match `pool_category_name_regex` from server's configuration. All fields
    except the `version` are optional - update concerns only provided fields.

    Errors:

    - the version is outdated
    - the pool category does not exist
    - the name is used by an existing pool category (names are case insensitive)
    - the name is invalid
    - the color is invalid
    - privileges are too low
    """
    category = pool_categories.get_category_by_name(category_name, lock=True)
    versions.verify_version(category, body.require("version"))
    versions.bump_version(category)
    if body.has("name"):
        auth.verify_privilege(auth_user, "pool_categories:edit:name")
        pool_categories.update_category_name(category, body.name)
    if body.has("color"):
        auth.verify_privilege(auth_user, "pool_categories:edit:color")
        pool_categories.update_category_color(category, body.color)
    db.session.flush()
    snapshots.modify(category, auth_user)
    db.session.commit()
    return _serialize(category, fields)


@router.delete(
    "/pool-category/{category_name}",
    response_model=resources.Empty,
    summary="Delete a pool category",
    openapi_extra=request_body(VersionOnly),
)
def delete_pool_category(
    category_name: str,
    auth_user: CurrentUser,
    body: Annotated[VersionOnly, Depends(read_body(VersionOnly))],
) -> Any:
    """
    Deletes existing pool category. The pool category to be deleted must have no
    usages.

    Errors:

    - the version is outdated
    - the pool category does not exist
    - the pool category is used by some pools
    - the pool category is the last pool category available
    - privileges are too low
    """
    category = pool_categories.get_category_by_name(category_name, lock=True)
    versions.verify_version(category, body.require("version"))
    auth.verify_privilege(auth_user, "pool_categories:delete")
    pool_categories.delete_category(category)
    snapshots.delete(category, auth_user)
    db.session.commit()
    return {}


@router.put(
    "/pool-category/{category_name}/default",
    response_model=resources.PoolCategory,
    summary="Make a pool category the default one",
)
def set_pool_category_as_default(
    category_name: str,
    auth_user: Annotated[model.User, Depends(require("pool_categories:set_default"))],
    fields: CheckedFields,
) -> Any:
    """
    Sets given pool category as default. All new pools created manually or
    automatically will have this category.

    Errors:

    - the pool category does not exist
    - privileges are too low
    """
    category = pool_categories.get_category_by_name(category_name, lock=True)
    pool_categories.set_default_category(category)
    db.session.flush()
    snapshots.modify(category, auth_user)
    db.session.commit()
    return _serialize(category, fields)
