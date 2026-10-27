"""
What the endpoints depend on: who is asking, what they may do, and what
they sent.
"""

import base64
import dataclasses
import json
import os
import shutil
import tempfile
import urllib.parse
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Annotated, Any, cast

import python_multipart
from fastapi import Depends, Query, Request
from fastapi.security import APIKeyHeader
from fastapi.security.http import HTTPBase
from python_multipart.exceptions import FormParserError
from python_multipart.multipart import Field, File
from starlette.concurrency import run_in_threadpool
from starlette.requests import ClientDisconnect

from lithica import config, db, errors, model
from lithica.api.error_handlers import HttpError
from lithica.api.schemas import READ_AS_INT, Bool, RequestModel
from lithica.func import auth, file_uploads, net, serialization, user_tokens, users
from lithica.func import content as content_module
from lithica.func.content import Content, ContentLike
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
    # A token of a user who is gone (deleted, renamed) does not work either:
    # that is the client's session ending, not a page that is not found.
    user = users.try_get_user_by_name(username)
    user_token = (
        user_tokens.get_by_user_and_token(user, token) if user is not None else None
    )
    if user is None or user_token is None or not auth.is_valid_token(user_token):
        raise errors.InvalidTokenError("Invalid token.")
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


def fields_of(
    serializer: type[serialization.BaseSerializer],
) -> Callable[[list[str]], list[str]]:
    """
    The `fields` of an endpoint whose answer `serializer` writes, checked
    before the endpoint runs: a request is refused for a field the answer
    would not have before anything is created, changed or deleted, not after.
    """

    def checked_fields(
        fields: Annotated[list[str], Depends(get_fields)],
    ) -> list[str]:
        serializer.check_fields(fields)
        return fields

    return checked_fields


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
    offset: Annotated[
        int, Query(ge=0, description="How many results to skip."), READ_AS_INT
    ] = 0,
    limit: Annotated[
        int,
        Query(ge=1, le=100, description="How many results to return."),
        READ_AS_INT,
    ] = 100,
) -> Page:
    return Page(query, offset, limit)


PageParams = Annotated[Page, Depends(get_page)]


def search(
    executor: Executor,
    page: Page,
    # each executor yields entities of its own config's model
    serializer: Callable[[Any], Any],
    user: model.User | None = None,
) -> dict[str, Any]:
    """Run a search made by `user` and build the paged response."""
    count, entities = executor.execute(page.query, page.offset, page.limit, user)
    return {
        "query": page.query,
        "offset": page.offset,
        "limit": page.limit,
        "total": count,
        "results": [serializer(entity) for entity in entities],
    }


_MISSING = object()

# what the server accepts in one request when max_upload_size is not set
DEFAULT_MAX_UPLOAD_SIZE = 1024 * 1024 * 1024

# an uploaded file up to this size is kept in memory, a larger one on disk
MAX_MEMORY_FILE_SIZE = 1024 * 1024


class RequestData:
    """
    The parameters and uploaded files of one request.

    `params` is the query string overlaid with the JSON of the body, as the
    old framework merged them. In a multipart request the JSON is the
    `metadata` part and every part sent as a file is in `files`.

    A large file is not in memory: it is a `Content` in a temporary
    directory that belongs to the request and is removed by `close()`, as
    is every file downloaded for it. (A file that was stored in the
    meantime was renamed out of there and stays.)
    """

    def __init__(
        self,
        params: dict[str, Any],
        files: dict[str, ContentLike],
        upload_dir: str | None = None,
    ) -> None:
        self.params = params
        self.files = files
        self._upload_dir = upload_dir
        self._downloads: list[Content] = []

    def close(self) -> None:
        for download in self._downloads:
            download.delete()
        if self._upload_dir is not None:
            shutil.rmtree(self._upload_dir, ignore_errors=True)

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
    ) -> ContentLike:
        """
        The content of a file the request refers to: uploaded as a part,
        named by URL (`<name>Url`, downloaded here) or uploaded earlier
        (`<name>Token`).
        """
        if name in self.files and self.files[name]:
            return self.files[name]

        if name + "Url" in self.params:
            download = net.download(
                self.params[name + "Url"],
                use_video_downloader=use_video_downloader,
            )
            if isinstance(download, Content):
                self._downloads.append(download)
            return download

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


def max_upload_size() -> int:
    """The largest request body the server takes, in bytes (GET /info says it)."""
    return config.config.get("max_upload_size") or DEFAULT_MAX_UPLOAD_SIZE


async def _body(request: Request) -> AsyncIterator[bytes]:
    """
    The request body, in pieces of about a megabyte, refused once it is
    larger than the max_upload_size setting.
    """
    limit = max_upload_size()
    too_large = HttpError(
        413,
        "RequestTooLargeError",
        "The request is larger than the maximum of %d bytes." % limit,
        title="Payload Too Large",
    )
    declared = request.headers.get("Content-Length", "")
    if declared.isdigit() and int(declared) > limit:
        raise too_large
    received = 0
    pieces: list[bytes] = []
    gathered = 0
    try:
        async for chunk in request.stream():
            received += len(chunk)
            if received > limit:
                raise too_large
            pieces.append(chunk)
            gathered += len(chunk)
            if gathered >= MAX_MEMORY_FILE_SIZE:
                yield b"".join(pieces)
                pieces, gathered = [], 0
    except ClientDisconnect:
        # The client went away in the middle of its request (a browser does
        # that when the page is left). Nobody is there to read an answer;
        # this ends the request as a refused one instead of a server error.
        raise HttpError(
            400, "ValidationError", "The request ended before it was complete."
        ) from None
    if pieces:
        yield b"".join(pieces)


async def _read_multipart(
    request: Request, upload_dir: str
) -> tuple[bytes | str | None, dict[str, ContentLike]]:
    """
    Read a multipart/form-data body. Parts that carry a file name are files;
    the large ones are written to `upload_dir` as they arrive. Plain form
    fields are text.
    """
    files: dict[str, ContentLike] = {}
    fields: dict[str, str] = {}
    opened: list[File] = []

    def on_field(field: Field) -> None:
        if field.field_name is not None:
            value = field.value or b""
            fields[field.field_name.decode("utf-8")] = value.decode("utf-8")

    def on_file(file: File) -> None:
        # the parser still flushes the last file when it finishes, so the
        # files are closed only after parsing is over
        opened.append(file)
        if file.field_name is None:
            return
        name = file.field_name.decode("utf-8")
        if file.in_memory:
            file.file_object.seek(0)
            files[name] = file.file_object.read()
        else:
            assert file.actual_file_name is not None
            file.file_object.flush()
            # it exists to be stored: saving it may rename it into place
            files[name] = Content(os.fsdecode(file.actual_file_name), movable=True)

    headers = {
        "Content-Type": request.headers.get("Content-Type", "").encode("latin-1")
    }
    try:
        parser = python_multipart.create_form_parser(
            headers,
            on_field,
            on_file,
            config={
                "UPLOAD_DIR": upload_dir,
                "UPLOAD_DELETE_TMP": False,
                "MAX_MEMORY_FILE_SIZE": MAX_MEMORY_FILE_SIZE,
            },
        )
        async for piece in _body(request):
            # writes to disk: off the event loop
            await run_in_threadpool(parser.write, piece)
        await run_in_threadpool(parser.finalize)
    except (FormParserError, ValueError, UnicodeDecodeError) as ex:
        raise HttpError(
            400, "ValidationError", "Could not decode the multipart request body."
        ) from ex
    finally:
        for file in opened:
            file.close()
    if not files and not fields:
        raise HttpError(400, "ValidationError", "No files attached.")
    # browsers send the JSON part as a Blob, which arrives as a file
    metadata = files.get("metadata", fields.get("metadata"))
    if isinstance(metadata, Content):
        metadata = metadata.read()
    return metadata, files


async def _read_request(request: Request, upload_dir: str | None) -> RequestData:
    params: dict[str, Any] = dict(urllib.parse.parse_qsl(request.url.query))
    files: dict[str, ContentLike] = {}
    body: bytes | str | None
    if upload_dir is not None:
        body, files = await _read_multipart(request, upload_dir)
    else:
        body = b"".join([piece async for piece in _body(request)])

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
    return RequestData(params, files, upload_dir)


def _make_upload_dir() -> str:
    return tempfile.mkdtemp(prefix="upload-", dir=content_module.temporary_dir())


# async because it awaits the request body; the disk work is on the pool
async def read_request(request: Request) -> AsyncIterator[RequestData]:
    """
    The request's parameters and files. What it stored on disk is removed
    when the request is over, whatever became of it.
    """
    upload_dir = None
    if "multipart" in request.headers.get("Content-Type", ""):
        # the uploads of one request go to a directory of their own, so
        # that all of them, finished or not, can be removed together
        upload_dir = await run_in_threadpool(_make_upload_dir)
    data = None
    try:
        data = await _read_request(request, upload_dir)
        yield data
    finally:
        if data is not None:
            await run_in_threadpool(data.close)
        elif upload_dir is not None:
            await run_in_threadpool(shutil.rmtree, upload_dir, True)


RequestDataParam = Annotated[RequestData, Depends(read_request)]


def read_body[M: RequestModel](
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
