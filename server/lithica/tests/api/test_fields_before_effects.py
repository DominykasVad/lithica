"""An unknown field in `fields` is refused before anything is changed."""

import os

import pytest

from lithica import db, errors, model, registry
from lithica.api import (
    comment_api,
    docs_api,
    info_api,
    password_reset_api,
    pool_api,
    pool_category_api,
    post_api,
    snapshot_api,
    tag_api,
    tag_category_api,
    upload_api,
    user_api,
    user_token_api,
)
from lithica.func import posts
from lithica.func.serialization import BaseSerializer
from lithica.tests.api.http import assert_error, ok


@pytest.fixture
def data_dir(config_injector, tmpdir, tag_category_factory):
    path = str(tmpdir.mkdir("data"))
    config_injector(
        {
            "data_dir": path,
            "data_url": "http://example.com/data/",
            "secret": "test",
            "allow_broken_uploads": False,
            "delete_source_files": True,
            "thumbnails": {
                "post_width": 300,
                "post_height": 300,
                "avatar_width": 30,
                "avatar_height": 30,
            },
            "convert": {"gif": {"to_mp4": False, "to_webm": False}},
            "tag_name_regex": r"^\S+$",
            "webhooks": [],
            "privileges": {
                "posts:create:identified": model.User.RANK_REGULAR,
                "posts:edit:tags": model.User.RANK_REGULAR,
                "posts:edit:safety": model.User.RANK_REGULAR,
                "posts:view": model.User.RANK_REGULAR,
                "posts:merge": model.User.RANK_REGULAR,
                "tags:create": model.User.RANK_REGULAR,
                "uploads:use_downloader": model.User.RANK_ADMINISTRATOR,
            },
        }
    )
    db.session.add(tag_category_factory(name="default", default=True))
    db.session.flush()
    return path


@pytest.fixture
def user(user_factory):
    user = user_factory(rank=model.User.RANK_REGULAR)
    db.session.add(user)
    db.session.flush()
    return user


def _files(path):
    return sorted(
        os.path.relpath(os.path.join(root, name), path)
        for root, _dirs, names in os.walk(path)
        for name in names
    )


def _tag_names():
    db.session.expire_all()
    return sorted(name.name for name in db.session.query(model.TagName))


def test_creating_a_post_with_an_unknown_field_creates_nothing(
    client, user, data_dir, read_asset
):
    response = client.post(
        "/posts",
        user=user,
        query={"fields": "id,noSuchField"},
        body={"safety": "safe", "tags": ["fresh"]},
        files={"content": read_asset("png.png")},
    )

    body = assert_error(response, errors.ValidationError)
    assert response.status_code == 400
    assert "Invalid key: 'noSuchField'" in body["description"]
    assert db.session.query(model.Post).count() == 0
    assert _tag_names() == []
    assert _files(data_dir) == []


def test_updating_a_post_with_an_unknown_field_changes_nothing(
    client, user, data_dir, read_asset
):
    created = ok(
        client.post(
            "/posts",
            user=user,
            query={"fields": "id,version"},
            body={"safety": "safe", "tags": ["old"]},
            files={"content": read_asset("png.png")},
        )
    )
    files_before = _files(data_dir)

    response = client.put(
        f"/post/{created['id']}",
        user=user,
        query={"fields": "noSuchField"},
        body={"version": created["version"], "safety": "unsafe", "tags": ["new"]},
    )

    assert_error(response, errors.ValidationError)
    db.session.expire_all()
    post = posts.get_post_by_id(created["id"])
    assert post.version == created["version"]
    assert post.safety == model.Post.SAFETY_SAFE
    assert [tag.first_name for tag in post.tags] == ["old"]
    assert _tag_names() == ["old"]
    assert _files(data_dir) == files_before


def test_merging_posts_with_an_unknown_field_deletes_nothing(
    client, user, data_dir, read_asset
):
    first, second = (
        ok(
            client.post(
                "/posts",
                user=user,
                query={"fields": "id,version"},
                body={"safety": "safe", "tags": []},
                files={"content": read_asset(name)},
            )
        )
        for name in ("png.png", "jpeg.jpg")
    )
    files_before = _files(data_dir)

    response = client.post(
        "/post-merge",
        user=user,
        query={"fields": "noSuchField"},
        body={
            "remove": first["id"],
            "mergeTo": second["id"],
            "removeVersion": first["version"],
            "mergeToVersion": second["version"],
            "replaceContent": False,
        },
    )

    assert_error(response, errors.ValidationError)
    db.session.expire_all()
    assert db.session.query(model.Post).count() == 2
    assert _files(data_dir) == files_before


def test_a_known_field_of_a_module_is_accepted(client, user, data_dir, read_asset):
    registry.use(
        [
            registry.Module(
                name="probe",
                post_fields={"probeField": lambda post, auth_user: post.post_id},
            )
        ]
    )
    created = ok(
        client.post(
            "/posts",
            user=user,
            query={"fields": "id,probeField"},
            body={"safety": "safe", "tags": []},
            files={"content": read_asset("png.png")},
        )
    )
    assert created == {"id": created["id"], "probeField": created["id"]}
    assert "probeField" in posts.PostSerializer.field_names()


def _routes_with_fields():
    """Every route of the engine and the modules that takes `fields`, and how."""
    routers = [
        api.router
        for api in (
            comment_api,
            docs_api,
            info_api,
            password_reset_api,
            pool_api,
            pool_category_api,
            post_api,
            snapshot_api,
            tag_api,
            tag_category_api,
            upload_api,
            user_api,
            user_token_api,
        )
    ] + [module.router for module in registry.available() if module.router]
    found = {}

    def walk(dependant, route):
        for sub in dependant.dependencies:
            name = getattr(sub.call, "__name__", None)
            if name in ("checked_fields", "get_fields"):
                found.setdefault(route, set()).add(name)
            walk(sub, route)

    def visit(router):
        for route in router.routes:
            if hasattr(route, "original_router"):
                # a router included in this one (FastAPI's own wrapper)
                visit(route.original_router)
            else:
                walk(route.dependant, f"{sorted(route.methods)[0]} {route.path}")

    for router in routers:
        visit(router)
    return found


def test_every_route_with_fields_checks_them_first():
    routes = _routes_with_fields()
    # the engine's routes that answer with a resource of their own
    assert len(routes) > 40
    unchecked = [
        route for route, calls in routes.items() if "checked_fields" not in calls
    ]
    assert unchecked == []


def test_a_serializer_lists_its_fields_without_a_resource():
    for serializer in BaseSerializer.__subclasses__():
        names = serializer.field_names()
        assert names, serializer
        assert len(names) == len(set(names))
