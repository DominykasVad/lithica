from typing import Annotated, Any

from fastapi import Depends

from lithica import db, model
from lithica.api import resources
from lithica.api.dependencies import CurrentUser, Fields, read_body, require
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
from lithica.func import auth, snapshots, tag_categories, versions

router = ApiRouter(tags=["Tag categories"])


class TagCategoryCreate(RequestModel):
    name: Str = required()
    color: Str = required()
    order: Int = required()


class TagCategoryUpdate(RequestModel):
    version: Int = required()
    name: Str = optional()
    color: Str = optional()
    order: Int = optional()


# Any: the serializer's output, which the response model describes
def _serialize(category: model.TagCategory, fields: list[str]) -> Any:
    return tag_categories.serialize_category(category, options=fields)


@router.get(
    "/tag-categories",
    response_model=resources.Unpaged[resources.TagCategory],
    summary="List tag categories",
)
def get_tag_categories(
    _user: Annotated[model.User, Depends(require("tag_categories:list"))],
    fields: Fields,
) -> Any:
    categories = tag_categories.get_all_categories()
    return {
        "results": [_serialize(category, fields) for category in categories],
    }


@router.post(
    "/tag-categories",
    response_model=resources.TagCategory,
    summary="Create a tag category",
    openapi_extra=request_body(TagCategoryCreate),
)
def create_tag_category(
    auth_user: Annotated[model.User, Depends(require("tag_categories:create"))],
    fields: Fields,
    body: Annotated[TagCategoryCreate, Depends(read_body(TagCategoryCreate))],
) -> Any:
    name = body.require("name")
    color = body.require("color")
    order = body.require("order")
    category = tag_categories.create_category(name, color, order)
    db.session.add(category)
    db.session.flush()
    snapshots.create(category, auth_user)
    db.session.commit()
    return _serialize(category, fields)


@router.get(
    "/tag-category/{category_name}",
    response_model=resources.TagCategory,
    summary="Get a tag category",
)
def get_tag_category(
    category_name: str,
    _user: Annotated[model.User, Depends(require("tag_categories:view"))],
    fields: Fields,
) -> Any:
    category = tag_categories.get_category_by_name(category_name)
    return _serialize(category, fields)


@router.put(
    "/tag-category/{category_name}",
    response_model=resources.TagCategory,
    summary="Update a tag category",
    openapi_extra=request_body(TagCategoryUpdate),
)
def update_tag_category(
    category_name: str,
    auth_user: CurrentUser,
    fields: Fields,
    body: Annotated[TagCategoryUpdate, Depends(read_body(TagCategoryUpdate))],
) -> Any:
    """Only the fields that are sent are changed."""
    category = tag_categories.get_category_by_name(category_name, lock=True)
    versions.verify_version(category, body.require("version"))
    versions.bump_version(category)
    if body.has("name"):
        auth.verify_privilege(auth_user, "tag_categories:edit:name")
        tag_categories.update_category_name(category, body.name)
    if body.has("color"):
        auth.verify_privilege(auth_user, "tag_categories:edit:color")
        tag_categories.update_category_color(category, body.color)
    if body.has("order"):
        auth.verify_privilege(auth_user, "tag_categories:edit:order")
        tag_categories.update_category_order(category, body.order)
    db.session.flush()
    snapshots.modify(category, auth_user)
    db.session.commit()
    return _serialize(category, fields)


@router.delete(
    "/tag-category/{category_name}",
    response_model=resources.Empty,
    summary="Delete a tag category",
    openapi_extra=request_body(VersionOnly),
)
def delete_tag_category(
    category_name: str,
    auth_user: CurrentUser,
    body: Annotated[VersionOnly, Depends(read_body(VersionOnly))],
) -> Any:
    category = tag_categories.get_category_by_name(category_name, lock=True)
    versions.verify_version(category, body.require("version"))
    auth.verify_privilege(auth_user, "tag_categories:delete")
    tag_categories.delete_category(category)
    snapshots.delete(category, auth_user)
    db.session.commit()
    return {}


@router.put(
    "/tag-category/{category_name}/default",
    response_model=resources.TagCategory,
    summary="Make a tag category the default one",
)
def set_tag_category_as_default(
    category_name: str,
    auth_user: Annotated[model.User, Depends(require("tag_categories:set_default"))],
    fields: Fields,
) -> Any:
    category = tag_categories.get_category_by_name(category_name, lock=True)
    tag_categories.set_default_category(category)
    db.session.flush()
    snapshots.modify(category, auth_user)
    db.session.commit()
    return _serialize(category, fields)
