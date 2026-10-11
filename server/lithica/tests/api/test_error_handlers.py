from typing import Annotated, Any

import pytest
import sqlalchemy.orm as sa_orm
from fastapi import FastAPI, Query
from fastapi.testclient import TestClient

from lithica import errors
from lithica.api import error_handlers
from lithica.func import tags


class _ErrorWithFields(errors.ValidationError):
    pass


def _client(raised: Exception | None = None) -> TestClient:
    app = FastAPI()
    error_handlers.install(app)

    @app.get("/raise")
    def raise_error() -> None:
        assert raised is not None
        raise raised

    @app.get("/typed")
    def typed(
        number: Annotated[int, Query(ge=1, le=100)],
        other: Annotated[int, Query()] = 0,
    ) -> dict[str, Any]:
        return {"number": number}

    return TestClient(app, raise_server_exceptions=False)


@pytest.mark.parametrize(
    "error,status_code,name,title",
    [
        (errors.AuthError("x"), 403, "AuthError", "Authentication error"),
        (errors.ValidationError("x"), 400, "ValidationError", "Validation error"),
        (errors.SearchError("x"), 400, "SearchError", "Search error"),
        (errors.IntegrityError("x"), 409, "IntegrityError", "Integrity violation"),
        (errors.NotFoundError("x"), 404, "NotFoundError", "Not found"),
        (errors.ProcessingError("x"), 400, "ProcessingError", "Processing error"),
        (
            errors.ThirdPartyError("x"),
            500,
            "ThirdPartyError",
            "Server configuration error",
        ),
        # a subclass is reported under its own name, with its parent's status
        (tags.TagNotFoundError("x"), 404, "TagNotFoundError", "Not found"),
        (tags.TagIsInUseError("x"), 400, "TagIsInUseError", "Validation error"),
        (
            errors.MissingRequiredParameterError("x"),
            400,
            "MissingRequiredParameterError",
            "Validation error",
        ),
    ],
)
def test_business_errors(error, status_code, name, title):
    response = _client(error).get("/raise")
    assert response.status_code == status_code
    assert response.headers["content-type"] == "application/json"
    assert response.json() == {"name": name, "title": title, "description": "x"}


def test_extra_fields_are_added_to_the_body():
    error = _ErrorWithFields(
        "Post already uploaded", extra_fields={"otherPostId": 5, "otherPostUrl": "u"}
    )
    response = _client(error).get("/raise")
    assert response.status_code == 400
    assert response.json() == {
        "name": "_ErrorWithFields",
        "title": "Validation error",
        "description": "Post already uploaded",
        "otherPostId": 5,
        "otherPostUrl": "u",
    }


def test_stale_data_is_reported_as_an_integrity_error():
    response = _client(sa_orm.exc.StaleDataError("UPDATE matched 0 rows")).get("/raise")
    assert response.status_code == 409
    assert response.json() == {
        "name": "IntegrityError",
        "title": "Integrity violation",
        "description": "Someone else modified this in the meantime. Please try again.",
    }


def test_http_layer_error():
    error = error_handlers.HttpError(406, "ValidationError", "Only JSON.")
    response = _client(error).get("/raise")
    assert response.status_code == 406
    assert response.json() == {
        "name": "ValidationError",
        "title": "Not Acceptable",
        "description": "Only JSON.",
    }


def test_unknown_error_is_a_plain_500():
    response = _client(ZeroDivisionError("secret detail")).get("/raise")
    assert response.status_code == 500
    assert "secret detail" not in response.text


def test_unknown_path():
    response = _client().get("/no/such/path")
    assert response.status_code == 404
    assert response.json() == {
        "name": "ValidationError",
        "title": "Not Found",
        "description": "Requested path /no/such/path was not found.",
    }


def test_unknown_method():
    response = _client().post("/typed")
    assert response.status_code == 405
    assert response.json() == {
        "name": "ValidationError",
        "title": "Method Not Allowed",
        "description": "Allowed methods: ['GET']",
    }


@pytest.mark.parametrize(
    "query,name,description",
    [
        (
            "",
            "MissingRequiredParameterError",
            "Required parameter 'number' is missing.",
        ),
        (
            "?number=abc",
            "InvalidParameterError",
            "Parameter 'number' must be an integer value.",
        ),
        (
            "?number=0",
            "InvalidParameterError",
            "Parameter 'number' must be at least 1.",
        ),
        (
            "?number=101",
            "InvalidParameterError",
            "Parameter 'number' may not exceed 100.",
        ),
        (
            # only the first problem is reported
            "?number=abc&other=def",
            "InvalidParameterError",
            "Parameter 'number' must be an integer value.",
        ),
    ],
)
def test_invalid_parameters(query, name, description):
    response = _client().get("/typed" + query)
    assert response.status_code == 400
    assert response.json() == {
        "name": name,
        "title": "Validation error",
        "description": description,
    }


def test_timestamps_and_indentation_of_the_old_framework():
    from datetime import datetime

    from lithica.api.responses import JsonResponse

    response = JsonResponse({"time": datetime(1997, 1, 2, 3, 4, 5), "list": [1]})
    assert response.body == (
        b'{\n  "time": "1997-01-02T03:04:05Z",\n  "list": [\n    1\n  ]\n}'
    )
    assert response.headers["content-type"] == "application/json"


def test_unknown_method_lists_every_method_of_the_path():
    from fastapi import APIRouter

    app = FastAPI()
    error_handlers.install(app)
    router = APIRouter()

    @router.get("/thing/{name}")
    def get_thing(name: str) -> None:
        pass

    @router.put("/thing/{name}")
    def put_thing(name: str) -> None:
        pass

    @router.delete("/other")
    def delete_other() -> None:
        pass

    app.include_router(router)

    @app.post("/thing/{name}")
    def post_thing(name: str) -> None:
        pass

    response = TestClient(app).patch("/thing/x")
    assert response.status_code == 405
    assert response.json()["description"] == "Allowed methods: ['GET', 'POST', 'PUT']"
    assert response.headers["allow"] == "GET, POST, PUT"
