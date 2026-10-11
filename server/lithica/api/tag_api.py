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
    RequestModel,
    Str,
    StrList,
    VersionOnly,
    optional,
    request_body,
    required,
)
from lithica.func import auth, snapshots, tags, util, versions

router = ApiRouter(tags=["Tags"])

_search_executor = search.Executor(search.configs.TagSearchConfig())


class TagCreate(RequestModel):
    names: StrList = required()
    category: Str = required()
    description: Str = ""
    suggestions: StrList = []
    implications: StrList = []


class TagUpdate(RequestModel):
    version: Int = required()
    names: StrList = optional()
    category: Str = optional()
    description: Str = optional()
    suggestions: StrList = optional()
    implications: StrList = optional()


class TagMerge(RequestModel):
    remove: Str = required()
    merge_to: Str = required()
    remove_version: Int = required()
    merge_to_version: Int = required()


# Any: the serializer's output, which the response model describes
def _serialize(tag: model.Tag, fields: list[str]) -> Any:
    return tags.serialize_tag(tag, options=fields)


def _create_if_needed(tag_names: list[str], user: model.User) -> None:
    if not tag_names:
        return
    _existing_tags, new_tags = tags.get_or_create_tags_by_names(tag_names)
    if len(new_tags):
        auth.verify_privilege(user, "tags:create")
    db.session.flush()
    for tag in new_tags:
        snapshots.create(tag, user)


@router.get("/tags", response_model=resources.Paged[resources.Tag], summary="List tags")
def get_tags(
    _user: Annotated[model.User, Depends(require("tags:list"))],
    fields: Fields,
    page: PageParams,
) -> Any:
    return run_search(_search_executor, page, lambda tag: _serialize(tag, fields))


@router.post(
    "/tags",
    response_model=resources.Tag,
    summary="Create a tag",
    openapi_extra=request_body(TagCreate),
)
def create_tag(
    auth_user: Annotated[model.User, Depends(require("tags:create"))],
    fields: Fields,
    body: Annotated[TagCreate, Depends(read_body(TagCreate))],
) -> Any:
    """Suggested and implied tags that do not exist yet are created."""
    names = body.require("names")
    category = body.require("category")

    _create_if_needed(body.suggestions, auth_user)
    _create_if_needed(body.implications, auth_user)

    tag = tags.create_tag(names, category, body.suggestions, body.implications)
    tags.update_tag_description(tag, body.description)
    db.session.add(tag)
    db.session.flush()
    snapshots.create(tag, auth_user)
    db.session.commit()
    return _serialize(tag, fields)


# The tag name is the rest of the path: names may contain slashes.


@router.get("/tag/{tag_name:path}", response_model=resources.Tag, summary="Get a tag")
def get_tag(
    tag_name: str,
    _user: Annotated[model.User, Depends(require("tags:view"))],
    fields: Fields,
) -> Any:
    tag = tags.get_tag_by_name(tag_name)
    return _serialize(tag, fields)


@router.put(
    "/tag/{tag_name:path}",
    response_model=resources.Tag,
    summary="Update a tag",
    openapi_extra=request_body(TagUpdate),
)
def update_tag(
    tag_name: str,
    auth_user: CurrentUser,
    fields: Fields,
    body: Annotated[TagUpdate, Depends(read_body(TagUpdate))],
) -> Any:
    """Only the fields that are sent are changed."""
    tag = tags.get_tag_by_name(tag_name)
    versions.verify_version(tag, body.require("version"))
    versions.bump_version(tag)
    if body.has("names"):
        auth.verify_privilege(auth_user, "tags:edit:names")
        tags.update_tag_names(tag, body.names)
    if body.has("category"):
        auth.verify_privilege(auth_user, "tags:edit:category")
        tags.update_tag_category_name(tag, body.category)
    if body.has("description"):
        auth.verify_privilege(auth_user, "tags:edit:description")
        tags.update_tag_description(tag, body.description)
    if body.has("suggestions"):
        auth.verify_privilege(auth_user, "tags:edit:suggestions")
        _create_if_needed(body.suggestions, auth_user)
        tags.update_tag_suggestions(tag, body.suggestions)
    if body.has("implications"):
        auth.verify_privilege(auth_user, "tags:edit:implications")
        _create_if_needed(body.implications, auth_user)
        tags.update_tag_implications(tag, body.implications)
    tag.last_edit_time = util.utcnow()
    db.session.flush()
    snapshots.modify(tag, auth_user)
    db.session.commit()
    return _serialize(tag, fields)


@router.delete(
    "/tag/{tag_name:path}",
    response_model=resources.Empty,
    summary="Delete a tag",
    openapi_extra=request_body(VersionOnly),
)
def delete_tag(
    tag_name: str,
    auth_user: CurrentUser,
    body: Annotated[VersionOnly, Depends(read_body(VersionOnly))],
) -> Any:
    tag = tags.get_tag_by_name(tag_name)
    versions.verify_version(tag, body.require("version"))
    auth.verify_privilege(auth_user, "tags:delete")
    snapshots.delete(tag, auth_user)
    tags.delete(tag)
    db.session.commit()
    return {}


@router.post(
    "/tag-merge",
    response_model=resources.Tag,
    summary="Merge one tag into another",
    openapi_extra=request_body(TagMerge),
)
def merge_tags(
    auth_user: CurrentUser,
    fields: Fields,
    body: Annotated[TagMerge, Depends(read_body(TagMerge))],
) -> Any:
    """
    Remove the tag `remove` and give its posts, suggestions and implications
    to the tag `mergeTo`, which is returned.
    """
    source_tag_name = body.require("remove")
    target_tag_name = body.require("merge_to")
    source_tag = tags.get_tag_by_name(source_tag_name)
    target_tag = tags.get_tag_by_name(target_tag_name)
    versions.verify_version(source_tag, body.require("remove_version"))
    versions.verify_version(target_tag, body.require("merge_to_version"))
    versions.bump_version(target_tag)
    auth.verify_privilege(auth_user, "tags:merge")
    tags.merge_tags(source_tag, target_tag)
    snapshots.merge(source_tag, target_tag, auth_user)
    db.session.commit()
    return _serialize(target_tag, fields)


@router.get(
    "/tag-siblings/{tag_name:path}",
    response_model=resources.Unpaged[resources.TagSibling],
    summary="List the tags most often used together with a tag",
)
def get_tag_siblings(
    tag_name: str,
    _user: Annotated[model.User, Depends(require("tags:view"))],
    fields: Fields,
) -> Any:
    tag = tags.get_tag_by_name(tag_name)
    result = tags.get_tag_siblings(tag)
    serialized_siblings = []
    for sibling, occurrences in result:
        serialized_siblings.append(
            {"tag": _serialize(sibling, fields), "occurrences": occurrences}
        )
    return {"results": serialized_siblings}
