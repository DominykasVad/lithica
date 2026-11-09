"""
Login tokens and app tokens, over HTTP with real Authorization headers: a
value is shown once and never read back, tokens are named by id only, and
an app token does only what its rights and its owner's rank allow.
"""

import base64
from datetime import datetime
from unittest.mock import patch

import pytest
import yaml

from lithica import db, errors, model, registry
from lithica.app import create_app
from lithica.func import app_token_rights, app_tokens, auth, user_tokens
from lithica.tests.api.http import assert_error, ok, shipped_config
from lithica.tests.conftest import ApiClient
from lithica.tests.modules import cards


def _header(user_name: str, value: str) -> dict[str, str]:
    credentials = base64.b64encode(("%s:%s" % (user_name, value)).encode()).decode()
    return {"Authorization": "Token %s" % credentials}


def _dist_config() -> dict:
    with open("config.yaml.dist") as handle:
        return yaml.safe_load(handle)


@pytest.fixture
def client(config_injector, tmpdir, tag_category_factory) -> ApiClient:
    """An open site with the cards module and the shipped privileges."""
    config_injector(shipped_config(str(tmpdir.mkdir("data")), modules=["cards"]))
    db.session.add(tag_category_factory(name="default", default=True))
    db.session.flush()
    registry.load_configured()
    return ApiClient(create_app())


@pytest.fixture
def owner(user_factory) -> model.User:
    user = user_factory(name="owner", rank=model.User.RANK_REGULAR)
    db.session.add(user)
    db.session.flush()
    return user


@pytest.fixture
def card_post(client, owner) -> int:
    created = ok(
        client.post(
            "/posts",
            user=owner,
            body={"safety": "safe", "tags": ["a_card"]},
            files={"content": cards.png_card(cards.v2_card())},
        )
    )
    return created["id"]


def _login_token(client, user, **body) -> dict:
    return ok(client.post("/user-token/%s" % user.name, user=user, body=body))


def _app_token(client, user, rights, **body) -> dict:
    return ok(
        client.post(
            "/app-token/%s" % user.name,
            user=user,
            body={"name": "my app", "rights": rights, **body},
        )
    )


def _as(token: dict, user: model.User) -> dict[str, str]:
    return _header(user.name, token["token"])


def _who(client, headers) -> int:
    return client.get("/user/owner", headers=headers).status_code


# ---------------------------------------------------------------------------
# login tokens


def test_login_token_value_is_shown_once(client, owner):
    created = _login_token(client, owner, note="laptop")
    assert isinstance(created["id"], int)
    value = created["token"]
    assert isinstance(value, str) and len(value) == 43
    # stored as its hash, and nothing else
    stored = db.session.get(model.UserToken, created["id"])
    assert stored.token_hash == auth.hash_token(value)
    assert value not in (stored.note or "")

    listed = ok(client.get("/user-tokens/owner", user=owner))["results"]
    assert [one["token"] for one in listed] == [None]
    assert [one["id"] for one in listed] == [created["id"]]
    asked = ok(client.get("/user-tokens/owner", user=owner, query={"fields": "token"}))
    assert asked["results"] == [{"token": None}]

    updated = ok(
        client.put(
            "/user-token/owner/%d" % created["id"],
            user=owner,
            body={"version": created["version"], "note": "desktop"},
        )
    )
    assert updated["token"] is None
    assert updated["note"] == "desktop"
    # and it works
    assert _who(client, _as(created, owner)) == 200


def test_login_token_is_named_by_id_never_by_value(client, owner):
    created = _login_token(client, owner)
    value = created["token"]
    assert_error(
        client.put("/user-token/owner/%s" % value, user=owner, body={"version": 1}),
        user_tokens.UserTokenNotFoundError,
    )
    # a value in the path deletes nothing
    assert ok(client.delete("/user-token/owner/%s" % value, user=owner)) == {}
    assert _who(client, _as(created, owner)) == 200
    # an unknown id: the same answer
    assert ok(client.delete("/user-token/owner/999999", user=owner)) == {}
    # by id it goes, and stops working
    assert ok(client.delete("/user-token/owner/%d" % created["id"], user=owner)) == {}
    assert_error(
        client.get("/user/owner", headers=_as(created, owner)),
        errors.InvalidTokenError,
    )


def test_logout_deletes_by_id_with_the_token_itself(client, owner):
    created = _login_token(client, owner)
    headers = _as(created, owner)
    assert (
        ok(client.delete("/user-token/owner/%d" % created["id"], headers=headers)) == {}
    )
    assert_error(client.get("/user/owner", headers=headers), errors.InvalidTokenError)


def test_another_users_token_id_is_not_found(client, owner, user_factory):
    other = user_factory(name="other")
    db.session.add(other)
    db.session.flush()
    theirs = _login_token(client, other)
    assert_error(
        client.put(
            "/user-token/owner/%d" % theirs["id"], user=owner, body={"version": 1}
        ),
        user_tokens.UserTokenNotFoundError,
    )
    assert ok(client.delete("/user-token/owner/%d" % theirs["id"], user=owner)) == {}
    assert _who(client, _as(theirs, other)) == 200


def test_kinds_do_not_mix(client, owner):
    login = _login_token(client, owner)
    app = _app_token(client, owner, ["read"])
    assert_error(
        client.put("/user-token/owner/%d" % app["id"], user=owner, body={"version": 1}),
        user_tokens.UserTokenNotFoundError,
    )
    assert ok(client.delete("/user-token/owner/%d" % app["id"], user=owner)) == {}
    assert_error(
        client.put(
            "/app-token/owner/%d" % login["id"], user=owner, body={"version": 1}
        ),
        app_tokens.AppTokenNotFoundError,
    )
    assert ok(client.delete("/app-token/owner/%d" % login["id"], user=owner)) == {}
    # both still work, and each list has its own kind only
    assert _who(client, _as(login, owner)) == 200
    assert client.get("/posts", headers=_as(app, owner)).status_code == 200
    assert [
        t["id"] for t in ok(client.get("/user-tokens/owner", user=owner))["results"]
    ] == [login["id"]]
    assert [
        t["id"] for t in ok(client.get("/app-tokens/owner", user=owner))["results"]
    ] == [app["id"]]


# ---------------------------------------------------------------------------
# app tokens: the routes


def test_app_token_is_shown_once(client, owner):
    created = _app_token(
        client, owner, ["read", "upload", "read"], expirationTime="2100-01-01T00:00:00Z"
    )
    assert created["token"].startswith("lithica_app_")
    assert created["name"] == "my app"
    assert created["rights"] == ["read", "upload"]
    assert created["enabled"] is True
    assert created["expirationTime"] is not None
    assert created["user"]["name"] == "owner"
    stored = db.session.get(model.UserToken, created["id"])
    assert stored.kind == "app"
    assert stored.token_hash == auth.hash_token(created["token"])

    listed = ok(client.get("/app-tokens/owner", user=owner))["results"]
    assert len(listed) == 1 and listed[0]["token"] is None
    updated = ok(
        client.put(
            "/app-token/owner/%d" % created["id"],
            user=owner,
            body={
                "version": created["version"],
                "name": "renamed",
                "rights": ["write"],
            },
        )
    )
    assert updated["name"] == "renamed"
    # rights cannot be changed
    assert updated["rights"] == ["read", "upload"]
    assert updated["token"] is None


@pytest.mark.parametrize(
    "body",
    [
        {"name": "x", "rights": []},
        {"name": "x"},
        {"name": "x", "rights": ["delete"]},
        {"name": "x", "rights": ["read", 5]},
        {"name": "x", "rights": 5},
        {"name": "  ", "rights": ["read"]},
        {"rights": ["read"]},
        {"name": "x" * 129, "rights": ["read"]},
    ],
)
def test_creating_refuses_bad_names_and_rights(client, owner, body):
    response = client.post("/app-token/owner", user=owner, body=body)
    assert response.status_code == 400, response.text
    assert db.session.query(model.UserToken).count() == 0


def test_creating_refuses_a_right_the_owner_holds_nothing_of(client, user_factory):
    restricted = user_factory(name="restricted", rank=model.User.RANK_RESTRICTED)
    db.session.add(restricted)
    db.session.flush()
    with patch.dict(
        "lithica.config.config",
        {
            "privileges": _dist_config()["privileges"]
            | {"app_tokens:create:self": "restricted"}
        },
    ):
        # a restricted user may read, but neither upload nor write
        _app_token(client, restricted, ["read"])
        for right in ["upload", "write"]:
            response = client.post(
                "/app-token/restricted",
                user=restricted,
                body={"name": "x", "rights": ["read", right]},
            )
            assert response.status_code == 400, response.text


def test_revoking(client, owner):
    created = _app_token(client, owner, ["read"])
    headers = _as(created, owner)
    assert client.get("/posts", headers=headers).status_code == 200
    assert ok(client.delete("/app-token/owner/%d" % created["id"], user=owner)) == {}
    assert_error(client.get("/posts", headers=headers), errors.InvalidTokenError)
    # gone already: the same answer
    assert ok(client.delete("/app-token/owner/%d" % created["id"], user=owner)) == {}


def test_disabled_and_expired_app_tokens_do_not_work(client, owner, fake_datetime):
    disabled = _app_token(client, owner, ["read"], enabled=False)
    assert_error(
        client.get("/posts", headers=_as(disabled, owner)),
        errors.InvalidTokenError,
    )
    expiring = _app_token(
        client, owner, ["read"], expirationTime="2100-01-01T00:00:00Z"
    )
    with fake_datetime("2100-01-02"):
        assert_error(
            client.get("/posts", headers=_as(expiring, owner)),
            errors.InvalidTokenError,
        )


def test_bump_login_with_an_app_token(client, owner, fake_datetime):
    created = _app_token(client, owner, ["read"])
    owner.last_login_time = datetime(1990, 1, 1)
    db.session.flush()
    with fake_datetime("2000-01-01"):
        ok(
            client.get(
                "/posts", query={"bump-login": "yes"}, headers=_as(created, owner)
            )
        )
    assert owner.last_login_time == datetime(1990, 1, 1)
    token = db.session.get(model.UserToken, created["id"])
    assert token.last_usage_time == datetime(2000, 1, 1)


def test_info_lists_the_rights(client):
    info = ok(client.get("/info"))
    rights = info["appTokenRights"]
    assert set(rights) == set(app_token_rights.RIGHTS)
    assert "posts:list" in rights["read"]
    assert "tagCategories:list" in rights["read"]
    assert "posts:reverseSearch" in rights["read"]
    assert rights["upload"] == ["uploads:create"]
    for privileges in rights.values():
        for privilege in privileges:
            assert privilege in info["config"]["privileges"]


# ---------------------------------------------------------------------------
# app tokens: what a request made with one may do


def test_read_token_reads_cards_and_posts(client, owner, card_post):
    headers = _as(_app_token(client, owner, ["read"]), owner)
    assert (
        client.get("/modules/cards/post/%d" % card_post, headers=headers).status_code
        == 200
    )
    download = client.get(
        "/modules/cards/post/%d/download" % card_post, headers=headers
    )
    assert download.status_code == 200
    assert ok(client.get("/posts", headers=headers))["total"] == 1
    assert ok(client.get("/post/%d" % card_post, headers=headers))["id"] == card_post


def test_read_token_may_change_nothing(client, owner, card_post, read_asset):
    token = _app_token(client, owner, ["read"])
    headers = _as(token, owner)
    post = ok(client.get("/post/%d" % card_post, user=owner))
    login = _login_token(client, owner)
    user_version = owner.version
    attempts = [
        lambda: client.post(
            "/uploads", headers=headers, files={"content": read_asset("png.png")}
        ),
        lambda: client.post(
            "/posts",
            headers=headers,
            body={"safety": "safe"},
            files={"content": read_asset("png.png")},
        ),
        lambda: client.post(
            "/tags", headers=headers, body={"names": ["new"], "category": "default"}
        ),
        lambda: client.put(
            "/post/%d" % card_post,
            headers=headers,
            body={"version": post["version"], "tags": ["other"]},
        ),
        # an edit that names nothing to change, which asks no privilege
        lambda: client.put(
            "/post/%d" % card_post, headers=headers, body={"version": post["version"]}
        ),
        lambda: client.delete(
            "/post/%d" % card_post, headers=headers, body={"version": post["version"]}
        ),
        # every token route, its own token included
        lambda: client.get("/user-tokens/owner", headers=headers),
        lambda: client.post("/user-token/owner", headers=headers, body={}),
        lambda: client.put(
            "/user-token/owner/%d" % login["id"], headers=headers, body={"version": 1}
        ),
        lambda: client.delete("/user-token/owner/%d" % login["id"], headers=headers),
        lambda: client.get("/app-tokens/owner", headers=headers),
        lambda: client.post(
            "/app-token/owner", headers=headers, body={"name": "x", "rights": ["read"]}
        ),
        lambda: client.put(
            "/app-token/owner/%d" % token["id"],
            headers=headers,
            body={"version": 1, "name": "x"},
        ),
        lambda: client.delete("/app-token/owner/%d" % token["id"], headers=headers),
        # the account
        lambda: client.get("/user/owner", headers=headers),
        lambda: client.delete(
            "/user/owner", headers=headers, body={"version": user_version}
        ),
    ]
    for field, value in [
        ("name", "renamed"),
        ("password", "new password"),
        ("email", "x@example.com"),
        ("rank", "restricted"),
        ("avatarStyle", "gravatar"),
        (None, None),
    ]:
        body = {"version": user_version}
        if field is not None:
            body[field] = value
        attempts.append(
            lambda body=body: client.put("/user/owner", headers=headers, body=body)
        )
    for index, attempt in enumerate(attempts):
        # what a refused request left in the test's session (a request of the
        # server rolls it back) is not seen by the next one
        db.session.expire_all()
        response = attempt()
        assert response.status_code == 403, (index, response.text)
        assert_error(response, errors.AuthError)
        assert response.json()["name"] == "AuthError", response.text

    # nothing happened: the tokens are there, the account and the post as they were
    db.session.expire_all()
    assert db.session.query(model.UserToken).count() == 2
    assert db.session.get(model.User, owner.user_id).name == "owner"
    assert (
        ok(client.get("/post/%d" % card_post, user=owner))["version"] == post["version"]
    )
    assert ok(client.get("/posts", user=owner))["total"] == 1


def test_an_edit_that_names_nothing_still_works_with_a_login_token(
    client, owner, card_post
):
    headers = _as(_login_token(client, owner), owner)
    post = ok(client.get("/post/%d" % card_post, user=owner))
    ok(
        client.put(
            "/post/%d" % card_post, headers=headers, body={"version": post["version"]}
        )
    )


def test_write_and_upload_token_creates_posts(client, owner, read_asset):
    headers = _as(_app_token(client, owner, ["write", "upload"]), owner)
    upload = ok(
        client.post(
            "/uploads", headers=headers, files={"content": read_asset("png.png")}
        )
    )
    created = ok(
        client.post(
            "/posts",
            headers=headers,
            body={
                "safety": "safe",
                "tags": ["brand_new"],
                "contentToken": upload["token"],
            },
        )
    )
    assert created["user"]["name"] == "owner"
    edited = ok(
        client.put(
            "/post/%d" % created["id"],
            headers=headers,
            body={"version": created["version"], "tags": ["brand_new", "another"]},
        )
    )
    assert len(edited["tags"]) == 2


def test_write_token_of_a_regular_owner_cannot_do_what_power_users_do(
    client, owner, read_asset
):
    headers = _as(_app_token(client, owner, ["write"]), owner)
    post = ok(
        client.post(
            "/posts",
            headers=headers,
            body={"safety": "safe"},
            files={"content": read_asset("png.png")},
        )
    )
    # posts:edit:content is for power users
    assert_error(
        client.put(
            "/post/%d" % post["id"],
            headers=headers,
            body={"version": post["version"]},
            files={"content": read_asset("jpeg.jpg")},
        ),
        errors.AuthError,
    )


def test_demoting_the_owner_shrinks_the_token(client, owner, read_asset):
    headers = _as(_app_token(client, owner, ["read", "upload"]), owner)
    ok(
        client.post(
            "/uploads", headers=headers, files={"content": read_asset("png.png")}
        )
    )
    owner.rank = model.User.RANK_RESTRICTED
    db.session.flush()
    assert_error(
        client.post(
            "/uploads", headers=headers, files={"content": read_asset("png.png")}
        ),
        errors.AuthError,
    )
    # what the rank still grants, it still may
    ok(client.get("/posts", headers=headers))


def test_deleted_token_and_unknown_right(client, owner):
    created = _app_token(client, owner, ["read"])
    stored = db.session.get(model.UserToken, created["id"])
    stored.rights = ["read-everything"]
    db.session.flush()
    assert_error(client.get("/posts", headers=_as(created, owner)), errors.AuthError)
    db.session.delete(stored)
    db.session.flush()
    assert_error(
        client.get("/posts", headers=_as(created, owner)),
        errors.InvalidTokenError,
    )


def test_administrators_token_reaches_nothing_about_accounts(
    client, user_factory, session
):
    admin = user_factory(name="admin", rank=model.User.RANK_ADMINISTRATOR)
    db.session.add(admin)
    db.session.flush()
    created = _app_token(client, admin, sorted(app_token_rights.RIGHTS))
    headers = _as(created, admin)
    for response in [
        client.get("/users", headers=headers),
        client.get("/user/admin", headers=headers),
        client.get("/user-tokens/admin", headers=headers),
        client.get("/app-tokens/admin", headers=headers),
        client.post(
            "/users", headers=headers, body={"name": "new", "password": "pass1"}
        ),
    ]:
        assert_error(response, errors.AuthError)

    # and none of those privileges at all, as has_privilege answers them
    stored = db.session.get(model.UserToken, created["id"])
    with db.session_scope():
        app_token_rights.begin_app_token_request(stored.rights)
        for privilege in _dist_config()["privileges"]:
            if app_token_rights.is_forbidden(privilege):
                assert not auth.has_privilege(admin, privilege), privilege
            elif privilege not in app_token_rights.privileges_of(stored.rights):
                assert not auth.has_privilege(admin, privilege), privilege
            else:
                assert auth.has_privilege(admin, privilege), privilege


def test_write_app_token_cannot_change_post_kind(client, owner, card_post):
    headers = _as(_app_token(client, owner, ["write"]), owner)
    post = ok(client.get("/post/%d" % card_post, user=owner))
    response = client.put(
        "/post/%d/kind" % card_post,
        headers=headers,
        body={"version": post["version"], "kind": "media"},
    )
    assert_error(response, errors.AuthError)
    assert (
        ok(client.get("/post/%d" % card_post, user=owner))["version"] == post["version"]
    )
