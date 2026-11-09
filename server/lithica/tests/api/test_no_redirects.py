"""
Contract (doc/API.md, General rules): an authenticated API route never
answers with a redirect. Clients such as Lumiverse drop the credentials on a
redirect, so a path is answered as written, with or without the trailing
slash.

The walk takes every route of the application as it is built, the engine's
and those of every module in lithica/modules (registry.available()), from
the application's routes themselves: a new route is walked without a change
here. Each is sent with a login token and with an app token, with and
without the trailing slash. Errors from the sample values are fine; a
redirect is not, and neither is a server error.
"""

import base64
import re
from typing import Any
from unittest.mock import patch

import pytest
from fastapi.routing import iter_route_contexts
from fastapi.testclient import TestClient
from starlette.applications import Starlette
from starlette.responses import RedirectResponse
from starlette.routing import Route

from lithica import db, model, registry
from lithica.app import create_app
from lithica.func import app_token_rights, auth, user_tokens
from lithica.tests.api.http import shipped_config
from lithica.tests.modules import cards

PARAMETER = re.compile(r"\{([^}:]+)(:[^}]+)?\}")

# what a path parameter is filled with, by its name; any other name gets "1"
SAMPLES = {
    "post_id": "1",
    "user_name": "walker",
    # no token of the walker: its own are not deleted on the way
    "token_id": "999999",
    "comment_id": "1",
    "pool_id": "1",
    "tag_name": "a_tag",
    "category_name": "default",
}


def _routes(app: Any) -> list[tuple[str, str]]:
    found = set()
    for route in iter_route_contexts(app.routes):
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None) or set()
        if not path:
            continue
        for method in methods:
            if method != "HEAD":
                found.add((method, path))
    return sorted(found)


def _fill(template: str) -> str:
    return PARAMETER.sub(lambda match: SAMPLES.get(match.group(1), "1"), template)


def _header(user_name: str, value: str) -> dict[str, str]:
    credentials = base64.b64encode(("%s:%s" % (user_name, value)).encode()).decode()
    return {"Authorization": "Token %s" % credentials, "Accept": "application/json"}


def _is_redirect(response: Any) -> bool:
    return 300 <= response.status_code < 400 or "location" in response.headers


def test_the_check_sees_a_redirect():
    # without this, a client that follows redirects would pass the walk
    def redirect(_request: Any) -> RedirectResponse:
        return RedirectResponse("/elsewhere", status_code=307)

    client = TestClient(
        Starlette(routes=[Route("/r", redirect)]), follow_redirects=False
    )
    assert _is_redirect(client.get("/r"))


@pytest.fixture
def walk_client(config_injector, tmpdir, tag_category_factory, user_factory):
    config = shipped_config(str(tmpdir.mkdir("data")))
    # a site that sends mail (caught below): password reset answers as it is
    # meant to, not with the error of a site that cannot
    config["smtp"] = config["smtp"] | {"host": "mail.example.com"}
    config["domain"] = "https://example.com"
    config_injector(config)
    registry.use(registry.available())
    db.session.add(tag_category_factory(name="default", default=True))
    walker = user_factory(name="walker", rank=model.User.RANK_ADMINISTRATOR)
    db.session.add(walker)
    login, login_value = user_tokens.create_user_token(walker, True)
    app_value = auth.generate_app_token()
    app_token = user_tokens.new_token(walker, True, model.UserToken.KIND_APP, app_value)
    app_token.note = "walker"
    app_token.rights = sorted(app_token_rights.RIGHTS)
    db.session.add_all([login, app_token])
    db.session.flush()
    application = create_app()
    client = TestClient(application, follow_redirects=False)
    # a post (a card) for the post routes' sample id to find
    created = client.post(
        "/posts",
        headers=_header("walker", login_value),
        data={"metadata": '{"safety": "safe", "tags": ["a_tag"]}'},
        files={"content": ("card.png", cards.png_card(cards.v2_card()))},
    )
    assert created.status_code == 200, created.text
    return application, client, {"login": login_value, "app": app_value}


@pytest.fixture(autouse=True)
def no_mail():
    with patch("lithica.func.mailer.send_mail"):
        yield


def test_no_route_answers_with_a_redirect(walk_client):
    application, client, values = walk_client
    routes = _routes(application)
    paths = {path for _, path in routes}
    # the walk covers the engine, the modules and the plain download route
    assert "/posts" in paths
    assert "/app-token/{user_name}/{token_id}" in paths
    assert "/modules/cards/post/{post_id}/download" in paths

    redirects: list[str] = []
    server_errors: list[str] = []
    answered = {kind: 0 for kind in values}
    for method, template in routes:
        filled = _fill(template)
        for path in {filled.rstrip("/") or "/", filled.rstrip("/") + "/"}:
            for kind, value in values.items():
                kwargs: dict[str, Any] = {"headers": _header("walker", value)}
                if method in ("POST", "PUT", "DELETE"):
                    kwargs["json"] = {}
                response = client.request(method, path, **kwargs)
                label = "%s %s (%s): %d" % (method, path, kind, response.status_code)
                if response.status_code == 200:
                    answered[kind] += 1
                if _is_redirect(response):
                    redirects.append(label)
                if response.status_code >= 500:
                    server_errors.append(label + " " + response.text[:120])
    assert redirects == []
    assert server_errors == []
    # both tokens worked: the routes answered, not only the authentication
    assert answered["login"] > 40, answered
    assert answered["app"] > 20, answered
