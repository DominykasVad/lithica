"""
GET /info's `acceptedTypes` against what an upload really takes: a file of
every listed type makes a post of that MIME type, every picture and video
the engine knows is listed, a module's type is listed exactly when the
module is switched on, and a file of no listed type is refused.
"""

import os

import pytest

from lithica.api import info_api
from lithica.func import mime, posts
from lithica.tests.api.http import assert_error, ok
from lithica.tests.fixtures.modules import dummy

# the site and user of the module tests: a site whose modules can change
from lithica.tests.test_dummy_module import _png, site, user  # noqa: F401

ASSETS = os.path.join(os.path.dirname(__file__), "assets")

# a file of each type the engine lists
ENGINE_FILES = {
    "image/jpeg": "jpeg.jpg",
    "image/png": "png.png",
    "image/gif": "gif.gif",
    "image/webp": "webp.webp",
    "image/bmp": "bmp.bmp",
    "image/avif": "avif.avif",
    "image/heif": "heif.heif",
    "image/heic": "heic.heic",
    "video/mp4": "mp4.mp4",
    "video/quicktime": "mov.mov",
    "video/webm": "webm.webm",
    "application/x-shockwave-flash": "flash.swf",
}


def _read(name: str) -> bytes:
    with open(os.path.join(ASSETS, name), "rb") as handle:
        return handle.read()


def _listed(client, user):  # noqa: F811
    return {
        entry["mime"][0]: entry["extensions"]
        for entry in ok(client.get("/info", user=user))["acceptedTypes"]
    }


@pytest.fixture(autouse=True)
def _no_disk_walk(monkeypatch):
    monkeypatch.setattr(info_api, "_disk_usage", info_api._DiskUsage())
    monkeypatch.setattr(info_api._DiskUsage, "_start_measuring", lambda self: None)


@pytest.fixture(autouse=True)
def _info_settings(site):  # noqa: F811
    from lithica import config

    # what the info endpoint reads besides the types
    config.config.update(
        {
            "name": "test installation",
            "contact_email": None,
            "enable_safety": True,
            "user_name_regex": "1",
            "password_regex": "2",
            "tag_category_name_regex": "3",
            "default_rank": "regular",
            "smtp": {"host": None},
        }
    )
    config.config["privileges"]["posts:view:featured"] = "regular"


def test_every_listed_engine_type_has_a_file_here():
    assert set(ENGINE_FILES) == {mime_type for mime_type, _ in mime.ACCEPTED_TYPES}


def test_an_extension_listed_first_is_the_one_a_file_is_stored_with():
    for mime_type, extensions in mime.ACCEPTED_TYPES:
        assert mime.get_extension(mime_type) == extensions[0]


def test_every_file_of_a_listed_type_is_taken(site, user):  # noqa: F811
    client = site(["dummy"])
    listed = _listed(client, user)
    files = {**ENGINE_FILES}
    for mime_type, name in files.items():
        created = ok(
            client.post(
                "/posts",
                user=user,
                body={"safety": "safe", "tags": []},
                files={"content": _read(name)},
            )
        )
        assert created["mimeType"] == mime_type, name
        assert mime_type in listed
    # the module's own type, with the extension it stores files with
    assert listed[dummy.FILE_MIME_TYPE] == [dummy.FILE_EXTENSION]
    created = ok(
        client.post(
            "/posts",
            user=user,
            body={"safety": "safe", "tags": []},
            files={"content": dummy.FILE_MAGIC + _png(shade=3)},
        )
    )
    assert created["mimeType"] == dummy.FILE_MIME_TYPE


def test_every_picture_and_video_the_engine_knows_is_listed():
    listed = {mime_type for mime_type, _ in mime.ACCEPTED_TYPES}
    for name in sorted(os.listdir(ASSETS)):
        detected = mime.get_mime_type(_read(name))
        if detected != "application/octet-stream":
            assert detected in listed, name


def test_a_module_type_is_listed_only_where_the_module_is_on(site, user):  # noqa: F811
    without = site([])
    assert dummy.FILE_MIME_TYPE not in _listed(without, user)
    # and its file is refused there, as any type not listed
    assert_error(
        without.post(
            "/posts",
            user=user,
            body={"safety": "safe", "tags": []},
            files={"content": dummy.FILE_MAGIC + _png(shade=4)},
        ),
        posts.InvalidPostContentError,
    )
    assert dummy.FILE_MIME_TYPE in _listed(site(["dummy"]), user)


def test_a_file_of_no_listed_type_is_refused(site, user):  # noqa: F811
    client = site(["dummy"])
    assert "text/plain" not in _listed(client, user)
    assert_error(
        client.post(
            "/posts",
            user=user,
            body={"safety": "safe", "tags": []},
            files={"content": _read("text.txt")},
        ),
        posts.InvalidPostContentError,
    )
