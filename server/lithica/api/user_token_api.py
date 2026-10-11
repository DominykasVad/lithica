from typing import Annotated, Any

from fastapi import Depends

from lithica import db, model
from lithica.api import resources
from lithica.api.dependencies import CurrentUser, Fields, read_body
from lithica.api.routing import ApiRouter
from lithica.api.schemas import (
    Bool,
    Int,
    RequestModel,
    Str,
    optional,
    request_body,
    required,
)
from lithica.func import auth, user_tokens, users, versions

router = ApiRouter(tags=["User tokens"])


class UserTokenCreate(RequestModel):
    enabled: Bool = True
    note: Str = optional()
    expiration_time: Str = optional()


class UserTokenUpdate(RequestModel):
    version: Int = required()
    enabled: Bool = optional()
    note: Str = optional()
    expiration_time: Str = optional()


# Any: the serializer's output, which the response model describes
def _serialize(
    user_token: model.UserToken, auth_user: model.User, fields: list[str]
) -> Any:
    return user_tokens.serialize_user_token(user_token, auth_user, options=fields)


@router.get(
    "/user-tokens/{user_name}",
    response_model=resources.Unpaged[resources.UserToken],
    summary="List the login tokens of a user",
)
def get_user_tokens(user_name: str, auth_user: CurrentUser, fields: Fields) -> Any:
    """
    Searches for user tokens for the given user.

    Errors:

    - privileges are too low
    """
    user = users.get_user_by_name(user_name)
    infix = "self" if auth_user.user_id == user.user_id else "any"
    auth.verify_privilege(auth_user, "user_tokens:list:%s" % infix)
    user_token_list = user_tokens.get_user_tokens(user)
    return {
        "results": [_serialize(token, auth_user, fields) for token in user_token_list]
    }


@router.post(
    "/user-token/{user_name}",
    response_model=resources.UserToken,
    summary="Create a login token",
    openapi_extra=request_body(UserTokenCreate),
)
def create_user_token(
    user_name: str,
    auth_user: CurrentUser,
    fields: Fields,
    body: Annotated[UserTokenCreate, Depends(read_body(UserTokenCreate))],
) -> Any:
    """
    Creates a new user token that can be used for authentication of API
    endpoints instead of a password.

    Errors:

    - privileges are too low
    """
    user = users.get_user_by_name(user_name)
    infix = "self" if auth_user.user_id == user.user_id else "any"
    auth.verify_privilege(auth_user, "user_tokens:create:%s" % infix)
    user_token = user_tokens.create_user_token(user, body.enabled)
    if body.has("note"):
        user_tokens.update_user_token_note(user_token, body.note)
    if body.has("expiration_time"):
        user_tokens.update_user_token_expiration_time(user_token, body.expiration_time)
    db.session.add(user_token)
    db.session.commit()
    return _serialize(user_token, auth_user, fields)


@router.put(
    "/user-token/{user_name}/{user_token}",
    response_model=resources.UserToken,
    summary="Update a login token",
    openapi_extra=request_body(UserTokenUpdate),
)
def update_user_token(
    user_name: str,
    user_token: str,
    auth_user: CurrentUser,
    fields: Fields,
    body: Annotated[UserTokenUpdate, Depends(read_body(UserTokenUpdate))],
) -> Any:
    """
    Updates an existing user token using specified parameters. All fields except
    the `version` are optional - update concerns only provided fields.

    Errors:

    - the version is outdated
    - the user token does not exist
    - privileges are too low
    """
    user = users.get_user_by_name(user_name)
    infix = "self" if auth_user.user_id == user.user_id else "any"
    auth.verify_privilege(auth_user, "user_tokens:edit:%s" % infix)
    token = user_tokens.get_existing_by_user_and_token(user, user_token)
    versions.verify_version(token, body.require("version"))
    versions.bump_version(token)
    if body.has("enabled"):
        auth.verify_privilege(auth_user, "user_tokens:edit:%s" % infix)
        user_tokens.update_user_token_enabled(token, body.enabled)
    if body.has("note"):
        auth.verify_privilege(auth_user, "user_tokens:edit:%s" % infix)
        user_tokens.update_user_token_note(token, body.note)
    if body.has("expiration_time"):
        auth.verify_privilege(auth_user, "user_tokens:edit:%s" % infix)
        user_tokens.update_user_token_expiration_time(token, body.expiration_time)
    user_tokens.update_user_token_edit_time(token)
    db.session.commit()
    return _serialize(token, auth_user, fields)


@router.delete(
    "/user-token/{user_name}/{user_token}",
    response_model=resources.Empty,
    summary="Delete a login token",
)
def delete_user_token(user_name: str, user_token: str, auth_user: CurrentUser) -> Any:
    """
    Deletes existing user token.

    Errors:

    - the token does not exist
    - privileges are too low
    """
    user = users.get_user_by_name(user_name)
    infix = "self" if auth_user.user_id == user.user_id else "any"
    auth.verify_privilege(auth_user, "user_tokens:delete:%s" % infix)
    token = user_tokens.get_by_user_and_token(user, user_token)
    if token is not None:
        db.session.delete(token)
        db.session.commit()
    return {}
