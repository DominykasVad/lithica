"""File-less posts stay out of every file-dependent operation."""

from collections.abc import Callable
from pathlib import Path
from unittest.mock import patch

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from fastapi.routing import iter_route_contexts

from lithica import db, errors, model, registry
from lithica.app import create_app
from lithica.func import post_kinds, posts, share_links, snapshots
from lithica.tests.api.http import enabled_config, ok
from lithica.tests.conftest import ApiClient
from lithica.tests.test_migration_token_hashes import migration_db  # noqa: F401


def identity(data: registry.Payload) -> registry.Payload:
    return data


@pytest.fixture
def site(
    config_injector: Callable[..., None],
    tmp_path: Path,
    user_factory: Callable[..., model.User],
    tag_category_factory: Callable[..., model.TagCategory],
) -> tuple[ApiClient, model.User]:
    config_injector(enabled_config({"data_dir": str(tmp_path), "modules": ["cards"]}))
    registry.load_configured()
    application = create_app()
    registry.use(
        [
            *registry.modules(),
            registry.Module(
                name="probe",
                post_kinds=[registry.PostKind("document", frozenset())],
                document_kinds=[registry.DocumentKind("document", validate=identity)],
            ),
        ]
    )
    user = user_factory(rank=model.User.RANK_ADMINISTRATOR)
    db.session.add(tag_category_factory(name="default", default=True))
    db.session.add(user)
    db.session.commit()
    return ApiClient(application), user


def make(user: model.User) -> model.Post:
    post = posts.create_fileless_post("document", user)
    db.session.commit()
    return post


def test_serialization_and_counts(site: tuple[ApiClient, model.User]) -> None:
    client, user = site
    post = make(user)
    body = ok(client.get(f"/post/{post.post_id}", user=user))
    for key in (
        "type",
        "mimeType",
        "checksum",
        "checksumMD5",
        "fileSize",
        "canvasWidth",
        "canvasHeight",
        "contentUrl",
        "thumbnailUrl",
    ):
        assert body[key] is None
    assert body["listed"]
    assert post.signature is None and not post.contents
    assert ok(client.get(f"/post/{post.post_id}/content", user=user))["results"] == []
    assert posts.count_posts_without_signature() == 0
    assert posts.count_posts_without_md5_checksum() == 0
    assert posts.count_posts_to_reextract() == 0
    assert posts.count_posts_for_kind_backfill() == 0
    for backfill in (
        posts.update_all_post_signatures,
        posts.update_all_md5_checksums,
        posts.reextract_all_post_contents,
        posts.update_all_post_kinds,
    ):
        assert backfill() == (0, 0)
    with patch(
        "lithica.func.posts.files.get", side_effect=AssertionError("file access")
    ):
        posts.generate_post_thumbnail(post)
    with patch(
        "lithica.func.posts.files.delete", side_effect=AssertionError("file delete")
    ):
        snapshots.create(post, user)
        post.source = "edited"
        snapshots.modify(post, user)
        snapshots.delete(post, user)
        posts.delete(post)
        db.session.flush()


@pytest.mark.parametrize(
    "operation", [posts.update_post_content, posts.update_post_thumbnail]
)
def test_file_updates(
    site: tuple[ApiClient, model.User], operation: Callable[..., None]
) -> None:
    post = make(site[1])
    with pytest.raises(errors.ValidationError, match="This post has no file"):
        operation(post, b"file")


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("replace", [False, True])
def test_merge(
    site: tuple[ApiClient, model.User],
    post_factory: Callable[[], model.Post],
    reverse: bool,
    replace: bool,
) -> None:
    post, file = make(site[1]), post_factory()
    db.session.add(file)
    db.session.flush()
    with pytest.raises(errors.ValidationError, match="This post has no file"):
        posts.merge_posts(file if reverse else post, post if reverse else file, replace)


def test_kind_and_share(
    site: tuple[ApiClient, model.User], post_factory: Callable[[], model.Post]
) -> None:
    post = make(site[1])
    with pytest.raises(errors.ValidationError):
        post_kinds.set_kind(post, "media")
    with pytest.raises(errors.ValidationError):
        post_kinds.set_kind(post_factory(), "document")
    with pytest.raises(errors.ValidationError):
        share_links.create(post, site[1], None, None)
    for kind in ("media", "unknown"):
        with pytest.raises(errors.ValidationError):
            posts.create_fileless_post(kind, site[1])
    for kind in ("card", "lorebook"):
        assert posts.create_fileless_post(kind, site[1]).kind == kind
    assert post_kinds.derived_kind(post_factory()) == "media"


def test_walk(
    site: tuple[ApiClient, model.User], read_asset: Callable[[str], bytes]
) -> None:
    client, user = site
    known = {
        "/post/{post_id}",
        "/post/{post_id}/content",
        "/post/{post_id}/score",
        "/post/{post_id}/favorite",
        "/post/{post_id}/around",
        "/post/{post_id}/kind",
        "/post/{post_id}/typed-relations",
        "/post/{post_id}/external-ids",
        "/post/{post_id}/share-links",
        "/post/{post_id}/document",
        "/post/{post_id}/document-versions",
        "/post/{post_id}/document-version/{number}",
        "/post/{post_id}/document-version/{number}/restore",
        "/modules/cards/post/{post_id}",
        "/modules/cards/post/{post_id}/download",
        "/posts",
        "/featured-post",
        "/posts/reverse-search",
    }
    for route in iter_route_contexts(client._app.routes):
        path = getattr(route, "path", "")
        if "{post_id}" not in path and path not in {
            "/posts",
            "/featured-post",
            "/posts/reverse-search",
        }:
            continue
        assert path.rstrip("/") in known, f"Add a file-less walk case for {path}"
        for method in getattr(route, "methods", set()):
            post = make(user)
            body = {
                "version": post.version,
                "id": post.post_id,
                "kind": "media",
                "score": 1,
                "externalIds": [],
                "safety": "safe",
            }
            response = client.request(
                method,
                path.replace("{post_id}", str(post.post_id)).replace("{number}", "0"),
                user=user,
                body=body if method != "GET" else None,
                files={"content": read_asset("png.png")}
                if method == "POST" and path in {"/posts", "/posts/reverse-search"}
                else None,
            )
            assert response.status_code < 500, (method, path, response.text)


def test_fileless_migration(migration_db: tuple[sa.Engine, Config]) -> None:  # noqa: F811
    engine, settings = migration_db
    command.upgrade(settings, "head")
    post = sa.Table("post", sa.MetaData(), autoload_with=engine)
    from lithica.func import util

    with engine.begin() as conn:
        conn.execute(
            post.insert().values(
                creation_time=util.utcnow(),
                safety="safe",
                kind="document",
                listed=True,
                version=1,
            )
        )
    with pytest.raises(RuntimeError, match="without a file"):
        command.downgrade(settings, "f2a7b8c9d0e1")
    with engine.begin() as conn:
        conn.execute(post.delete())
    command.downgrade(settings, "f2a7b8c9d0e1")
    assert all(
        not col["nullable"]
        for col in sa.inspect(engine).get_columns("post")
        if col["name"] in {"type", "mime-type", "checksum"}
    )
    command.upgrade(settings, "head")


@pytest.mark.parametrize(
    "field", ["content", "thumbnail", "contentUrl", "contentToken"]
)
def test_http_replacement(site: tuple[ApiClient, model.User], field: str) -> None:
    client, user = site
    post = make(user)
    body: dict[str, object] = {"version": post.version}
    files = None
    if field in {"content", "thumbnail"}:
        files = {field: b"file"}
    else:
        body[field] = (
            "https://example.invalid/image.png"
            if field == "contentUrl"
            else "not-a-token"
        )
    with patch("lithica.func.net.download", side_effect=AssertionError("download")):
        response = client.put(
            f"/post/{post.post_id}", user=user, body=body, files=files
        )
    assert response.status_code == 400
    assert response.json()["description"] == "This post has no file."


def test_share_delivery(site: tuple[ApiClient, model.User]) -> None:
    import secrets

    from lithica.func import auth, util

    post = make(site[1])
    salt = secrets.token_bytes(32)
    token = share_links.derive_token(salt)
    db.session.add(
        model.ShareLink(
            post_id=post.post_id,
            user_id=site[1].user_id,
            salt=salt,
            token_hash=auth.hash_token(token),
            creation_time=util.utcnow(),
        )
    )
    db.session.flush()
    with pytest.raises(errors.NotFoundError):
        share_links.delivery(token)


def test_search(
    site: tuple[ApiClient, model.User], read_asset: Callable[[str], bytes]
) -> None:
    client, user = site
    post = make(user)
    image = read_asset("jpeg.jpg")
    assert posts.search_by_image_exact(image) is None
    assert posts.search_by_image(image) == []
    for token in ("image", "animation", "video", "flash", "charx"):
        assert (
            ok(client.get("/posts", user=user, query={"query": f"type:{token}"}))[
                "results"
            ]
            == []
        )
    assert post.kind == "document"


def test_invalid_document_kinds() -> None:
    invalid = [
        registry.Module("empty", post_kinds=[registry.PostKind("empty", frozenset())]),
        registry.Module(
            "wrong",
            document_kinds=[registry.DocumentKind("missing", validate=identity)],
        ),
        registry.Module(
            "large",
            post_kinds=[registry.PostKind("large", frozenset())],
            document_kinds=[
                registry.DocumentKind(
                    "large", validate=identity, max_size=registry.PAYLOAD_SIZE_CAP + 1
                )
            ],
        ),
    ]
    for module in invalid:
        with pytest.raises(errors.ConfigError):
            registry.use([module])


@pytest.mark.parametrize("mask", range(1, 7))
def test_partial_file_identity_refused(
    site: tuple[ApiClient, model.User], mask: int
) -> None:
    from sqlalchemy.exc import IntegrityError

    post = make(site[1])
    with pytest.raises(IntegrityError), db.session.begin_nested():
        for index, (name, value) in enumerate(
            (("type", "image"), ("mime_type", "image/png"), ("checksum", "hash"))
        ):
            setattr(post, name, value if mask & (1 << index) else None)
        db.session.flush()


def test_file_operations_never_derive_document_only_kind(
    site: tuple[ApiClient, model.User], read_asset: Callable[[str], bytes]
) -> None:
    client, user = site
    content = read_asset("png.png")
    post, _ = posts.create_post(content, [], user)
    db.session.commit()
    assert post.kind == "media"
    response = client.put(
        f"/post/{post.post_id}/kind",
        user=user,
        body={"version": post.version, "kind": "document"},
    )
    assert response.status_code == 400
    posts.update_post_content(post, content)
    db.session.commit()
    assert post.kind == "media"
    assert posts.reextract_all_post_contents() == (1, 0)
    assert post.kind == "media"
    assert posts.update_all_post_kinds() == (1, 0)
    assert post.kind == "media"


def test_download_and_startup_warning(site: tuple[ApiClient, model.User]) -> None:
    client, user = site
    post = make(user)
    response = client.get(f"/modules/cards/post/{post.post_id}/download", user=user)
    assert response.status_code == 404
    with patch("lithica.func.posts.logger.warning") as warning:
        posts.warn_about_pending_backfills()
    warning.assert_not_called()
