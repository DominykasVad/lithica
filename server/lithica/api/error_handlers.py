"""
Turns exceptions into the API's error responses.

Every error has the same body: `name` (for programs: the exception class),
`title` and `description` (for people), plus any extra fields the exception
carries. Which status and title an error gets is decided here by the kind of
business error it is.
"""

from collections.abc import Mapping, Sequence
from http import HTTPStatus
from typing import Any, LiteralString

import sqlalchemy.orm as sa_orm
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException
from starlette.routing import BaseRoute, Match

from lithica import errors
from lithica.api.responses import JsonResponse

# kind of business error -> (status, title); a subclass is its parent's kind
ERROR_KINDS: list[tuple[type[errors.BaseError], int, str]] = [
    (errors.AuthError, 403, "Authentication error"),
    (errors.ValidationError, 400, "Validation error"),
    (errors.SearchError, 400, "Search error"),
    (errors.IntegrityError, 409, "Integrity violation"),
    (errors.NotFoundError, 404, "Not found"),
    (errors.ProcessingError, 400, "Processing error"),
    (errors.ThirdPartyError, 500, "Server configuration error"),
]


# the type of the pydantic errors that lithica.api.schemas raises; their
# message completes the sentence "Parameter 'x' ..."
PARAMETER_ERROR: LiteralString = "lithica_parameter"


class HttpError(Exception):
    """An error of the HTTP layer itself rather than of a business rule."""

    def __init__(
        self,
        status_code: int,
        name: str,
        description: str,
        title: str | None = None,
    ) -> None:
        super().__init__(description)
        self.status_code = status_code
        self.name = name
        self.description = description
        self.title = title or HTTPStatus(status_code).phrase


def error_response(
    status_code: int,
    name: str,
    title: str,
    description: str,
    extra_fields: dict[str, Any] | None = None,
) -> JsonResponse:
    body: dict[str, Any] = {"name": name, "title": title, "description": description}
    if extra_fields is not None:
        body.update(extra_fields)
    return JsonResponse(body, status_code=status_code)


def parameter_error(details: Sequence[Any]) -> errors.ValidationError:
    """
    Turn pydantic's report about a request into the API's own error. Only
    the first problem is reported, as before: the old framework stopped at
    the first parameter it could not read.
    """
    detail = details[0]
    names = [part for part in detail["loc"] if isinstance(part, str)]
    name = names[-1] if names else "?"
    kind = detail["type"]
    context = detail.get("ctx") or {}
    if kind == "missing":
        return errors.MissingRequiredParameterError(
            "Required parameter %r is missing." % name
        )
    if kind == PARAMETER_ERROR:
        problem = detail["msg"]
    elif kind in ("int_parsing", "int_type", "int_from_float"):
        problem = "must be an integer value"
    elif kind == "greater_than_equal":
        problem = "must be at least %r" % context.get("ge")
    elif kind == "less_than_equal":
        problem = "may not exceed %r" % context.get("le")
    else:
        problem = "is not valid (%s)" % detail["msg"]
    return errors.InvalidParameterError("Parameter %r %s." % (name, problem))


async def _on_business_error(_request: Request, ex: Exception) -> JsonResponse:
    for kind, status_code, title in ERROR_KINDS:
        if isinstance(ex, kind):
            return error_response(
                status_code,
                type(ex).__name__,
                title,
                str(ex),
                getattr(ex, "extra_fields", None),
            )
    raise ex


async def _on_stale_data_error(_request: Request, _ex: Exception) -> JsonResponse:
    return error_response(
        409,
        "IntegrityError",
        "Integrity violation",
        "Someone else modified this in the meantime. Please try again.",
    )


async def _on_http_error(_request: Request, ex: Exception) -> JsonResponse:
    assert isinstance(ex, HttpError)
    return error_response(ex.status_code, ex.name, ex.title, ex.description)


async def _on_request_validation_error(request: Request, ex: Exception) -> JsonResponse:
    assert isinstance(ex, RequestValidationError)
    return await _on_business_error(request, parameter_error(ex.errors()))


async def _on_routing_error(request: Request, ex: Exception) -> JsonResponse:
    """Errors raised by the router itself: no such path, no such method."""
    assert isinstance(ex, HTTPException)
    title = HTTPStatus(ex.status_code).phrase
    if ex.status_code == 404:
        description = "Requested path %s was not found." % request.url.path
    elif ex.status_code == 405:
        allowed = _allowed_methods(request) or _listed_in(ex.headers)
        description = "Allowed methods: %r" % allowed
    else:
        description = str(ex.detail)
    response = error_response(ex.status_code, "ValidationError", title, description)
    if ex.headers:
        response.headers.update(ex.headers)
    if ex.status_code == 405:
        response.headers["Allow"] = ", ".join(allowed)
    return response


def _listed_in(headers: Mapping[str, str] | None) -> list[str]:
    """The methods of an Allow header, as the router set it."""
    allow = (headers or {}).get("Allow", "")
    return sorted(method.strip() for method in allow.split(",") if method.strip())


def _allowed_methods(request: Request) -> list[str]:
    """
    The methods the requested path does answer to. The router reports those
    of one route only, and each method of a path is a route of its own.
    """
    methods: set[str] = set()

    def collect(routes: Sequence[BaseRoute]) -> None:
        for route in routes:
            # a router added with include_router() is kept as one entry
            # that holds the router
            included = getattr(route, "original_router", None)
            if included is not None:
                collect(included.routes)
                continue
            match, _child_scope = route.matches(request.scope)
            if match != Match.NONE:
                methods.update(getattr(route, "methods", None) or [])

    collect(request.app.routes)
    return sorted(methods)


def install(app: FastAPI) -> None:
    for kind, _status_code, _title in ERROR_KINDS:
        app.add_exception_handler(kind, _on_business_error)
    app.add_exception_handler(sa_orm.exc.StaleDataError, _on_stale_data_error)
    app.add_exception_handler(HttpError, _on_http_error)
    app.add_exception_handler(RequestValidationError, _on_request_validation_error)
    app.add_exception_handler(HTTPException, _on_routing_error)
