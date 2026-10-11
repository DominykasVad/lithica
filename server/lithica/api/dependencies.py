"""What the endpoints depend on: who is asking, and what they may do."""

import base64
from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, Query, Request
from fastapi.security import APIKeyHeader
from fastapi.security.http import HTTPBase

from lithica import db, errors, model
from lithica.api.error_handlers import HttpError
from lithica.api.schemas import Bool
from lithica.func import auth, user_tokens, users

# where the request's user name is kept for the request log
LOG_USER_KEY = "lithica.user_name"

# These two only describe the accepted credentials in the OpenAPI document.
# The header is read and checked by get_user below; neither of them refuses
# a request.
_basic_scheme = HTTPBase(
    scheme="basic",
    scheme_name="basicAuth",
    description="User name and password.",
    auto_error=False,
)
_token_scheme = APIKeyHeader(
    name="Authorization",
    scheme_name="tokenAuth",
    description="`Token ` followed by the base64 of `user-name:login-token`.",
    auto_error=False,
)


def _anonymous_user() -> model.User:
    # the name is left unset, which reads as None
    user = model.User()
    user.rank = model.User.RANK_ANONYMOUS
    return user


def _authenticate_basic_auth(username: str, password: str) -> model.User:
    user = users.get_user_by_name(username)
    if not auth.is_valid_password(user, password):
        raise errors.AuthError("Invalid password.")
    return user


def _authenticate_token(
    username: str, token: str
) -> tuple[model.User, model.UserToken]:
    user = users.get_user_by_name(username)
    user_token = user_tokens.get_by_user_and_token(user, token)
    if user_token is None or not auth.is_valid_token(user_token):
        raise errors.AuthError("Invalid token.")
    return user, user_token


def _decode_credentials(credentials: str) -> list[str]:
    return base64.decodebytes(credentials.encode("ascii")).decode("utf8").split(":", 1)


def _authenticate(header: str, bump_login: bool) -> model.User:
    auth_token = None
    try:
        auth_type, credentials = header.split(" ", 1)
        if auth_type.lower() == "basic":
            username, password = _decode_credentials(credentials)
            auth_user = _authenticate_basic_auth(username, password)
        elif auth_type.lower() == "token":
            username, token = _decode_credentials(credentials)
            auth_user, auth_token = _authenticate_token(username, token)
        else:
            raise HttpError(
                400,
                "ValidationError",
                "Only basic or token HTTP authentication is supported.",
            )
    except ValueError as err:
        raise HttpError(
            400,
            "ValidationError",
            "Authorization header values are not properly formed. "
            "Supplied header %s. Got error: %s" % (header, err),
        ) from err

    if bump_login and auth_user.user_id:
        users.bump_user_login_time(auth_user)
        if auth_token is not None:
            user_tokens.bump_usage_time(auth_token)
        db.session.commit()
    return auth_user


def get_user(
    request: Request,
    bump_login: Annotated[
        Bool,
        Query(
            alias="bump-login",
            description="Record this request as a login of the authenticated user.",
        ),
    ] = False,
    _basic: Annotated[object, Depends(_basic_scheme)] = None,
    _token: Annotated[object, Depends(_token_scheme)] = None,
) -> model.User:
    """
    The user who sent the request: authenticated by the Authorization header
    (Basic, or Token with a login token), or the anonymous user without one.
    Wrong credentials are an error, not an anonymous request.
    """
    header = request.headers.get("Authorization")
    user = _authenticate(header, bump_login) if header else _anonymous_user()
    request.scope[LOG_USER_KEY] = user.name
    return user


CurrentUser = Annotated[model.User, Depends(get_user)]


def require(privilege: str) -> Callable[[model.User], model.User]:
    """
    Dependency factory: the endpoint needs this privilege. Gives the user
    who has it, or refuses the request before the endpoint runs.
    """

    def dependency(user: CurrentUser) -> model.User:
        auth.verify_privilege(user, privilege)
        return user

    return dependency
