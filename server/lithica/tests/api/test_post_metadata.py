"""Typed relations and exact installation IDs, with real request sessions."""

import base64
from typing import Any

import pytest
from fastapi.testclient import TestClient

from lithica import config, db, model, registry
from lithica.app import create_app
from lithica.func import auth, posts, user_tokens, util
from lithica.tests.api.http import shipped_config


def header(value: str) -> dict[str, str]:
    encoded = base64.b64encode(("owner:" + value).encode()).decode()
    return {"Authorization": "Token " + encoded, "Accept": "application/json"}


@pytest.fixture
def site(
    config_injector,
    tmpdir,
    committing_session,
    post_factory,
    user_factory,
    tag_category_factory,
    tag_factory,
) -> dict[str, Any]:
    config_injector(
        shipped_config(
            str(tmpdir.mkdir("data")),
            modules=["cards"],
            visibility="nsfw-login",
            file_link_secret="x" * 32,
        )
    )
    registry.load_configured()
    with db.session_scope():
        user = user_factory(name="owner", rank=model.User.RANK_REGULAR)
        db.session.add(user)
        db.session.flush()
        headers = {}
        for right in ("login", "read", "write"):
            value = auth.generate_app_token()
            token = user_tokens.new_token(
                user,
                True,
                model.UserToken.KIND_LOGIN
                if right == "login"
                else model.UserToken.KIND_APP,
                value,
            )
            if right != "login":
                token.rights = [right]
                token.note = right
            db.session.add(token)
            headers[right] = header(value)
        category = tag_category_factory(name="default", default=True)
        db.session.add(category)
        tag = tag_factory(names=["nsfw"], category=category)
        image, card, other = post_factory(), post_factory(), post_factory()
        card.kind = "card"
        db.session.add_all([tag, image, card, other])
        db.session.flush()
        ids = [post.post_id for post in (image, card, other)]
        tag_id = tag.tag_id
        db.session.commit()
    client = TestClient(create_app(), headers={"Accept": "application/json"})
    return dict(
        client=client,
        headers=headers,
        image=ids[0],
        card=ids[1],
        other=ids[2],
        tag=tag_id,
    )


def create(site: dict[str, Any], **extra: Any) -> Any:
    return site["client"].post(
        "/typed-relations",
        headers=site["headers"]["write"],
        json={"from": site["image"], "to": site["card"], "type": "gallery-of", **extra},
    )


def put_ids(
    site: dict[str, Any],
    pairs: list[dict[str, str]],
    post: int | None = None,
    right: str = "write",
) -> Any:
    return site["client"].put(
        f"/post/{post or site['image']}/external-ids?fields=id,externalIds",
        headers=site["headers"][right],
        json={"externalIds": pairs},
    )


def test_typed_relation_roundtrip(site):
    client, headers = site["client"], site["headers"]
    response = create(site, label="  smile  ")
    assert response.status_code == 200, response.text
    row = response.json()
    assert row["label"] == "smile" and row["direction"] == "out"
    assert row["post"]["id"] == site["card"]
    path = f"/post/{site['card']}/typed-relations"
    answer = client.get(path).json()["results"][0]
    assert answer["direction"] == "in"
    assert answer["post"]["id"] == site["image"]
    assert "?" in answer["post"]["contentUrl"]
    assert "?" in answer["post"]["thumbnailUrl"]
    assert client.get(path, params={"direction": "out"}).json() == {"results": []}
    assert client.get(path, params={"type": "avatar-of"}).json() == {"results": []}
    assert client.get(path, params={"direction": "in", "type": "gallery-of"}).json()[
        "results"
    ] == [answer]
    for query in ({"type": "missing"}, {"direction": "both"}):
        assert client.get(path, params=query).status_code == 400
    assert create(site).status_code == 409
    route = f"/typed-relation/{row['id']}"
    assert (
        client.put(route, headers=headers["write"], json={"label": None}).json()[
            "label"
        ]
        is None
    )
    assert client.put(route, headers=headers["write"], json={}).status_code == 400
    assert client.delete(route, headers=headers["write"]).status_code == 200
    assert client.get(path).json() == {"results": []}
    with db.session_scope():
        assert db.session.get(model.Post, site["image"]).version == 1
        assert db.session.query(model.Snapshot).count() == 0


@pytest.mark.parametrize(
    "extra",
    [
        {"from": "card", "type": "avatar-of"},
        {"to": "other", "type": "avatar-of"},
        {"to": "image"},
        {"type": "missing"},
        {"label": "x" * 129},
        {"label": "bad\nlabel"},
    ],
)
def test_invalid_typed_relation(site, extra):
    extra = {
        key: site[value] if value in {"card", "other", "image"} else value
        for key, value in extra.items()
    }
    response = create(site, **extra)
    assert response.status_code == 400, response.text
    assert response.json()["name"] == "InvalidTypedRelationError"
    if extra.get("type") == "missing":
        assert "'missing'" in response.json()["description"]


@pytest.mark.parametrize("end", ["image", "card"])
def test_delete_either_end_and_kind_change(site, end):
    assert create(site).status_code == 200
    with db.session_scope():
        post = db.session.get(model.Post, site["card"])
        post.kind = "media"
        db.session.commit()
    assert (
        len(
            site["client"]
            .get(f"/post/{site['card']}/typed-relations")
            .json()["results"]
        )
        == 1
    )
    with db.session_scope():
        db.session.delete(db.session.get(model.Post, site[end]))
        db.session.commit()
        assert db.session.query(model.PostTypedRelation).count() == 0


def test_external_ids_lookup_replace_search_and_delete(site):
    pairs = [
        {"host": "lumiverse-home", "id": "MiXeD space/a:b*"},
        {"host": "chub", "id": "second"},
    ]
    response = put_ids(site, pairs + pairs)
    assert response.status_code == 200, response.text
    assert response.json()["externalIds"] == sorted(
        pairs, key=lambda pair: pair["host"]
    )
    client = site["client"]
    for pair in pairs:
        found = client.get("/external-id", params={**pair, "fields": "id,externalIds"})
        assert found.status_code == 200, found.text
        assert found.json()["id"] == site["image"]
    for value in ("missing", pairs[0]["id"].lower()):
        assert (
            client.get(
                "/external-id", params={"host": "lumiverse-home", "id": value}
            ).status_code
            == 404
        )
    assert put_ids(site, pairs, site["other"]).status_code == 409
    for query, expected in [
        ("external-host:chub", {site["image"]}),
        ("external-host:missing", set()),
        ("-external-host:chub", {site["card"], site["other"]}),
    ]:
        response = client.get("/posts", params={"query": query, "fields": "id"})
        assert response.status_code == 200, response.text
        assert {row["id"] for row in response.json()["results"]} == expected
    assert (
        client.get("/posts", params={"query": "external-host:bad*"}).status_code == 400
    )
    assert put_ids(site, pairs[:1]).json()["externalIds"] == pairs[:1]
    assert client.get("/external-id", params=pairs[1]).status_code == 404
    with db.session_scope():
        db.session.delete(db.session.get(model.Post, site["image"]))
        db.session.commit()
    assert put_ids(site, pairs, site["other"]).status_code == 200


@pytest.mark.parametrize(
    "pair",
    [
        {"host": "Bad", "id": "ok"},
        {"host": "a" * 65, "id": "ok"},
        {"host": "ok", "id": ""},
        {"host": "ok", "id": " padded"},
        {"host": "ok", "id": "bad\n"},
        {"host": "ok", "id": "a" * 257},
    ],
)
def test_invalid_external_ids(site, pair):
    response = put_ids(site, [pair])
    assert response.status_code == 400
    assert response.json()["name"] == "InvalidExternalIdError"


@pytest.mark.parametrize("right", [None, "read"])
def test_privileges(site, right):
    row = create(site).json()
    headers = site["headers"][right] if right else {}
    client = site["client"]
    for method, path, body in [
        (
            "POST",
            "/typed-relations",
            {"from": site["other"], "to": site["card"], "type": "gallery-of"},
        ),
        ("PUT", f"/typed-relation/{row['id']}", {"label": "changed"}),
        ("DELETE", f"/typed-relation/{row['id']}", None),
        ("PUT", f"/post/{site['image']}/external-ids", {"externalIds": []}),
    ]:
        assert (
            client.request(method, path, headers=headers, json=body).status_code == 403
        )


def test_visibility_and_hidden_uniqueness(site):
    row = create(site).json()
    pair = {"host": "chub", "id": "Hidden ID/:"}
    assert put_ids(site, [pair]).status_code == 200
    with db.session_scope():
        image = db.session.get(model.Post, site["image"])
        image.tags.append(db.session.get(model.Tag, site["tag"]))
        db.session.commit()
    client = site["client"]
    path = f"/post/{site['card']}/typed-relations"
    assert client.get(path).json() == {"results": []}
    assert (
        client.get("/external-id", params=pair).json()["name"]
        == "ExternalIdNotFoundError"
    )
    assert (
        client.get("/posts", params={"query": "external-host:chub"}).json()["results"]
        == []
    )
    assert (
        client.put(f"/typed-relation/{row['id']}", json={"label": None}).status_code
        == 403
    )
    assert (
        client.delete(
            f"/typed-relation/{row['id']}", headers=site["headers"]["write"]
        ).status_code
        == 200
    )
    # Logged-in requests see both ends and the ID; conflicts never name its owner.
    assert (
        client.get(
            "/external-id", params=pair, headers=site["headers"]["read"]
        ).status_code
        == 200
    )
    assert create(site).status_code == 200
    assert len(client.get(path, headers=site["headers"]["read"]).json()["results"]) == 1
    response = put_ids(site, [pair], site["other"])
    assert response.status_code == 409
    assert str(site["image"]) not in response.json()["description"]


def test_merge_moves_metadata(site):
    assert create(site).status_code == 200
    pair = {"host": "chub", "id": "move"}
    assert put_ids(site, [pair]).status_code == 200
    with db.session_scope():
        source = db.session.get(model.Post, site["image"])
        target = db.session.get(model.Post, site["other"])
        now = util.utcnow()
        # Duplicate, self after merge, and incoming relations.
        db.session.add_all(
            [
                model.PostTypedRelation(
                    from_post_id=target.post_id,
                    to_post_id=site["card"],
                    type="gallery-of",
                    creation_time=now,
                ),
                model.PostTypedRelation(
                    from_post_id=source.post_id,
                    to_post_id=target.post_id,
                    type="arbitrary",
                    creation_time=now,
                ),
                model.PostTypedRelation(
                    from_post_id=site["card"],
                    to_post_id=source.post_id,
                    type="arbitrary",
                    creation_time=now,
                ),
            ]
        )
        db.session.flush()
        posts.merge_posts(source, target, False)
        db.session.commit()
        assert db.session.query(model.PostTypedRelation).count() == 2
        assert db.session.query(model.PostExternalId).one().post_id == target.post_id
    assert (
        site["client"].get("/external-id", params={**pair, "fields": "id"}).json()["id"]
        == site["other"]
    )


def test_relation_cap(site):
    with db.session_scope():
        now = util.utcnow()
        db.session.add_all(
            [
                model.PostTypedRelation(
                    from_post_id=site["image"],
                    to_post_id=site["other"],
                    type=f"type-{index}",
                    creation_time=now,
                )
                for index in range(1000)
            ]
        )
        db.session.commit()
    response = create(site)
    assert response.status_code == 400
    assert "1000" in response.json()["description"]


def test_info_and_disabled_type(site):
    client = site["client"]
    types = client.get("/info").json()["typedRelationTypes"]
    assert [item["name"] for item in types] == [
        "avatar-of",
        "embedded-in",
        "archived-from",
        "gallery-of",
        "expression-of",
    ]
    assert all(
        item["fromKinds"] == ["media"] and item["toKinds"] == ["card"] for item in types
    )
    registry.use([])
    assert client.get("/info").json()["typedRelationTypes"] == []
    assert create(site).status_code == 400


def test_hidden_typed_relation_is_404_for_authorized_anonymous(site):
    row = create(site).json()
    with db.session_scope():
        post = db.session.get(model.Post, site["image"])
        post.tags.append(db.session.get(model.Tag, site["tag"]))
        db.session.commit()
    config.config["privileges"]["posts:edit:typed_relations"] = "anonymous"
    client = site["client"]
    path = f"/typed-relation/{row['id']}"
    assert client.put(path, json={"label": "new"}).status_code == 404
    assert client.delete(path).status_code == 404
    assert (
        client.post(
            "/typed-relations",
            json={"from": site["image"], "to": site["card"], "type": "gallery-of"},
        ).status_code
        == 404
    )


def test_read_endpoints_require_posts_view(site):
    config.config["privileges"]["posts:view"] = "administrator"
    for path, params in [
        (f"/post/{site['card']}/typed-relations", {}),
        ("/external-id", {"host": "chub", "id": "id"}),
    ]:
        assert (
            site["client"]
            .get(path, params=params, headers=site["headers"]["read"])
            .status_code
            == 403
        )


def test_label_empty_and_ordering(site):
    row = create(site, type="expression-of", label="   ").json()
    assert row["label"] is None
    assert create(site, type="avatar-of").status_code == 200
    rows = site["client"].get(f"/post/{site['card']}/typed-relations").json()["results"]
    assert [row["type"] for row in rows] == ["avatar-of", "expression-of"]


def test_external_host_uses_existing_escaping(site):
    pair = {"host": "my..home", "id": "ID"}
    assert put_ids(site, [pair]).status_code == 200
    response = site["client"].get(
        "/posts", params={"query": r"external-host:my\.\.home", "fields": "id"}
    )
    assert response.status_code == 200, response.text
    assert [post["id"] for post in response.json()["results"]] == [site["image"]]
