import pytest
from fastapi.testclient import TestClient

from lithica import app as lithica_app


@pytest.fixture
def client():
    return TestClient(lithica_app.app, headers={"Accept": "application/json"})


def _get(client, origin=None):
    headers = {} if origin is None else {"Origin": origin}
    return client.get("/no-such-path", headers=headers)


def _preflight(client, origin):
    client.headers.pop("Accept")
    return client.options(
        "/no-such-path",
        headers={"Origin": origin, "Access-Control-Request-Method": "POST"},
    )


@pytest.mark.parametrize("cors_origins", [[], None])
def test_no_cors_headers_by_default(client, config_injector, cors_origins):
    config_injector({"cors_origins": cors_origins})
    response = _get(client, "https://other.example.com")
    assert response.status_code == 404
    assert "Access-Control-Allow-Origin" not in response.headers
    assert "Vary" not in response.headers


def test_no_cors_headers_without_the_setting(client, config_injector):
    config_injector({})
    response = _get(client, "https://other.example.com")
    assert "Access-Control-Allow-Origin" not in response.headers


def test_preflight_is_not_answered_by_default(client, config_injector):
    config_injector({"cors_origins": []})
    response = _preflight(client, "https://other.example.com")
    assert response.status_code != 200
    assert "Access-Control-Allow-Origin" not in response.headers
    assert "Access-Control-Allow-Methods" not in response.headers


def test_cors_headers_for_listed_origin(client, config_injector):
    config_injector(
        {"cors_origins": ["https://app.example.com", "https://b.example.com"]}
    )
    response = _get(client, "https://b.example.com")
    # the headers are sent on error responses too, or the client could not
    # read the error
    assert response.status_code == 404
    assert response.headers["Access-Control-Allow-Origin"] == "https://b.example.com"
    assert response.headers["Vary"] == "Origin"
    assert response.headers["content-type"] == "application/json"


@pytest.mark.parametrize(
    "origin",
    [
        "https://evil.example.com",
        "http://app.example.com",
        "https://app.example.com.evil.example.com",
        "https://app.example.com:8443",
        "null",
        "*",
    ],
)
def test_no_cors_headers_for_unlisted_origin(client, config_injector, origin):
    config_injector({"cors_origins": ["https://app.example.com"]})
    response = _get(client, origin)
    assert "Access-Control-Allow-Origin" not in response.headers
    assert response.headers["Vary"] == "Origin"


def test_no_allow_origin_without_origin_header(client, config_injector):
    config_injector({"cors_origins": ["https://app.example.com"]})
    response = _get(client)
    assert "Access-Control-Allow-Origin" not in response.headers


def test_preflight_for_listed_origin(client, config_injector):
    config_injector({"cors_origins": ["https://app.example.com"]})
    response = _preflight(client, "https://app.example.com")
    assert response.status_code == 200
    assert response.content == b""
    assert response.headers["Access-Control-Allow-Origin"] == "https://app.example.com"
    assert response.headers["Access-Control-Allow-Methods"] == (
        "GET, POST, PUT, DELETE, OPTIONS"
    )
    assert response.headers["Access-Control-Allow-Headers"] == (
        "Authorization, Content-Type"
    )


def test_preflight_for_unlisted_origin(client, config_injector):
    config_injector({"cors_origins": ["https://app.example.com"]})
    response = _preflight(client, "https://evil.example.com")
    assert response.status_code != 200
    assert "Access-Control-Allow-Origin" not in response.headers
    assert "Access-Control-Allow-Methods" not in response.headers


def test_each_header_is_sent_once(client, config_injector):
    config_injector({"cors_origins": ["https://app.example.com"]})
    response = _get(client, "https://app.example.com")
    assert response.headers.get_list("Access-Control-Allow-Origin") == [
        "https://app.example.com"
    ]
    assert response.headers.get_list("Vary") == ["Origin"]
