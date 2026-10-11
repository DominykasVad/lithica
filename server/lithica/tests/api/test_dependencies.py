import base64
import functools
import logging
from datetime import datetime
from typing import Annotated, Any
from unittest.mock import patch

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from lithica import db, model
from lithica.api import dependencies, error_handlers
from lithica.api.dependencies import CurrentUser, require
from lithica.app import SessionScopeMiddleware
from lithica.func import auth, user_tokens, users


def _header(scheme: str, user_name: str, secret: str) -> dict[str, str]:
    credentials = base64.b64encode(("%s:%s" % (user_name, secret)).encode()).decode()
    return {"Authorization": "%s %s" % (scheme, credentials)}


@functools.cache
def _password_hash(password: str) -> str:
    # argon2 is slow on purpose; hash each test password once per run
    with patch.dict("lithica.config.config", {"secret": "test"}):
        return auth.get_password_hash("salt", password)[0]


@pytest.fixture
def client(config_injector):
    config_injector(
        {
            "secret": "test",
            "privileges": {
                "tags:list": model.User.RANK_REGULAR,
                "tags:delete": model.User.RANK_ADMINISTRATOR,
            },
        }
    )
    app = FastAPI()
    error_handlers.install(app)

    @app.get("/whoami")
    def whoami(user: CurrentUser) -> dict[str, Any]:
        return {"name": user.name, "rank": user.rank, "id": user.user_id}

    @app.get("/tags")
    def list_tags(
        user: Annotated[model.User, Depends(require("tags:list"))],
    ) -> dict[str, Any]:
        return {"name": user.name}

    @app.delete("/tags")
    def delete_tags(
        user: Annotated[model.User, Depends(require("tags:delete"))],
    ) -> dict[str, Any]:
        return {"name": user.name}

    return TestClient(app)


@pytest.fixture
def user(user_factory):
    user = user_factory(name="u1", rank=model.User.RANK_REGULAR)
    user.password_salt = "salt"
    user.password_hash = _password_hash("password")
    user.password_revision = 3
    db.session.add(user)
    db.session.flush()
    return user


@pytest.fixture
def token(user, user_token_factory):
    user_token = user_token_factory(user=user, token="the-token")
    db.session.add(user_token)
    db.session.flush()
    return user_token


def test_no_header_is_the_anonymous_user(client):
    response = client.get("/whoami")
    assert response.status_code == 200
    assert response.json() == {"name": None, "rank": "anonymous", "id": None}


def test_basic_auth(client, user):
    response = client.get("/whoami", headers=_header("Basic", "u1", "password"))
    assert response.status_code == 200
    assert response.json() == {"name": "u1", "rank": "regular", "id": user.user_id}


@pytest.mark.parametrize("scheme", ["Basic", "basic", "BASIC"])
def test_scheme_name_is_case_insensitive(client, user, scheme):
    response = client.get("/whoami", headers=_header(scheme, "u1", "password"))
    assert response.json()["name"] == "u1"


def test_basic_auth_with_wrong_password(client, user):
    response = client.get("/whoami", headers=_header("Basic", "u1", "wrong"))
    assert response.status_code == 403
    assert response.json() == {
        "name": "AuthError",
        "title": "Authentication error",
        "description": "Invalid password.",
    }


def test_basic_auth_with_unknown_user(client):
    response = client.get("/whoami", headers=_header("Basic", "nobody", "password"))
    assert response.status_code == 404
    assert response.json()["name"] == "UserNotFoundError"


def test_password_may_contain_colons(client, user):
    user.password_hash = _password_hash("pass:wo:rd")
    db.session.flush()
    response = client.get("/whoami", headers=_header("Basic", "u1", "pass:wo:rd"))
    assert response.json()["name"] == "u1"


def test_token_auth(client, user, token):
    response = client.get("/whoami", headers=_header("Token", "u1", "the-token"))
    assert response.status_code == 200
    assert response.json()["name"] == "u1"


def test_token_auth_with_wrong_token(client, user, token):
    response = client.get("/whoami", headers=_header("Token", "u1", "other"))
    assert response.status_code == 403
    assert response.json() == {
        "name": "AuthError",
        "title": "Authentication error",
        "description": "Invalid token.",
    }


def test_token_auth_with_disabled_token(client, user, token):
    token.enabled = False
    db.session.flush()
    response = client.get("/whoami", headers=_header("Token", "u1", "the-token"))
    assert response.status_code == 403
    assert response.json()["description"] == "Invalid token."


def test_token_auth_with_expired_token(client, user, token):
    token.expiration_time = datetime(1998, 1, 1)
    db.session.flush()
    response = client.get("/whoami", headers=_header("Token", "u1", "the-token"))
    assert response.status_code == 403
    assert response.json()["description"] == "Invalid token."


def test_password_is_not_a_token_and_a_token_is_not_a_password(client, user, token):
    response = client.get("/whoami", headers=_header("Token", "u1", "password"))
    assert response.status_code == 403
    response = client.get("/whoami", headers=_header("Basic", "u1", "the-token"))
    assert response.status_code == 403


def test_unsupported_scheme(client):
    response = client.get(
        "/whoami", headers={"Authorization": "Secret SuperSecretValue"}
    )
    assert response.status_code == 400
    assert response.json() == {
        "name": "ValidationError",
        "title": "Bad Request",
        "description": "Only basic or token HTTP authentication is supported.",
    }


@pytest.mark.parametrize(
    "header",
    [
        "Basic",  # no credentials
        "Basic !!!not-base64!!!",
        "Basic " + base64.b64encode(b"no-colon").decode(),
        "Basic " + base64.b64encode(b"\xff\xfe:\xff").decode(),
        "Token " + base64.b64encode(b"no-colon").decode(),
    ],
)
def test_malformed_header(client, header):
    response = client.get("/whoami", headers={"Authorization": header})
    assert response.status_code == 400
    body = response.json()
    assert body["name"] == "ValidationError"
    assert body["title"] == "Bad Request"
    assert body["description"].startswith(
        "Authorization header values are not properly formed."
    )


def test_login_time_is_not_bumped_by_default(client, user):
    client.get("/whoami", headers=_header("Basic", "u1", "password"))
    assert user.last_login_time is None


def test_bump_login(client, user, fake_datetime):
    with fake_datetime("1997-01-01"):
        response = client.get(
            "/whoami?bump-login=true", headers=_header("Basic", "u1", "password")
        )
    assert response.status_code == 200
    assert user.last_login_time == datetime(1997, 1, 1)


def test_bump_login_with_token(client, user, token, fake_datetime):
    with fake_datetime("1997-01-01"):
        response = client.get(
            "/whoami?bump-login=yes", headers=_header("Token", "u1", "the-token")
        )
    assert response.status_code == 200
    assert user.last_login_time == datetime(1997, 1, 1)
    assert token.last_usage_time == datetime(1997, 1, 1)


def test_bump_login_of_anonymous_user_does_nothing(client):
    with patch("lithica.func.users.bump_user_login_time"):
        response = client.get("/whoami?bump-login=true")
        users.bump_user_login_time.assert_not_called()
    assert response.status_code == 200


def test_bump_login_must_be_a_boolean(client):
    response = client.get("/whoami?bump-login=perhaps")
    assert response.status_code == 400
    assert response.json() == {
        "name": "InvalidParameterError",
        "title": "Validation error",
        "description": "Parameter 'bump-login' must be a boolean value.",
    }


def test_tokens_are_compared_through_the_token_lookup(client, user, token):
    with patch("lithica.func.user_tokens.get_by_user_and_token") as lookup:
        lookup.return_value = token
        response = client.get("/whoami", headers=_header("Token", "u1", "anything"))
        user_tokens.get_by_user_and_token.assert_called_once_with(user, "anything")
    assert response.json()["name"] == "u1"


def test_privilege_granted(client, user):
    response = client.get("/tags", headers=_header("Basic", "u1", "password"))
    assert response.status_code == 200
    assert response.json() == {"name": "u1"}


def test_privilege_missing(client, user):
    response = client.delete("/tags", headers=_header("Basic", "u1", "password"))
    assert response.status_code == 403
    assert response.json() == {
        "name": "AuthError",
        "title": "Authentication error",
        "description": "Insufficient privileges to do this.",
    }


def test_privilege_missing_for_anonymous_user(client):
    response = client.get("/tags")
    assert response.status_code == 403
    assert response.json()["name"] == "AuthError"


def test_wrong_credentials_are_refused_before_the_privilege_check(client, user):
    response = client.delete("/tags", headers=_header("Basic", "u1", "wrong"))
    assert response.json()["description"] == "Invalid password."


def test_request_is_logged_with_its_user(client, user, caplog):
    client.app.add_middleware(SessionScopeMiddleware)
    with caplog.at_level(logging.INFO, logger="lithica.app"):
        client.get(
            "/whoami?bump-login=true", headers=_header("Basic", "u1", "password")
        )
        client.get("/whoami")
    messages = [record.getMessage() for record in caplog.records]
    assert messages == [
        "GET /whoami (user=u1, queries=0)",
        "GET /whoami (user=None, queries=0)",
    ]
    # neither the password nor the header reaches the log
    assert "password" not in caplog.text
    assert "Basic" not in caplog.text


def test_dependencies_describe_the_credentials(client):
    schemes = client.app.openapi()["components"]["securitySchemes"]
    assert schemes["basicAuth"] == {
        "type": "http",
        "scheme": "basic",
        "description": dependencies._basic_scheme.model.description,
    }
    assert schemes["tokenAuth"]["type"] == "apiKey"
    assert schemes["tokenAuth"]["name"] == "Authorization"
