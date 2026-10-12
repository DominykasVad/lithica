import pytest
from fastapi.testclient import TestClient

from lithica import app as lithica_app
from lithica import openapi


@pytest.fixture
def client():
    return TestClient(lithica_app.app, headers={"Accept": "application/json"})


@pytest.mark.parametrize("api_docs", [False, None, 0])
def test_documentation_is_off_unless_switched_on(client, config_injector, api_docs):
    config_injector({"api_docs": api_docs})
    for path in ["/docs", "/redoc", "/openapi.json"]:
        response = client.get(path)
        assert response.status_code == 404
        # exactly the answer for a path that does not exist
        assert response.json() == {
            "name": "ValidationError",
            "title": "Not Found",
            "description": "Requested path %s was not found." % path,
        }


def test_documentation_is_served_when_switched_on(client, config_injector):
    config_injector({"api_docs": True})
    served = client.get("/openapi.json")
    assert served.status_code == 200
    # a site serves the description of what it has: the contract, less the
    # routes of the modules that are not switched on here
    contract = openapi.build()
    assert served.json()["info"] == contract["info"]
    assert served.json()["paths"] == {
        path: operations
        for path, operations in contract["paths"].items()
        if not path.startswith("/modules/")
    }
    assert served.json()["tags"] == openapi.TAGS

    # no Accept: application/json needed, a browser opens these
    client.headers.pop("Accept")
    for path, marker in [("/docs", "swagger-ui"), ("/redoc", "redoc")]:
        page = client.get(path)
        assert page.status_code == 200
        assert page.headers["content-type"].startswith("text/html")
        assert marker in page.text
        # the document is loaded by a relative URL, so that the page works
        # under any base path
        assert "'openapi.json'" in page.text or '"openapi.json"' in page.text
        assert "/openapi.json" not in page.text
    # requests made from the page say that they accept JSON, as the API asks
    assert 'request.headers["Accept"] = "application/json"' in client.get("/docs").text


def test_api_docs_can_be_switched_on_by_the_environment(monkeypatch):
    from lithica import config

    monkeypatch.delenv("API_DOCS", raising=False)
    assert config._environment_overrides() == {}
    monkeypatch.setenv("API_DOCS", "1")
    assert config._environment_overrides() == {"api_docs": True}
    monkeypatch.setenv("API_DOCS", "0")
    assert config._environment_overrides() == {"api_docs": False}
    monkeypatch.setenv("API_DOCS", "")
    assert config._environment_overrides() == {}
