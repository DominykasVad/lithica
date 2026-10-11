"""Helpers for tests that call the API over HTTP (the `client` fixture)."""

from typing import Any

import httpx2
import pydantic

from lithica.api.error_handlers import ERROR_KINDS


def ok(response: httpx2.Response) -> Any:
    """The body of a successful response."""
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/json"
    return response.json()


def assert_error(
    response: httpx2.Response,
    error_class: type[Exception],
    description: str | None = None,
) -> dict[str, Any]:
    """
    Assert that the request was refused with this business error: its name,
    and the status and title of its kind. Returns the error body.
    """
    body = response.json()
    assert body["name"] == error_class.__name__, response.text
    for kind, status_code, title in ERROR_KINDS:
        if issubclass(error_class, kind):
            assert response.status_code == status_code, response.text
            assert body["title"] == title
            break
    else:
        raise AssertionError("%r is not a business error" % error_class)
    if description is not None:
        assert body["description"] == description
    return body


def assert_fits(
    model: type[pydantic.BaseModel], body: Any, complete: bool = True
) -> None:
    """
    Assert that a response body is what its response model describes: every
    field of a known name and the documented type. A body that leaves fields
    out on purpose (`fields=`, or a field shown only to some users) is
    checked with `complete=False`.
    """
    try:
        model.model_validate(body)
    except pydantic.ValidationError as ex:
        problems = [
            error for error in ex.errors() if complete or error["type"] != "missing"
        ]
        assert not problems, problems
