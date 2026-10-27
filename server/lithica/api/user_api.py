from typing import Annotated, Any

from fastapi import Depends

from lithica import db, model, search
from lithica.api import resources
from lithica.api.dependencies import (
    CurrentUser,
    PageParams,
    RequestDataParam,
    fields_of,
    read_body,
)
from lithica.api.dependencies import search as run_search
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
from lithica.func import auth, users, versions

# checked before the endpoint runs (see fields_of)
CheckedFields = Annotated[list[str], Depends(fields_of(users.UserSerializer))]

router = ApiRouter(tags=["Users"])

_search_executor = search.Executor(search.configs.UserSearchConfig())


class UserCreate(RequestModel):
    name: Str = required()
    password: Str = required()
    email: Str = ""
    rank: Str = optional()
    avatar_style: Str = optional()
    # the picture for the "manual" style, when it is not uploaded as a part
    avatar_url: Str = optional()
    avatar_token: Str = optional()


class UserUpdate(RequestModel):
    version: Int = required()
    name: Str = optional()
    password: Str = optional()
    email: Str = optional()
    rank: Str = optional()
    avatar_style: Str = optional()
    avatar_url: Str = optional()
    avatar_token: Str = optional()


# Any: the serializer's output, which the response model describes
def _serialize(
    user: model.User, auth_user: model.User, fields: list[str], **kwargs: Any
) -> Any:
    return users.serialize_user(user, auth_user, options=fields, **kwargs)


@router.get(
    "/users", response_model=resources.Paged[resources.User], summary="List users"
)
def get_users(auth_user: CurrentUser, fields: CheckedFields, page: PageParams) -> Any:
    """
    Searches for users.

    The tokens `query` understands are listed under "User search" in doc/API.md.

    Errors:

    - privileges are too low
    """
    auth.verify_privilege(auth_user, "users:list")
    return run_search(
        _search_executor, page, lambda user: _serialize(user, auth_user, fields)
    )


@router.post(
    "/users",
    response_model=resources.User,
    summary="Create a user",
    openapi_extra=request_body(UserCreate, "avatar"),
)
def create_user(
    auth_user: CurrentUser,
    fields: CheckedFields,
    data: RequestDataParam,
    body: Annotated[UserCreate, Depends(read_body(UserCreate))],
) -> Any:
    """
    Creates a new user using specified parameters. Names and passwords must
    match `user_name_regex` and `password_regex` from server's configuration,
    respectively. Email address, rank and avatar fields are optional. Avatar
    style can be either `gravatar` or `manual`. `manual` avatar style requires
    client to pass also `avatar` file - see file uploads for details. If the
    rank is empty and the user happens to be the first user ever created, become
    an administrator, whereas subsequent users will be given the rank indicated
    by `default_rank` in the server's configuration.

    Errors:

    - a user with such name already exists (names are case insensitive)
    - either user name, password, email or rank are invalid
    - the user is trying to update their or someone else's rank to higher than
      their own
    - avatar is missing for manual avatar style
    - privileges are too low
    """
    if auth_user.user_id is None:
        auth.verify_privilege(auth_user, "users:create:self")
    else:
        auth.verify_privilege(auth_user, "users:create:any")

    name = body.require("name")
    password = body.require("password")
    user = users.create_user(name, password, body.email)
    if body.has("rank"):
        users.update_user_rank(user, body.rank, auth_user)
    if body.has("avatar_style"):
        users.update_user_avatar(
            user, body.avatar_style, data.get_file("avatar", default=b"")
        )
    db.session.add(user)
    db.session.commit()

    return _serialize(user, auth_user, fields, force_show_email=True)


@router.get("/user/{user_name}", response_model=resources.User, summary="Get a user")
def get_user(user_name: str, auth_user: CurrentUser, fields: CheckedFields) -> Any:
    """
    Retrieves information about an existing user.

    Errors:

    - the user does not exist
    - privileges are too low
    """
    user = users.get_user_by_name(user_name)
    if auth_user.user_id != user.user_id:
        auth.verify_privilege(auth_user, "users:view")
    return _serialize(user, auth_user, fields)


@router.put(
    "/user/{user_name}",
    response_model=resources.User,
    summary="Update a user",
    openapi_extra=request_body(UserUpdate, "avatar"),
)
def update_user(
    user_name: str,
    auth_user: CurrentUser,
    fields: CheckedFields,
    data: RequestDataParam,
    body: Annotated[UserUpdate, Depends(read_body(UserUpdate))],
) -> Any:
    """
    Updates an existing user using specified parameters. Names and passwords
    must match `user_name_regex` and `password_regex` from server's
    configuration, respectively. All fields are optional - update concerns only
    provided fields. To update last login time, see authentication. Avatar style
    can be either `gravatar` or `manual`. `manual` avatar style requires client
    to pass also `avatar` file - see file uploads for details. All fields except
    the `version` are optional - update concerns only provided fields.

    Errors:

    - the version is outdated
    - the user does not exist
    - a user with new name already exists (names are case insensitive)
    - either user name, password, email or rank are invalid
    - the user is trying to update their or someone else's rank to higher than
      their own
    - avatar is missing for manual avatar style
    - privileges are too low
    """
    user = users.get_user_by_name(user_name)
    versions.verify_version(user, body.require("version"))
    versions.bump_version(user)
    infix = "self" if auth_user.user_id == user.user_id else "any"
    if body.has("name"):
        auth.verify_privilege(auth_user, "users:edit:%s:name" % infix)
        users.update_user_name(user, body.name)
    if body.has("password"):
        auth.verify_privilege(auth_user, "users:edit:%s:pass" % infix)
        users.update_user_password(user, body.password)
    if body.has("email"):
        auth.verify_privilege(auth_user, "users:edit:%s:email" % infix)
        users.update_user_email(user, body.email)
    if body.has("rank"):
        auth.verify_privilege(auth_user, "users:edit:%s:rank" % infix)
        users.update_user_rank(user, body.rank, auth_user)
    if body.has("avatar_style"):
        auth.verify_privilege(auth_user, "users:edit:%s:avatar" % infix)
        users.update_user_avatar(
            user, body.avatar_style, data.get_file("avatar", default=b"")
        )
    db.session.commit()
    return _serialize(user, auth_user, fields)


@router.delete(
    "/user/{user_name}",
    response_model=resources.Empty,
    summary="Delete a user",
    openapi_extra=request_body(VersionOnly),
)
def delete_user(
    user_name: str,
    auth_user: CurrentUser,
    body: Annotated[VersionOnly, Depends(read_body(VersionOnly))],
) -> Any:
    """
    Deletes existing user.

    Errors:

    - the version is outdated
    - the user does not exist
    - privileges are too low
    """
    user = users.get_user_by_name(user_name)
    versions.verify_version(user, body.require("version"))
    infix = "self" if auth_user.user_id == user.user_id else "any"
    auth.verify_privilege(auth_user, "users:delete:%s" % infix)
    db.session.delete(user)
    db.session.commit()
    return {}
