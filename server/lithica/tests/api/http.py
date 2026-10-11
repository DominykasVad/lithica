"""Helpers for tests that call the API over HTTP (the `api` fixture)."""

from typing import Any

import httpx2

from lithica.api.error_handlers import ERROR_KINDS


def result(response: httpx2.Response) -> Any:
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
