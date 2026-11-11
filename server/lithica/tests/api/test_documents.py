"""Document endpoints obey post visibility and application-token rights."""

import base64
from collections.abc import Callable
from pathlib import Path

from fastapi.testclient import TestClient

from lithica import db, model, registry
from lithica.app import create_app
from lithica.func import auth, documents, posts, user_tokens
from lithica.tests.api.http import enabled_config
from lithica.tests.conftest import ApiClient
from lithica.tests.fixtures.modules import dummy
from lithica.tests.test_documents import document_post  # noqa: F401


def test_document_endpoints(document_post: tuple[model.Post, model.User]) -> None:  # noqa: F811
    post, user = document_post
    client = ApiClient(create_app())
    path = f"/post/{post.post_id}"
    response = client.get(path + "/document", user=user)
    assert response.status_code == 404
    assert response.json()["name"] == "DocumentNotFoundError"
    documents.create(post, "dummy_document", {"text": "first"}, user)
    documents.write(post, {"text": "second"}, 0, user)
    db.session.commit()
    response = client.get(path + "/document", user=user)
    assert response.status_code == 200
    assert response.json()["data"] == {"text": "second"}
    response = client.get(
        path + "/document-versions", user=user, query={"offset": 1, "limit": 1}
    )
    assert response.status_code == 200
    assert response.json()["total"] == 2
    assert response.json()["results"][0]["number"] == 0
    assert "data" not in response.json()["results"][0]
    assert (
        client.get(
            path + "/document-versions", user=user, query={"limit": 101}
        ).status_code
        == 400
    )
    response = client.get(path + "/document-version/0", user=user)
    assert response.status_code == 200 and response.json()["data"] == {"text": "first"}
    response = client.post(
        path + "/document-version/0/restore", user=user, body={"version": 1}
    )
    assert response.status_code == 200 and response.json()["version"] == 2
    response = client.post(
        path + "/document-version/0/restore", user=user, body={"version": 1}
    )
    assert response.status_code == 409
    assert client.get(path + "/document-version/99", user=user).status_code == 404
    registry.use([])
    assert client.get(path + "/document", user=user).status_code == 404
    assert (
        client.post(
            path + "/document-version/0/restore", user=user, body={"version": 2}
        ).status_code
        == 404
    )


def test_tokens_and_visibility(
    config_injector: Callable[..., None],
    tmp_path: Path,
    committing_session: None,
    user_factory: Callable[..., model.User],
    tag_category_factory: Callable[..., model.TagCategory],
    tag_factory: Callable[..., model.Tag],
) -> None:
    config_injector(
        enabled_config({"data_dir": str(tmp_path), "visibility": "nsfw-login"})
    )
    registry.use([dummy.module])
    headers: dict[str, dict[str, str]] = {}
    with db.session_scope():
        user = user_factory(name="owner", rank=model.User.RANK_REGULAR)
        category = tag_category_factory(name="default", default=True)
        db.session.add_all([user, category])
        db.session.flush()
        tag = tag_factory(names=["nsfw"], category=category)
        db.session.add(tag)
        post = posts.create_fileless_post("dummy_document", user)
        post.tags = [tag]
        documents.create(post, "dummy_document", {"text": "first"}, user)
        documents.write(post, {"text": "second"}, 0, user)
        post_id = post.post_id
        for right in ("read", "write"):
            value = auth.generate_app_token()
            token = user_tokens.new_token(user, True, model.UserToken.KIND_APP, value)
            token.rights = [right]
            token.note = right
            db.session.add(token)
            encoded = base64.b64encode(("owner:" + value).encode()).decode()
            headers[right] = {"Authorization": "Token " + encoded}
        db.session.commit()
    client = TestClient(create_app(), headers={"Accept": "application/json"})
    path = f"/post/{post_id}"
    for suffix in ("/document", "/document-versions", "/document-version/0"):
        assert client.get(path + suffix).status_code == 404
        assert client.get(path + suffix, headers=headers["read"]).status_code == 200
    assert (
        client.post(
            path + "/document-version/0/restore",
            headers=headers["read"],
            json={"version": 1},
        ).status_code
        == 403
    )
    response = client.post(
        path + "/document-version/0/restore",
        headers=headers["write"],
        json={"version": 1},
    )
    assert response.status_code == 200 and response.json()["version"] == 2


def test_restore_rejection_and_pruned_version(
    document_post: tuple[model.Post, model.User],  # noqa: F811
) -> None:
    import dataclasses

    from lithica import config

    post, user = document_post
    config.config["document_versions_kept"] = 1
    documents.create(post, "dummy_document", {"text": "first"}, user)
    documents.write(post, {"text": "second"}, 0, user)
    documents.write(post, {"text": "third"}, 1, user)
    db.session.commit()
    client = ApiClient(create_app())
    path = f"/post/{post.post_id}"
    assert client.get(path + "/document-version/1", user=user).status_code == 404

    def reject(data: registry.Payload) -> registry.Payload:
        raise registry.DocumentRejected("Cannot restore this data.")

    kind = dataclasses.replace(dummy.module.document_kinds[0], validate=reject)
    registry.use([dataclasses.replace(dummy.module, document_kinds=[kind])])
    response = client.post(
        path + "/document-version/0/restore", user=user, body={"version": 2}
    )
    assert response.status_code == 400
    assert response.json()["description"] == "Cannot restore this data."
    assert documents.get(post).version == 2
    assert db.session.query(model.PostDocumentVersion).count() == 2
