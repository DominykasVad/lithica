"""
What the endpoints depend on: who is asking, what they may do, and what
they sent.
"""

import base64
import dataclasses
import json
import urllib.parse
from collections.abc import Awaitable, Callable
from typing import Annotated, Any, cast

from fastapi import Depends, Query, Request
from fastapi.security import APIKeyHeader
from fastapi.security.http import HTTPBase
from starlette.exceptions import HTTPException

from lithica import db, errors, model
from lithica.api.error_handlers import HttpError
from lithica.api.schemas import Bool, Int, RequestModel
from lithica.func import auth, file_uploads, net, user_tokens, users
from lithica.search.executor import Executor

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


def require_json_accept(request: Request) -> None:
    """The API speaks JSON only, and a request has to say it accepts it."""
    if "application/json" not in request.headers.get("Accept", ""):
        raise HttpError(
            406, "ValidationError", "This API only supports JSON responses."
        )


def get_fields(
    fields: Annotated[
        str | None,
        Query(
            description="Comma-separated names of the fields to return. "
            "All fields are returned when it is absent."
        ),
    ] = None,
) -> list[str]:
    if not fields:
        return []
    return fields.split(",") if "," in fields else [fields]


Fields = Annotated[list[str], Depends(get_fields)]


@dataclasses.dataclass(frozen=True)
class Page:
    """Which part of a search result the request asks for."""

    query: str
    offset: int
    limit: int


def get_page(
    query: Annotated[
        str, Query(description="Search query; see the search syntax.")
    ] = "",
    offset: Annotated[Int, Query(ge=0, description="How many results to skip.")] = 0,
    limit: Annotated[
        Int, Query(ge=1, le=100, description="How many results to return.")
    ] = 100,
) -> Page:
    return Page(query, offset, limit)


PageParams = Annotated[Page, Depends(get_page)]


def search(
    executor: Executor,
    page: Page,
    # each executor yields entities of its own config's model
    serializer: Callable[[Any], Any],
) -> dict[str, Any]:
    """Run a search and build the paged response."""
    count, entities = executor.execute(page.query, page.offset, page.limit)
    return {
        "query": page.query,
        "offset": page.offset,
        "limit": page.limit,
        "total": count,
        "results": [serializer(entity) for entity in entities],
    }


_MISSING = object()


class RequestData:
    """
    The parameters and uploaded files of one request.

    `params` is the query string overlaid with the JSON of the body, as the
    old framework merged them. In a multipart request the JSON is the
    `metadata` part and every part sent as a file is in `files`.
    """

    def __init__(self, params: dict[str, Any], files: dict[str, bytes]) -> None:
        self.params = params
        self.files = files

    def has_file(self, name: str, allow_tokens: bool = True) -> bool:
        return (
            name in self.files
            or name + "Url" in self.params
            or (allow_tokens and name + "Token" in self.params)
        )

    def get_file(
        self,
        name: str,
        default: object | bytes = _MISSING,
        use_video_downloader: bool = False,
        allow_tokens: bool = True,
    ) -> bytes:
        """
        The content of a file the request refers to: uploaded as a part,
        named by URL (`<name>Url`, downloaded here) or uploaded earlier
        (`<name>Token`).
        """
        if name in self.files and self.files[name]:
            return self.files[name]

        if name + "Url" in self.params:
            return net.download(
                self.params[name + "Url"],
                use_video_downloader=use_video_downloader,
            )

        if allow_tokens and name + "Token" in self.params:
            ret = file_uploads.get(self.params[name + "Token"])
            if ret:
                return ret
            elif default is not _MISSING:
                raise errors.MissingOrExpiredRequiredFileError(
                    "Required file %r is missing or has expired." % name
                )

        if default is not _MISSING:
            return cast(bytes, default)
        raise errors.MissingRequiredFileError("Required file %r is missing." % name)


# a JSON part larger than this is refused; uploads are not limited here
MAX_FORM_FIELD_SIZE = 1024 * 1024


async def _read_multipart(request: Request) -> tuple[bytes | str | None, dict]:
    files: dict[str, bytes] = {}
    fields: dict[str, str] = {}
    try:
        async with request.form(max_part_size=MAX_FORM_FIELD_SIZE) as form:
            for name, value in form.multi_items():
                if isinstance(value, str):
                    fields[name] = value
                else:
                    files[name] = await value.read()
    except HTTPException as ex:
        raise HttpError(
            400, "ValidationError", "Could not decode the multipart request body."
        ) from ex
    if not files and not fields:
        raise HttpError(400, "ValidationError", "No files attached.")
    # browsers send the JSON part as a Blob, which arrives as a file
    metadata = files.get("metadata", fields.get("metadata"))
    return metadata, files


# async because it awaits the request body; it does no blocking work itself
async def read_request(request: Request) -> RequestData:
    params: dict[str, Any] = dict(urllib.parse.parse_qsl(request.url.query))
    files: dict[str, bytes] = {}
    body: bytes | str | None
    if "multipart" in request.headers.get("Content-Type", ""):
        body, files = await _read_multipart(request)
    else:
        body = await request.body()

    if body:
        try:
            if isinstance(body, bytes):
                body = body.decode("utf-8")
            content = json.loads(body)
            if not isinstance(content, dict):
                raise ValueError("the JSON must be an object")
        except (ValueError, UnicodeDecodeError) as ex:
            raise HttpError(
                400,
                "ValidationError",
                "Could not decode the request body. The JSON "
                "was incorrect or was not encoded as UTF-8.",
            ) from ex
        params.update(content)
    return RequestData(params, files)


RequestDataParam = Annotated[RequestData, Depends(read_request)]


def body[M: RequestModel](
    model: type[M],
) -> Callable[[RequestData], Awaitable[M]]:
    """
    Dependency factory: the request's parameters as `model`. Describe the
    body in the OpenAPI document with `schemas.request_body(model)`.
    """

    # async only to stay off the thread pool: validation is quick, pure CPU
    async def dependency(data: RequestDataParam) -> M:
        return model.from_params(data.params)

    return dependency
