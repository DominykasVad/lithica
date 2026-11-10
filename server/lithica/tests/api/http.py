"""Helpers for tests that call the API over HTTP (the `client` fixture)."""

from typing import Any

import httpx2
import pydantic
import yaml

from lithica.api.error_handlers import ERROR_KINDS


def ok(response: httpx2.Response) -> Any:
    """The body of a successful response."""
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/json"
    return response.json()


def _names_of(error_class: type[Exception]) -> set[str]:
    """The class and its subclasses: an error is also an error of its parents."""
    names = {error_class.__name__}
    for subclass in error_class.__subclasses__():
        names |= _names_of(subclass)
    return names


def assert_error(
    response: httpx2.Response,
    error_class: type[Exception],
    description: str | None = None,
) -> dict[str, Any]:
    """
    Assert that the request was refused with this business error (or one
    derived from it, as `pytest.raises` would accept): its name, and the
    status and title of its kind. Returns the error body.
    """
    body = response.json()
    assert body["name"] in _names_of(error_class), response.text
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


def shipped_config(data_dir: str, **overrides: Any) -> dict[str, Any]:
    """
    A site with the settings and privileges of config.yaml.dist, as shipped,
    and what a test site needs on top (a data directory, a secret).
    """
    with open("config.yaml.dist") as handle:
        defaults = yaml.safe_load(handle)
    return (
        defaults
        | {
            "visibility": "open",
            "data_dir": data_dir,
            "data_url": "http://example.com/data/",
            "secret": "test",
            "allow_broken_uploads": False,
            "delete_source_files": True,
            "thumbnails": {
                "post_width": 300,
                "post_height": 300,
                "avatar_width": 30,
                "avatar_height": 30,
            },
            "convert": {"gif": {"to_mp4": False, "to_webm": False}},
            "tag_name_regex": r"^\S+$",
            "user_name_regex": r"^\S+$",
            "password_regex": r"^.{5,}$",
            "webhooks": [],
        }
        | overrides
    )


def enabled_config(overrides: dict[str, Any]) -> dict[str, Any]:
    """A complete behavior-test site, with optional features enabled.

    Any: YAML configuration contains heterogeneous values. Overrides replace
    whole entries (including privileges), as config_injector always did.
    """
    from lithica.func import site_settings

    values: dict[str, Any] = {
        "features": dict.fromkeys(site_settings.FEATURES, True)
    } | overrides
    data_dir = values.pop("data_dir", "")
    return shipped_config(data_dir, **values)
