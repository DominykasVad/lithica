import json
import re
import urllib.parse
from collections.abc import Callable
from datetime import datetime
from typing import Any

import python_multipart
from python_multipart.exceptions import FormParserError
from python_multipart.multipart import Field, File

from lithica import config, db
from lithica.func import util
from lithica.rest import context, errors, middleware, routes


def _json_serializer(obj: Any) -> str:
    """JSON serializer for objects not serializable by default JSON code"""
    if isinstance(obj, datetime):
        serial = obj.isoformat("T") + "Z"
        return serial
    raise TypeError("Type not serializable")


def _dump_json(obj: Any) -> str:
    return json.dumps(obj, default=_json_serializer, indent=2)


def _get_headers(env: dict[str, Any]) -> dict[str, str]:
    headers: dict[str, str] = {}
    for key, value in env.items():
        if key.startswith("HTTP_"):
            key = util.snake_case_to_upper_train_case(key[5:])
            headers[key] = value
    return headers


def _parse_multipart(env: dict[str, Any]) -> dict[str, bytes | str]:
    """
    Read a multipart/form-data body. Parts that carry a file name are
    returned as bytes, plain form fields as str.
    """
    parts: dict[str, bytes | str] = {}
    opened: list[File] = []

    def on_field(field: Field) -> None:
        if field.field_name is not None:
            value = field.value or b""
            parts[field.field_name.decode("utf-8")] = value.decode("utf-8")

    def on_file(file: File) -> None:
        # the parser still flushes the last file when it finishes, so the
        # files are closed only after parsing is over
        opened.append(file)
        if file.field_name is not None:
            file.file_object.seek(0)
            parts[file.field_name.decode("utf-8")] = file.file_object.read()

    headers = {"Content-Type": env["CONTENT_TYPE"].encode("latin-1")}
    if env.get("CONTENT_LENGTH"):
        headers["Content-Length"] = env["CONTENT_LENGTH"].encode("latin-1")
    try:
        python_multipart.parse_form(headers, env["wsgi.input"], on_field, on_file)
    except (FormParserError, UnicodeDecodeError) as ex:
        raise errors.HttpBadRequest(
            "ValidationError", "Could not decode the multipart request body."
        ) from ex
    finally:
        for file in opened:
            file.close()
    return parts


def _create_context(env: dict[str, Any]) -> context.Context:
    method = env["REQUEST_METHOD"]
    path = "/" + env["PATH_INFO"].lstrip("/")
    path = path.encode("latin-1").decode("utf-8")  # PEP-3333
    headers = _get_headers(env)

    files: dict[str, bytes] = {}
    params = dict(urllib.parse.parse_qsl(env.get("QUERY_STRING", "")))

    if "multipart" in env.get("CONTENT_TYPE", ""):
        parts = _parse_multipart(env)
        if not parts:
            raise errors.HttpBadRequest("ValidationError", "No files attached.")
        body = parts.get("metadata")
        # only parts sent as files are files; a plain form field is text
        files = {
            name: content
            for name, content in parts.items()
            if isinstance(content, bytes)
        }
    else:
        body = env["wsgi.input"].read()

    if body:
        try:
            if isinstance(body, bytes):
                body = body.decode("utf-8")

            for key, value in json.loads(body).items():
                params[key] = value
        except (ValueError, UnicodeDecodeError) as ex:
            raise errors.HttpBadRequest(
                "ValidationError",
                "Could not decode the request body. The JSON "
                "was incorrect or was not encoded as UTF-8.",
            ) from ex

    return context.Context(env, method, path, headers, params, files)


CORS_ALLOWED_METHODS = "GET, POST, PUT, DELETE, OPTIONS"
CORS_ALLOWED_HEADERS = "Authorization, Content-Type"


def _cors_headers(env: dict[str, Any]) -> list[tuple[str, str]]:
    """
    Return the CORS response headers for this request. Only origins listed in
    the cors_origins setting are answered; with the default empty list no
    header is sent and browsers allow same-origin requests only.
    """
    allowed_origins = config.config.get("cors_origins") or []
    if not allowed_origins:
        return []
    # the response differs by origin, so shared caches must key on it
    headers = [("Vary", "Origin")]
    origin = env.get("HTTP_ORIGIN")
    if origin is not None and origin in allowed_origins:
        headers.append(("Access-Control-Allow-Origin", origin))
    return headers


def _is_allowed_preflight(env: dict[str, Any]) -> bool:
    return (
        env.get("REQUEST_METHOD") == "OPTIONS"
        and "HTTP_ACCESS_CONTROL_REQUEST_METHOD" in env
        and env.get("HTTP_ORIGIN") in (config.config.get("cors_origins") or [])
    )


def application(
    env: dict[str, Any], start_response: Callable[[str, Any], Any]
) -> tuple[bytes]:
    cors_headers = _cors_headers(env)

    def start_response_with_cors(status: str, headers: Any) -> Any:
        return start_response(status, list(headers) + cors_headers)

    if _is_allowed_preflight(env):
        start_response_with_cors(
            "200 OK",
            [
                ("Access-Control-Allow-Methods", CORS_ALLOWED_METHODS),
                ("Access-Control-Allow-Headers", CORS_ALLOWED_HEADERS),
            ],
        )
        return (b"",)
    return _handle_request(env, start_response_with_cors)


def _handle_request(
    env: dict[str, Any], start_response: Callable[[str, Any], Any]
) -> tuple[bytes]:
    try:
        ctx = _create_context(env)
        if "application/json" not in ctx.get_header("Accept"):
            raise errors.HttpNotAcceptable(
                "ValidationError", "This API only supports JSON responses."
            )

        for url, allowed_methods in routes.routes.items():
            match = re.fullmatch(url, ctx.url)
            if match:
                if ctx.method not in allowed_methods:
                    raise errors.HttpMethodNotAllowed(
                        "ValidationError",
                        "Allowed methods: %r" % allowed_methods,
                    )
                handler = allowed_methods[ctx.method]
                break
        else:
            raise errors.HttpNotFound(
                "ValidationError",
                "Requested path " + ctx.url + " was not found.",
            )

        try:
            ctx.session = db.session()
            try:
                for hook in middleware.pre_hooks:
                    hook(ctx)
                try:
                    response = handler(
                        ctx,
                        {
                            k: urllib.parse.unquote(v)
                            for k, v in match.groupdict().items()
                        },
                    )
                except Exception:
                    ctx.session.rollback()
                    raise
                finally:
                    for hook in middleware.post_hooks:
                        hook(ctx)
            finally:
                db.session.remove()

            start_response("200 OK", [("content-type", "application/json")])
            return (_dump_json(response).encode("utf-8"),)

        except Exception as ex:
            for exception_type, ex_handler in errors.error_handlers.items():
                if isinstance(ex, exception_type):
                    ex_handler(ex)
            raise

    except errors.BaseHttpError as ex:
        start_response(
            "%d %s" % (ex.code, ex.reason),
            [("content-type", "application/json")],
        )
        blob = {
            "name": ex.name,
            "title": ex.title,
            "description": ex.description,
        }
        if ex.extra_fields is not None:
            for key, value in ex.extra_fields.items():
                blob[key] = value
        return (_dump_json(blob).encode("utf-8"),)
