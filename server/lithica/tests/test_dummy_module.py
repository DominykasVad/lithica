"""
The module system, proven end to end with the dummy module of
lithica/tests/fixtures/modules: switched on and off through the `modules`
setting, as a site would, and used through HTTP and the admin CLI.
"""

import hashlib
import io
import os
import struct
import zlib
from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
from pathlib import Path

import pytest
from importlinter import cli
from PIL import Image, PngImagePlugin

from lithica import db, errors, model, registry
from lithica.app import create_app
from lithica.func import file_types, posts
from lithica.tests.api.http import assert_error, ok
from lithica.tests.conftest import ApiClient
from lithica.tests.fixtures.modules import dummy

SERVER_DIR = Path(__file__).resolve().parent.parent.parent
FIXTURE_PACKAGE = "lithica.tests.fixtures.modules"


def _png(texts=(), shade=0):
    """A PNG picture with the given (keyword, text) chunks; `shade` tells them apart."""
    image = Image.new("RGB", (64, 64), (shade, 40, 200))
    for x in range(0, 64, 4):
        image.putpixel((x, (x * 7 + shade) % 64), (255, 255, shade))
    info = PngImagePlugin.PngInfo()
    for keyword, text in texts:
        info.add_text(keyword, text)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", pnginfo=info)
    return buffer.getvalue()


@pytest.fixture(scope="module")
def admin():
    # lithica-admin is a script without the .py suffix
    path = str(SERVER_DIR / "lithica-admin")
    loader = SourceFileLoader("lithica_admin", path)
    spec = spec_from_loader("lithica_admin", loader)
    assert spec
    module = module_from_spec(spec)
    loader.exec_module(module)
    return module


@pytest.fixture
def site(config_injector, tmpdir, monkeypatch, tag_category_factory, user_factory):
    """
    A site whose `modules` setting the test can change. Returns a function
    that sets it and starts the application anew, as a restart would.
    """
    monkeypatch.setattr(registry, "MODULE_PACKAGE", FIXTURE_PACKAGE)
    settings = {
        "modules": [],
        "data_dir": str(tmpdir.mkdir("data")),
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
            "posts:list": model.User.RANK_REGULAR,
            "posts:view": model.User.RANK_REGULAR,
            "posts:view:content:private": model.User.RANK_MODERATOR,
            "uploads:use_downloader": model.User.RANK_POWER,
            "posts:reverse_search": model.User.RANK_REGULAR,
            "posts:edit:content": model.User.RANK_REGULAR,
            "posts:delete": model.User.RANK_REGULAR,
            "tags:create": model.User.RANK_REGULAR,
            "users:edit:any:email": model.User.RANK_MODERATOR,
        },
    }
    config_injector(settings)
    db.session.add_all(
        [
            tag_category_factory(name="default", default=True),
            tag_category_factory(name="meta"),
        ]
    )
    db.session.flush()

    def start(modules):
        settings["modules"] = modules
        registry.load_configured()
        return ApiClient(create_app())

    return start


@pytest.fixture
def user(user_factory):
    user = user_factory(rank=model.User.RANK_REGULAR)
    db.session.add(user)
    db.session.flush()
    return user


def _upload(client, user, content, tags=()):
    return ok(
        client.post(
            "/posts",
            user=user,
            body={"safety": "safe", "tags": list(tags)},
            files={"content": content},
        )
    )


def _search(client, user, query):
    found = ok(client.get("/posts", user=user, query={"query": query, "fields": "id"}))
    return sorted(post["id"] for post in found["results"])


def _content(client, user, post_id):
    return [
        (entry["kind"], entry["content"])
        for entry in ok(client.get("/post/%d/content" % post_id, user=user))["results"]
    ]


CAT = [("Title", "A cat on a mat"), ("Tag", "from_file"), ("Author", "somebody")]


def test_site_without_the_module(site, user, admin):
    client = site([])
    created = _upload(client, user, _png(CAT), tags=["by_hand"])

    assert created["contentKinds"] == []
    assert "dummyKeywords" not in created
    assert [tag["names"][0] for tag in created["tags"]] == ["by_hand"]
    assert _content(client, user, created["id"]) == []
    assert db.session.query(model.PostContent).count() == 0
    assert client.get("/modules/dummy/stats", user=user).status_code == 404
    assert_error(
        client.get("/posts", user=user, query={"query": "dummy-text:cat"}),
        errors.SearchError,
    )
    assert_error(
        client.get("/posts", user=user, query={"fields": "dummyKeywords"}),
        errors.ValidationError,
    )
    with pytest.raises(SystemExit):
        admin.main(["dummy-count"])


def test_info_lists_the_module(site, user, monkeypatch):
    from lithica import config
    from lithica.api import info_api

    # what the info endpoint reads besides the modules
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
    config.config["privileges"]["posts:view:featured"] = model.User.RANK_POWER
    monkeypatch.setattr(info_api, "_disk_usage", info_api._DiskUsage())
    monkeypatch.setattr(info_api._DiskUsage, "_start_measuring", lambda self: None)
    assert ok(site([]).get("/info", user=user))["modules"] == []
    assert ok(site(["dummy"]).get("/info", user=user))["modules"] == ["dummy"]


def test_extraction_on_upload(site, user):
    client = site(["dummy"])
    created = _upload(client, user, _png(CAT), tags=["by_hand"])

    assert created["contentKinds"] == ["dummy_v1"]
    assert _content(client, user, created["id"]) == [
        ("dummy_v1", {"keyword": "Title", "text": "A cat on a mat"}),
        ("dummy_v1", {"keyword": "Tag", "text": "from_file"}),
        ("dummy_v1", {"keyword": "Author", "text": "somebody"}),
    ]
    # the post field the module adds
    assert created["dummyKeywords"] == ["Author", "Tag", "Title"]
    # the automatic tags, in the category the module names
    assert {tag["names"][0]: tag["category"] for tag in created["tags"]} == {
        "by_hand": "default",
        "dummy_text": "meta",
        "from_file": "meta",
    }


def test_upload_of_a_picture_without_text(site, user):
    client = site(["dummy"])
    created = _upload(client, user, _png())
    assert created["contentKinds"] == []
    assert created["dummyKeywords"] == []
    assert created["tags"] == []


def test_search_token(site, user):
    client = site(["dummy"])
    cat = _upload(client, user, _png(CAT, shade=1), tags=["animal"])["id"]
    dog = _upload(
        client, user, _png([("Title", "A dog"), ("Note", "not a CAT")], shade=2)
    )["id"]
    plain = _upload(client, user, _png(shade=3), tags=["animal"])["id"]

    assert _search(client, user, "dummy-text:*cat*") == [cat, dog]
    assert _search(client, user, "dummy-text:a*mat") == [cat]
    assert _search(client, user, "dummy-text:somebody") == [cat]
    assert _search(client, user, "dummy-text:nothing") == []
    assert _search(client, user, "-dummy-text:*cat*") == [plain]
    # together with the engine's own tokens
    assert _search(client, user, "animal -dummy-text:*cat*") == [plain]
    assert _search(client, user, "dummy-text:*dog* type:image") == [dog]
    assert _search(client, user, "dummy-text:*dog*,*mat") == [cat, dog]


def test_search_token_is_not_fooled_by_other_kinds(site, user):
    client = site(["dummy"])
    created = _upload(client, user, _png(shade=4))
    post = posts.get_post_by_id(created["id"])
    post.contents.append(
        model.PostContent(
            kind="another_v1",
            schema_version=1,
            payload={"text": "needle"},
            extracted_at=post.creation_time,
        )
    )
    db.session.commit()
    assert _search(client, user, "dummy-text:needle") == []


def test_route(site, user, user_factory):
    client = site(["dummy"])
    assert ok(client.get("/modules/dummy/stats", user=user)) == {
        "posts": 0,
        "chunks": 0,
    }
    _upload(client, user, _png(CAT, shade=1))
    _upload(client, user, _png([("Title", "another")], shade=2))
    _upload(client, user, _png(shade=3))
    assert ok(client.get("/modules/dummy/stats", user=user)) == {
        "posts": 2,
        "chunks": 4,
    }
    assert ok(client.get("/modules/dummy/stats/", user=user))["posts"] == 2
    # the module's route has the engine's authentication and privileges
    anonymous = user_factory(rank=model.User.RANK_ANONYMOUS)
    assert_error(client.get("/modules/dummy/stats", user=anonymous), errors.AuthError)
    assert client.post("/modules/dummy/stats", user=user).status_code == 405


def test_switching_the_module_on_and_reextracting(site, user, admin, capsys):
    client = site([])
    cat = _upload(client, user, _png(CAT, shade=1))["id"]
    plain = _upload(client, user, _png(shade=2))["id"]

    # switched on: the posts that are there have not been read yet
    client = site(["dummy"])
    assert _search(client, user, "dummy-text:*cat*") == []
    assert ok(client.get("/post/%d" % cat, user=user))["contentKinds"] == []

    assert admin.main(["reextract"]) == 0
    assert "reextract: 2 done, 0 failed" in capsys.readouterr().out

    assert _search(client, user, "dummy-text:*cat*") == [cat]
    post = ok(client.get("/post/%d" % cat, user=user))
    assert post["contentKinds"] == ["dummy_v1"]
    assert post["dummyKeywords"] == ["Author", "Tag", "Title"]
    # re-extraction reads; it does not tag
    assert post["tags"] == []
    assert _content(client, user, plain) == []

    # again, and for the one kind: nothing changes
    before = _content(client, user, cat)
    assert admin.main(["reextract", "--kind", "dummy_v1"]) == 0
    assert _content(client, user, cat) == before
    assert db.session.query(model.PostContent).count() == 3


def test_switching_the_module_off_again(site, user, admin):
    client = site(["dummy"])
    cat = _upload(client, user, _png(CAT))["id"]

    client = site([])
    post = ok(client.get("/post/%d" % cat, user=user))
    assert post["contentKinds"] == []
    assert "dummyKeywords" not in post
    assert _content(client, user, cat) == []
    assert client.get("/modules/dummy/stats", user=user).status_code == 404
    assert_error(
        client.get("/posts", user=user, query={"query": "dummy-text:cat"}),
        errors.SearchError,
    )
    # the tags it made are ordinary tags and stay
    assert {tag["names"][0] for tag in post["tags"]} == {"dummy_text", "from_file"}
    # and so does what it extracted, for the day it is switched on again
    assert db.session.query(model.PostContent).count() == 3
    assert admin.main(["reextract"]) == 0
    assert db.session.query(model.PostContent).count() == 3

    client = site(["dummy"])
    assert _search(client, user, "dummy-text:*cat*") == [cat]


def test_admin_command(site, user, admin, capsys):
    client = site(["dummy"])
    _upload(client, user, _png(CAT))
    assert admin.main(["dummy-count"]) == 0
    assert capsys.readouterr().out == "dummy: 3 text chunks\n"


def _chunk(chunk_type, data):
    return (
        struct.pack(">I", len(data))
        + chunk_type
        + data
        + struct.pack(">I", zlib.crc32(chunk_type + data))
    )


def _extracted(data):
    return [
        (content.payload["keyword"], content.payload["text"])
        for content in dummy.extract("image/png", io.BytesIO(data))
    ]


def test_extractor_reads_real_files(read_asset):
    assert _extracted(_png(CAT)) == CAT
    assert _extracted(_png()) == []
    assert _extracted(read_asset("png.png")) == []


@pytest.mark.parametrize(
    "data,expected",
    [
        (b"", []),
        (b"GIF89a", []),
        (dummy.PNG_SIGNATURE, []),
        (dummy.PNG_SIGNATURE + b"\x00\x00", []),
        # the chunk says it is longer than the file
        (
            dummy.PNG_SIGNATURE + struct.pack(">I4s", 1000, b"tEXt") + b"Title\x00cut",
            [],
        ),
        # no separator between keyword and text
        (dummy.PNG_SIGNATURE + _chunk(b"tEXt", b"just a keyword"), []),
        # too large to be worth reading; what follows is still read
        (
            dummy.PNG_SIGNATURE
            + _chunk(b"tEXt", b"Big\x00" + b"x" * dummy.MAX_TEXT_SIZE)
            + _chunk(b"tEXt", b"Small\x00kept"),
            [("Small", "kept")],
        ),
        # a NUL in the text cannot be stored and becomes a space
        (
            dummy.PNG_SIGNATURE + _chunk(b"tEXt", b"Key\x00a\x00b"),
            [("Key", "a b")],
        ),
        # bytes that are not ASCII are Latin-1, never an error
        (
            dummy.PNG_SIGNATURE + _chunk(b"tEXt", b"Key\x00caf\xe9 \xff"),
            [("Key", "caf\xe9 \xff")],
        ),
        # nothing after the end marker is read
        (
            dummy.PNG_SIGNATURE
            + _chunk(b"tEXt", b"Before\x001")
            + _chunk(b"IEND", b"")
            + _chunk(b"tEXt", b"After\x002"),
            [("Before", "1")],
        ),
    ],
)
def test_extractor_on_files_it_should_not_trust(data, expected):
    assert _extracted(data) == expected


def test_hostile_text_is_stored_and_returned_as_text(site, user):
    client = site(["dummy"])
    script = "<script>alert(1)</script>"
    created = _upload(
        client,
        user,
        _png(
            [("Title", script), ("Tag", "has space"), ("Tag", "'; DROP TABLE post;--")]
        ),
    )
    shown = _content(client, user, created["id"])
    assert shown[0] == ("dummy_v1", {"keyword": "Title", "text": script})
    # a text that is not a tag name on this site is not made a tag
    assert {tag["names"][0] for tag in created["tags"]} == {"dummy_text"}
    assert _search(client, user, "dummy-text:*script*") == [created["id"]]
    assert db.session.query(model.Post).count() == 1


def _middle_colour(image) -> tuple[int, int, int]:
    colour = image.convert("RGB").getpixel((image.width // 2, image.height // 2))
    assert isinstance(colour, tuple)
    return colour[0], colour[1], colour[2]


def _stored(url):
    """The stored file behind a content or thumbnail URL of the test site."""
    from lithica import config

    assert url.startswith(config.config["data_url"])
    relative = url[len(config.config["data_url"]) :]
    with open(os.path.join(config.config["data_dir"], relative), "rb") as handle:
        return handle.read()


def _refused_upload(client, user, content, error_class=posts.InvalidPostContentError):
    return assert_error(
        client.post(
            "/posts", user=user, body={"safety": "safe"}, files={"content": content}
        ),
        error_class,
    )


def test_upload_of_a_file_of_the_module(site, user):
    client = site(["dummy"])
    picture = _png(shade=5)
    uploaded = dummy.FILE_MAGIC + picture
    created = _upload(client, user, uploaded, tags=["by_hand"])

    assert created["type"] == "dummyfile"
    assert created["mimeType"] == "application/x-lithica-dummy"
    assert created["contentUrl"].endswith(".dummy")
    assert created["fileSize"] == len(uploaded)
    assert created["checksum"] == hashlib.sha1(uploaded).hexdigest()
    assert created["checksumMD5"] == hashlib.md5(uploaded).hexdigest()
    # not a picture, and nothing that plays
    assert created["canvasWidth"] is None and created["canvasHeight"] is None
    assert created["flags"] == []
    # the stored file is the upload, byte for byte
    assert _stored(created["contentUrl"]) == uploaded
    # its thumbnail is made of the picture the module took out of it
    thumbnail = Image.open(io.BytesIO(_stored(created["thumbnailUrl"])))
    assert thumbnail.format == "JPEG"
    assert thumbnail.size == (300, 300)
    red, green, blue = _middle_colour(thumbnail)
    assert red < 40 and green < 80 and blue > 160
    # extractors and auto-tags work on a module's type as on the engine's
    assert _content(client, user, created["id"]) == [
        ("dummy_v1", {"keyword": "Picture", "text": "%d bytes" % len(picture)})
    ]
    assert sorted(tag["names"][0] for tag in created["tags"]) == [
        "by_hand",
        "dummy_text",
    ]
    # and it is a post like any other
    assert ok(client.get("/post/%d" % created["id"], user=user))["type"] == "dummyfile"


@pytest.mark.parametrize(
    "rest", [b"", b"not a picture at all", b"\x89PNG\r\n\x1a\n and then nothing"]
)
def test_file_without_a_usable_picture_gets_the_placeholder(site, user, rest):
    client = site(["dummy"])
    uploaded = dummy.FILE_MAGIC + rest
    created = _upload(client, user, uploaded)
    assert created["type"] == "dummyfile"
    assert _stored(created["contentUrl"]) == uploaded
    assert _stored(created["thumbnailUrl"]) == posts.EMPTY_PIXEL
    # no picture, no part in the similar-image search
    assert db.session.query(model.PostSignature).count() == 0


def test_similar_image_search_works_on_the_thumbnail(site, user):
    client = site(["dummy"])
    picture = _png(shade=6)
    with_picture = _upload(client, user, dummy.FILE_MAGIC + picture)["id"]
    _upload(client, user, dummy.FILE_MAGIC)
    assert db.session.query(model.PostSignature).count() == 1

    found = ok(
        client.post("/posts/reverse-search", user=user, files={"content": picture})
    )
    # the picture alone is not the file: no exact match, a similar one
    assert found["exactPost"] is None
    assert [hit["post"]["id"] for hit in found["similarPosts"]] == [with_picture]


def test_search_by_the_type_of_the_module(site, user):
    client = site(["dummy"])
    picture = _upload(client, user, _png(shade=1))["id"]
    file = _upload(client, user, dummy.FILE_MAGIC)["id"]
    assert _search(client, user, "type:dummyfile") == [file]
    assert _search(client, user, "-type:dummyfile") == [picture]
    assert _search(client, user, "type:image") == [picture]
    assert _search(client, user, "type:image,dummyfile") == [picture, file]


def test_file_of_the_module_is_refused_without_the_module(site, user):
    client = site([])
    refused = _refused_upload(client, user, dummy.FILE_MAGIC + _png())
    assert refused["description"] == "Unhandled file type: 'application/octet-stream'"
    assert db.session.query(model.Post).count() == 0
    assert_error(
        client.get("/posts", user=user, query={"query": "type:dummyfile"}),
        errors.SearchError,
    )


def test_file_nobody_knows_is_refused_with_the_module_too(site, user):
    client = site(["dummy"])
    refused = _refused_upload(client, user, b"LITHICA-DUMM\nnot quite")
    assert refused["description"] == "Unhandled file type: 'application/octet-stream'"
    refused = _refused_upload(client, user, b"PK\x03\x04 some archive")
    assert refused["description"] == "Unhandled file type: 'application/octet-stream'"


def test_module_refuses_a_file_of_its_type_with_its_reason(site, user):
    client = site(["dummy"])
    refused = _refused_upload(client, user, dummy.FILE_MAGIC + b"FORBIDDEN stuff")
    assert refused["description"] == "A dummy file must not start with FORBIDDEN."
    assert db.session.query(model.Post).count() == 0


def test_replacing_a_picture_with_a_file_of_the_module_and_back(site, user):
    client = site(["dummy"])
    created = _upload(client, user, _png(CAT, shade=7))
    assert db.session.query(model.PostSignature).count() == 1

    def replace(version, content):
        return ok(
            client.put(
                "/post/%d" % created["id"],
                user=user,
                body={"version": version},
                files={"content": content},
            )
        )

    # to a file without a picture: the signature of the old picture goes
    replaced = replace(created["version"], dummy.FILE_MAGIC)
    assert replaced["type"] == "dummyfile"
    assert replaced["canvasWidth"] is None
    assert _stored(replaced["contentUrl"]) == dummy.FILE_MAGIC
    assert _stored(replaced["thumbnailUrl"]) == posts.EMPTY_PIXEL
    assert db.session.query(model.PostSignature).count() == 0

    # and back to a picture
    picture = _png(shade=8)
    replaced = replace(replaced["version"], picture)
    assert replaced["type"] == "image"
    assert replaced["mimeType"] == "image/png"
    assert replaced["canvasWidth"] == 64
    assert _stored(replaced["contentUrl"]) == picture
    assert db.session.query(model.PostSignature).count() == 1


def test_custom_thumbnail_wins_over_the_picture_of_the_module(site, user):
    client = site(["dummy"])
    created = ok(
        client.post(
            "/posts",
            user=user,
            body={"safety": "safe"},
            files={
                "content": dummy.FILE_MAGIC + _png(shade=5),
                "thumbnail": _plain_png((200, 30, 30)),
            },
        )
    )
    thumbnail = Image.open(io.BytesIO(_stored(created["thumbnailUrl"])))
    red, _green, blue = _middle_colour(thumbnail)
    assert red > 160 and blue < 80


def _plain_png(colour):
    buffer = io.BytesIO()
    Image.new("RGB", (64, 64), colour).save(buffer, format="PNG")
    return buffer.getvalue()


def _files_in(folder):
    from lithica import config

    path = os.path.join(config.config["data_dir"], folder)
    return sorted(name for name in os.listdir(path) if "." in name)


def test_switching_the_module_off_keeps_its_posts(site, user, admin):
    client = site(["dummy"])
    uploaded = dummy.FILE_MAGIC + _png(shade=5)
    created = _upload(client, user, uploaded)
    assert created["contentUrl"].endswith(".dummy")
    stored_as = posts.get_post_content_path(posts.get_post_by_id(created["id"]))
    assert stored_as.endswith(".dummy")

    client = site([])
    # the post is still there and says what it is
    post = ok(client.get("/post/%d" % created["id"], user=user))
    assert post["type"] == "dummyfile"
    assert post["mimeType"] == "application/x-lithica-dummy"
    assert _search(client, user, "") == [created["id"]]
    # and its file is where it was: the name of a stored file does not
    # change with the settings
    assert post["contentUrl"] == created["contentUrl"]
    assert posts.get_post_content_path(posts.get_post_by_id(created["id"])) == stored_as
    assert _stored(post["contentUrl"]) == uploaded
    # what only a loaded module does is off
    _refused_upload(client, user, dummy.FILE_MAGIC)
    assert_error(
        client.get("/posts", user=user, query={"query": "type:dummyfile"}),
        errors.SearchError,
    )

    # with the module back, everything about it is as before
    client = site(["dummy"])
    post = ok(client.get("/post/%d" % created["id"], user=user))
    assert post["contentUrl"] == created["contentUrl"]
    assert posts.get_post_content_path(posts.get_post_by_id(created["id"])) == stored_as
    assert _search(client, user, "type:dummyfile") == [created["id"]]


def test_deleting_a_post_of_a_switched_off_module_removes_its_file(site, user):
    client = site(["dummy"])
    created = _upload(client, user, dummy.FILE_MAGIC + _png(shade=5))
    assert len(_files_in("posts")) == 1 and _files_in("posts")[0].endswith(".dummy")
    assert len(_files_in("generated-thumbnails")) == 1

    client = site([])
    ok(
        client.delete(
            "/post/%d" % created["id"], user=user, body={"version": created["version"]}
        )
    )
    db.session.flush()
    assert db.session.query(model.Post).count() == 0
    # the real file went with the post: nothing is orphaned
    assert _files_in("posts") == []
    assert _files_in("generated-thumbnails") == []


def test_extension_of_a_module_is_known_without_loading_it(site):
    site([])
    assert registry.modules() == ()
    assert file_types.get_extension("application/x-lithica-dummy") == "dummy"
    # asking did not switch anything on
    assert registry.modules() == ()
    assert registry.file_types() == []
    assert registry.file_type_for("application/x-lithica-dummy") is None


def test_mime_type_no_module_knows_is_stored_as_dat(site, post_factory):
    site(["dummy"])
    assert file_types.get_extension("application/x-nobody") is None
    post = post_factory()
    post.mime_type = "application/x-nobody"
    db.session.add(post)
    db.session.flush()
    assert posts.get_post_content_path(post).endswith(".dat")
    assert posts.get_post_content_url(post).endswith(".dat")
    # and the engine's own types are the engine's to name
    assert file_types.get_extension("image/png") == "png"


def test_modules_there_are_are_read_once(site, monkeypatch):
    site([])
    calls = []
    real = registry.available

    def counting():
        calls.append(1)
        return real()

    monkeypatch.setattr(registry, "available", counting)
    for _ in range(3):
        assert file_types.get_extension("application/x-lithica-dummy") == "dummy"
        assert file_types.get_extension("application/x-nobody") is None
    assert len(calls) == 1


def test_broken_module_in_the_code_base_does_not_break_the_lookup(
    site, monkeypatch, caplog
):
    site([])

    def broken():
        raise ImportError("a module that does not import")

    monkeypatch.setattr(registry, "available", broken)
    assert file_types.get_extension("application/x-lithica-dummy") is None
    assert "Could not read the file types of the modules" in caplog.text
    # the loaded modules are still asked
    site(["dummy"])
    assert file_types.get_extension("application/x-lithica-dummy") == "dummy"


def _module_with(detect, thumbnail=None, name="probe", post_type="probefile"):
    return registry.Module(
        name=name,
        file_types=[
            registry.FileType(
                post_type=post_type,
                mime_type="application/x-%s" % post_type,
                extension=post_type,
                detect=detect,
                thumbnail=thumbnail,
            )
        ],
    )


def _site_with(site, modules):
    site([])
    registry.use(modules)
    return ApiClient(create_app())


def test_engine_looks_at_a_file_before_any_module(site, user, read_asset):
    asked = []

    def greedy(head, handle):
        asked.append(head)
        return True

    client = _site_with(site, [_module_with(greedy)])
    # every file the engine knows stays the engine's, whatever a module says
    assert _upload(client, user, _png(shade=1))["type"] == "image"
    assert _upload(client, user, read_asset("jpeg.jpg"))["type"] == "image"
    assert _upload(client, user, read_asset("gif-animated.gif"))["type"] == "animation"
    assert asked == []
    # and what the engine does not know is shown to the module, from its start
    unknown = b"something else" * 100
    created = _upload(client, user, unknown)
    assert created["type"] == "probefile"
    assert created["contentUrl"].endswith(".probefile")
    assert asked == [unknown[:512]]


def test_detector_is_given_the_file_from_its_start(site, user):
    seen = []

    def reading(head, handle):
        seen.append((handle.tell(), handle.read()))
        return False

    def accepting(head, handle):
        seen.append((handle.tell(), handle.read()))
        return True

    client = _site_with(
        site,
        [
            _module_with(reading, name="first", post_type="firstfile"),
            _module_with(accepting, name="second", post_type="secondfile"),
        ],
    )
    created = _upload(client, user, b"unknown bytes")
    # the first module to say yes has it, in the order of the configuration
    assert created["type"] == "secondfile"
    assert seen == [(0, b"unknown bytes"), (0, b"unknown bytes")]


@pytest.mark.parametrize("answer", [None, 1, "yes", [True]])
def test_only_a_plain_yes_of_a_detector_counts(site, user, answer):
    client = _site_with(site, [_module_with(lambda head, handle: answer)])
    _refused_upload(client, user, b"unknown bytes")


def test_failing_detector_counts_as_no(site, user, caplog):
    def failing(head, handle):
        raise RuntimeError("secret words from the file")

    client = _site_with(
        site,
        [
            _module_with(failing, name="first", post_type="firstfile"),
            _module_with(lambda head, handle: True, name="second", post_type="second"),
        ],
    )
    assert _upload(client, user, b"unknown bytes")["type"] == "second"
    assert "The detector of module 'first' for 'firstfile' files failed" in caplog.text

    client = _site_with(site, [_module_with(failing)])
    refused = _refused_upload(client, user, b"other unknown bytes")
    assert refused["description"] == "Unhandled file type: 'application/octet-stream'"


@pytest.mark.parametrize(
    "thumbnail",
    [
        lambda handle: None,
        lambda handle: "a string",
        lambda handle: b"",
        lambda handle: b"not a picture",
        lambda handle: (_ for _ in ()).throw(RuntimeError("broken")),
        # a video is not a picture, however well the engine knows it
        lambda handle: b"\x00\x00\x00\x18ftypmp42 and so on",
    ],
)
def test_thumbnail_hook_that_gives_no_picture_means_the_placeholder(
    site, user, thumbnail
):
    client = _site_with(site, [_module_with(lambda head, handle: True, thumbnail)])
    created = _upload(client, user, b"unknown bytes")
    assert created["type"] == "probefile"
    assert _stored(created["thumbnailUrl"]) == posts.EMPTY_PIXEL
    assert db.session.query(model.PostSignature).count() == 0


def test_thumbnail_larger_than_the_limit_means_the_placeholder(site, user, monkeypatch):
    picture = _png(shade=3)
    monkeypatch.setattr(file_types, "MAX_THUMBNAIL_SIZE", len(picture) - 1)
    client = _site_with(
        site, [_module_with(lambda head, handle: True, lambda handle: picture)]
    )
    created = _upload(client, user, b"unknown bytes")
    assert _stored(created["thumbnailUrl"]) == posts.EMPTY_PIXEL

    monkeypatch.setattr(file_types, "MAX_THUMBNAIL_SIZE", len(picture))
    created = _upload(client, user, b"other unknown bytes")
    assert _stored(created["thumbnailUrl"]) != posts.EMPTY_PIXEL


def test_file_without_a_thumbnail_hook_gets_the_placeholder(site, user):
    client = _site_with(site, [_module_with(lambda head, handle: True)])
    created = _upload(client, user, b"unknown bytes")
    assert _stored(created["thumbnailUrl"]) == posts.EMPTY_PIXEL
    assert _stored(created["contentUrl"]) == b"unknown bytes"


def test_thumbnails_of_module_files_can_be_regenerated(site, user, admin):
    client = site(["dummy"])
    created = _upload(client, user, dummy.FILE_MAGIC + _png(shade=5))
    before = _stored(created["thumbnailUrl"])
    from lithica import config

    path = os.path.join(
        config.config["data_dir"],
        created["thumbnailUrl"][len(config.config["data_url"]) :],
    )
    os.remove(path)
    admin.regenerate_thumbnails()
    assert _stored(created["thumbnailUrl"]) == before


def test_proof_module_keeps_to_the_import_boundary(tmp_path, capsys):
    # the same two rules as for lithica.modules, for the package the dummy
    # module lives in, and one more: the engine does not know the tests
    config = tmp_path / "boundary.toml"
    config.write_text(
        """
[tool.importlinter]
root_package = "lithica"

[[tool.importlinter.contracts]]
name = "fixture modules do not import each other"
type = "independence"
modules = ["lithica.tests.fixtures.modules.*"]

[[tool.importlinter.contracts]]
name = "fixture modules do not import real modules"
type = "forbidden"
source_modules = ["lithica.tests.fixtures.modules"]
forbidden_modules = ["lithica.modules"]

[[tool.importlinter.contracts]]
name = "the engine does not import the tests"
type = "forbidden"
source_modules = [%s]
forbidden_modules = ["lithica.tests"]
"""
        % ", ".join('"%s"' % part for part in _engine_parts())
    )
    status = cli.lint_imports(config_filename=str(config), no_cache=True)
    assert status == 0, capsys.readouterr().out


def _engine_parts():
    import tomllib

    with open(SERVER_DIR / "pyproject.toml", "rb") as handle:
        contracts = tomllib.load(handle)["tool"]["importlinter"]["contracts"]
    return contracts[0]["source_modules"]
