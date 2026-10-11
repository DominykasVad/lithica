import pytest
from fastapi.testclient import TestClient

from lithica import app as lithica_app


@pytest.fixture
def client():
    # not used as a context manager: the lifespan (startup work) does not run
    return TestClient(lithica_app.app, headers={"Accept": "application/json"})


def test_importing_the_app_does_not_start_it():
    # the startup work belongs to the lifespan; a second application object
    # can be built without it running
    assert lithica_app.create_app() is not lithica_app.app


@pytest.mark.parametrize("path", ["/no-such-path", "/no-such-path/", "/a/b/c"])
def test_unknown_path_is_answered_by_the_old_application(client, path):
    response = client.get(path)
    assert response.status_code == 404
    assert response.headers["content-type"] == "application/json"
    assert response.json() == {
        "name": "ValidationError",
        "title": "Not Found",
        "description": "Requested path %s was not found." % path,
    }


def test_old_application_still_checks_the_accept_header(client):
    response = client.get("/info", headers={"Accept": "text/html"})
    assert response.status_code == 406
    assert response.json()["name"] == "ValidationError"


def test_old_application_still_refuses_unknown_methods(client):
    response = client.request("PATCH", "/info")
    assert response.status_code == 405
    assert response.json()["title"] == "Method Not Allowed"


def test_no_redirect_for_a_trailing_slash(client):
    response = client.get("/info/", headers={"Accept": "text/html"})
    # answered (here: refused) by the route itself, not redirected to /info
    assert response.status_code == 406


def test_documentation_is_not_served(client):
    for path in ["/docs", "/redoc", "/openapi.json"]:
        assert client.get(path).status_code == 404
