"""
The module system, proven end to end with the dummy module of
lithica/tests/fixtures/modules: switched on and off through the `modules`
setting, as a site would, and used through HTTP and the admin CLI.
"""

import io
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
from lithica.func import posts
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
