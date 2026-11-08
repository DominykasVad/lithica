from typing import Annotated, Any

from fastapi import Depends, Path

from lithica import db, model
from lithica.api import resources
from lithica.api.dependencies import CurrentUser, fields_of, read_body
from lithica.api.routing import ApiRouter
from lithica.api.schemas import (
    AnyList,
    Bool,
    Int,
    RequestModel,
    Str,
    optional,
    request_body,
    required,
)
from lithica.func import app_tokens, auth, user_tokens, users, versions

# checked before the endpoint runs (see fields_of)
CheckedFields = Annotated[list[str], Depends(fields_of(app_tokens.AppTokenSerializer))]

TokenId = Annotated[str, Path(description="The token's `id`.")]

router = ApiRouter(tags=["App tokens"])


class AppTokenCreate(RequestModel):
    name: Str = required()
    rights: AnyList = required()
    enabled: Bool = True
    expiration_time: Str = optional()


class AppTokenUpdate(RequestModel):
    version: Int = required()
    name: Str = optional()
    enabled: Bool = optional()
    expiration_time: Str = optional()


def _infix(auth_user: model.User, user: model.User) -> str:
    return "self" if auth_user.user_id == user.user_id else "any"


@router.get(
    "/app-tokens/{user_name}",
    response_model=resources.Unpaged[resources.AppToken],
    summary="List the app tokens of a user",
)
def get_app_tokens(
    user_name: str, auth_user: CurrentUser, fields: CheckedFields
) -> Any:
    """
    Lists the app tokens of the given user. A token's value is never
    listed: `token` is null.

    Errors:

    - privileges are too low
    """
    user = users.get_user_by_name(user_name)
    auth.verify_privilege(auth_user, "app_tokens:list:%s" % _infix(auth_user, user))
    return {
        "results": [
            app_tokens.serialize_app_token(token, auth_user, fields)
            for token in app_tokens.get_app_tokens(user)
        ]
    }


@router.post(
    "/app-token/{user_name}",
    response_model=resources.AppToken,
    summary="Create an app token",
    openapi_extra=request_body(AppTokenCreate),
)
def create_app_token(
    user_name: str,
    auth_user: CurrentUser,
    fields: CheckedFields,
    body: Annotated[AppTokenCreate, Depends(read_body(AppTokenCreate))],
) -> Any:
    """
    Creates an app token: a token for another application, which may do
    only what its `rights` allow (the names `GET /info` lists in
    `appTokenRights`) and the user's rank grants, and never anything about
    accounts or tokens. `name` is 1 to 128 characters. Its value, `token`,
    is in this response and nowhere else: only a hash of it is stored. The
    rights cannot be changed later; make a new token instead.

    Errors:

    - the name is missing, empty or too long
    - the rights are empty, unknown, or the user holds none of the
      privileges of one of them
    - the expiration time is invalid or in the past
    - privileges are too low
    """
    user = users.get_user_by_name(user_name)
    auth.verify_privilege(auth_user, "app_tokens:create:%s" % _infix(auth_user, user))
    app_token, value = app_tokens.create_app_token(
        user, body.require("name"), body.require("rights"), body.enabled
    )
    if body.has("expiration_time"):
        user_tokens.update_user_token_expiration_time(app_token, body.expiration_time)
    db.session.add(app_token)
    db.session.commit()
    return app_tokens.serialize_app_token(app_token, auth_user, fields, value=value)


@router.put(
    "/app-token/{user_name}/{token_id}",
    response_model=resources.AppToken,
    summary="Update an app token",
    openapi_extra=request_body(AppTokenUpdate),
)
def update_app_token(
    user_name: str,
    token_id: TokenId,
    auth_user: CurrentUser,
    fields: CheckedFields,
    body: Annotated[AppTokenUpdate, Depends(read_body(AppTokenUpdate))],
) -> Any:
    """
    Updates an app token, named by its `id`. All fields except the
    `version` are optional - update concerns only provided fields. The
    rights cannot be changed.

    Errors:

    - the version is outdated
    - the app token does not exist
    - the name or the expiration time is invalid
    - privileges are too low
    """
    user = users.get_user_by_name(user_name)
    auth.verify_privilege(auth_user, "app_tokens:edit:%s" % _infix(auth_user, user))
    app_token = app_tokens.get_existing_by_user_and_id(
        user, user_tokens.parse_token_id(token_id)
    )
    versions.verify_version(app_token, body.require("version"))
    versions.bump_version(app_token)
    if body.has("name"):
        app_tokens.update_app_token_name(app_token, body.name)
    if body.has("enabled"):
        user_tokens.update_user_token_enabled(app_token, body.enabled)
    if body.has("expiration_time"):
        user_tokens.update_user_token_expiration_time(app_token, body.expiration_time)
    user_tokens.update_user_token_edit_time(app_token)
    db.session.commit()
    return app_tokens.serialize_app_token(app_token, auth_user, fields)


@router.delete(
    "/app-token/{user_name}/{token_id}",
    response_model=resources.Empty,
    summary="Revoke an app token",
)
def delete_app_token(user_name: str, token_id: TokenId, auth_user: CurrentUser) -> Any:
    """
    Revokes an app token, named by its `id`: it stops working at once. A
    token that does not exist, or is not an app token of this user, is left
    alone and the answer is the same.

    Errors:

    - privileges are too low
    """
    user = users.get_user_by_name(user_name)
    auth.verify_privilege(auth_user, "app_tokens:delete:%s" % _infix(auth_user, user))
    app_token = user_tokens.get_by_user_and_id(
        user, user_tokens.parse_token_id(token_id), model.UserToken.KIND_APP
    )
    if app_token is not None:
        app_tokens.delete_app_token(app_token)
        db.session.commit()
    return {}
