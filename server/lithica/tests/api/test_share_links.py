"""Share link management and credential-independent delivery."""

from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from lithica import config, db, model
from lithica.app import create_app
from lithica.func import auth, posts, share_links, util
from lithica.tests.api.http import ok, shipped_config
from lithica.tests.conftest import ApiClient

Site = tuple[ApiClient, model.User, model.User, model.User, model.Post]


@pytest.fixture
def site(
    config_injector: Callable[[dict[str, Any]], None],
    tmp_path: Path,
    user_factory: Callable[..., model.User],
    post_factory: Callable[..., model.Post],
) -> Site:
    # Any: the shared config fixture accepts heterogeneous configuration values.
    directory = tmp_path / "data"
    directory.mkdir()
    config_injector(shipped_config(str(directory)))
    owner = user_factory(name="owner", rank=model.User.RANK_REGULAR)
    admin = user_factory(name="admin", rank=model.User.RANK_ADMINISTRATOR)
    other = user_factory(name="other", rank=model.User.RANK_REGULAR)
    post = post_factory()
    db.session.add_all([owner, admin, other, post])
    db.session.flush()
    return ApiClient(create_app()), owner, admin, other, post


def make(site: Site, **body: object) -> dict[str, Any]:
    # Any: the HTTP helper decodes a heterogeneous JSON resource.
    client, owner, _, _, post = site
    return ok(client.post(f"/post/{post.post_id}/share-links", user=owner, body=body))


def test_derivation_and_storage(site: Site) -> None:
    link = make(site, note="reuse")
    row = db.session.get(model.ShareLink, link["id"])
    token = link["url"].split("/")[-1]
    assert share_links.derive_token(row.salt) == token
    assert row.token_hash == auth.hash_token(token)
    assert "token" not in row.__table__.columns
    assert len(row.salt) == 32
    assert token != share_links.derive_token(b"other")
    with patch.dict(config.config, secret="changed"):
        assert token != share_links.derive_token(row.salt)
        assert site[0].get(link["url"]).status_code == 404


def test_management(site: Site) -> None:
    client, owner, admin, other, post = site
    link = make(site, note="again")
    route = f"/post/{post.post_id}/share-links"
    assert ok(client.get(route, user=owner))["results"] == [link]
    assert ok(client.get(route, user=other))["results"] == []
    assert ok(client.get(route, user=admin))["results"] == [link]
    assert client.get(route).status_code == 403
    assert client.get("/user/owner/share-links", user=other).status_code == 403
    assert (
        ok(client.get("/user/owner/share-links?offset=1&limit=1", user=admin))[
            "results"
        ]
        == []
    )
    assert ok(client.get("/user/owner/share-links", user=owner))["total"] == 1
    assert client.delete(f"/share-link/{link['id']}", user=other).status_code == 403
    ok(client.delete(f"/share-link/{link['id']}", user=owner))
    assert client.get(link["url"]).status_code == 404


@pytest.mark.parametrize("mode", ["open", "login", "nsfw-login"])
def test_delivery_and_identical_refusals(site: Site, mode: str) -> None:
    client, owner, _, _, post = site
    link = make(site, expiresAt=(util.utcnow() + timedelta(days=1)).isoformat())
    config.config["visibility"] = mode
    before = posts.get_post_content_url(post), posts.get_post_thumbnail_url(post)
    response = client.get(link["url"], headers={"Authorization": "wrong"})
    assert response.status_code == 200
    assert response.content == b""
    assert response.headers["Content-Type"] == post.mime_type
    assert response.headers[
        "X-Accel-Redirect"
    ] == "/_share/" + posts.get_post_content_path(post).removeprefix("posts/")
    assert before == (
        posts.get_post_content_url(post),
        posts.get_post_thumbnail_url(post),
    )
    missing = client.get("/share/malformed!")
    assert missing.status_code == 404
    assert client.get("/share/" + "a" * 43).json() == missing.json()
    with patch(
        "lithica.func.util.utcnow", return_value=util.utcnow() + timedelta(days=2)
    ):
        assert client.get(link["url"]).json() == missing.json()
    ok(client.delete(f"/share-link/{link['id']}", user=owner))
    assert client.get(link["url"]).json() == missing.json()


def test_validation_cap_and_nsfw(
    site: Site, tag_factory: Callable[..., model.Tag]
) -> None:
    client, owner, _, _, post = site
    route = f"/post/{post.post_id}/share-links"
    for body in (
        {"expiresAt": "2000-01-01"},
        {"expiresAt": "bad"},
        {"note": "x" * 129},
    ):
        assert client.post(route, user=owner, body=body).status_code == 400
    link = make(site)
    post.tags.append(tag_factory(names=["nsfw"]))
    db.session.commit()
    assert client.post(route, user=owner, body={}).status_code == 400
    for mode in ("open", "login", "nsfw-login"):
        config.config["visibility"] = mode
        refused = client.get(link["url"])
        assert refused.status_code == 404
        assert refused.json() == client.get("/share/missing").json()
        config.config["share_links_nsfw"] = True
        assert client.get(link["url"]).status_code == 200
        config.config["share_links_nsfw"] = False
    config.config["share_links_nsfw"] = True
    for _ in range(99):
        make(site)
    assert client.post(route, user=owner, body={}).status_code == 400


@pytest.mark.parametrize("target", ["post", "user"])
def test_cascade(site: Site, target: str) -> None:
    client, owner, _, _, post = site
    link = make(site)
    db.session.delete(post if target == "post" else owner)
    db.session.commit()
    db.session.expire_all()
    assert db.session.get(model.ShareLink, link["id"]) is None
    assert client.get(link["url"]).status_code == 404


def test_merge_drops_source_links_and_keeps_target(
    site: Site, post_factory: Callable[..., model.Post]
) -> None:
    _, owner, _, _, source = site
    target = post_factory()
    db.session.add(target)
    db.session.flush()
    source_link = share_links.create(source, owner, None, None)
    target_link = share_links.create(target, owner, None, None)
    source_id, target_id = source_link.id, target_link.id
    posts.merge_posts(source, target, False)
    db.session.commit()
    db.session.expire_all()
    assert db.session.get(model.ShareLink, source_id) is None
    assert db.session.get(model.ShareLink, target_id) is not None


def test_delivery_uses_current_content_type(
    site: Site, read_asset: Callable[[str], bytes]
) -> None:
    client, _, _, _, post = site
    link = make(site)
    before = client.get(link["url"]).headers["X-Accel-Redirect"]
    posts.update_post_content(post, read_asset("gif.gif"))
    db.session.commit()
    response = client.get(link["url"])
    assert response.headers["Content-Type"] == "image/gif"
    assert response.headers["X-Accel-Redirect"] != before


def test_share_token_is_not_logged(
    site: Site, caplog: pytest.LogCaptureFixture
) -> None:
    import logging

    link = make(site)
    with caplog.at_level(logging.INFO, logger="lithica.app"):
        site[0].get(link["url"])
    assert link["url"].split("/")[-1] not in caplog.text


@pytest.mark.parametrize(
    "rank,allowed",
    [
        ("restricted", False),
        ("regular", True),
        ("power", True),
        ("moderator", True),
        ("administrator", True),
    ],
)
def test_rank_privileges(site: Site, rank: str, allowed: bool) -> None:
    client, owner, _, _, post = site
    owner.rank = rank
    db.session.commit()
    response = client.post(f"/post/{post.post_id}/share-links", user=owner, body={})
    assert response.status_code == (200 if allowed else 403)


def test_nsfw_implication(site: Site, tag_factory: Callable[..., model.Tag]) -> None:
    client, _, _, _, post = site
    link = make(site)
    parent = tag_factory(names=["implies_nsfw"])
    child = tag_factory(names=["nsfw"])
    parent.implications.append(child)
    post.tags.append(parent)
    db.session.commit()
    assert client.get(link["url"]).status_code == 404


def test_config_boolean() -> None:
    from lithica import errors

    with pytest.raises(errors.ConfigError, match="share_links_nsfw"):
        with patch.dict(config.config, share_links_nsfw="false"):
            config.validate_visibility()


def test_admin_can_revoke_another_users_link_and_page(site: Site) -> None:
    client, owner, admin, _, _ = site
    first = make(site)
    second = make(site)
    page = ok(client.get("/user/owner/share-links?offset=1&limit=1", user=admin))
    assert page["total"] == 2
    assert page["results"] == [second]
    ok(client.delete(f"/share-link/{first['id']}", user=admin))
    assert client.get(first["url"]).status_code == 404
    assert ok(client.get("/user/owner/share-links", user=owner))["results"] == [second]


def test_user_list_respects_anonymous_visibility(
    site: Site, tag_factory: Callable[..., model.Tag]
) -> None:
    client, _, _, _, post = site
    make(site)
    post.tags.append(tag_factory(names=["nsfw"]))
    db.session.commit()
    config.config["visibility"] = "nsfw-login"
    config.config["privileges"]["share_links:list:any"] = "anonymous"
    response = ok(client.get("/user/owner/share-links"))
    assert response["total"] == 0
    assert response["results"] == []
