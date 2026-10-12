"""The cards module: CHARX files and the safety of reading archives (PLAN.md 4.5)."""

import base64
import io
import json
import os
import struct
import zipfile

import pytest
from PIL import Image

from lithica import config, db, errors, model, registry
from lithica.func import posts
from lithica.modules import cards as cards_module
from lithica.modules.cards import charx
from lithica.tests.api.http import assert_error, ok
from lithica.tests.modules import cards

MEGABYTE = 1024 * 1024


def _upload(client, user, content):
    return ok(
        client.post(
            "/posts", user=user, body={"safety": "safe"}, files={"content": content}
        )
    )


def _refused(client, user, content):
    refused = assert_error(
        client.post(
            "/posts", user=user, body={"safety": "safe"}, files={"content": content}
        ),
        posts.InvalidPostContentError,
    )
    assert refused["title"] and refused["name"] == "InvalidPostContentError"
    assert db.session.query(model.Post).count() == 0
    return refused["description"]


UNKNOWN = "Unhandled file type: 'application/octet-stream'"


def _stored(url):
    assert url.startswith(config.config["data_url"])
    relative = url[len(config.config["data_url"]) :]
    with open(os.path.join(config.config["data_dir"], relative), "rb") as handle:
        return handle.read()


def _content(client, user, post_id):
    return ok(client.get("/post/%d/content" % post_id, user=user))["results"]


def _detect(data):
    return cards_module.detect_charx(data[:512], io.BytesIO(data))


def _rejected(data):
    with pytest.raises(registry.FileRejected) as refusal:
        _detect(data)
    return str(refusal.value)


def _thumbnail(data):
    return cards_module.charx_thumbnail(io.BytesIO(data))


def _patch_entry(data, name, flags=None, size=None):
    """
    Rewrite what the archive says about an entry, in its local header and
    in the table of contents: the flags, or the uncompressed size.
    """
    patched = bytearray(data)
    encoded = name.encode()
    for signature, flags_at, size_at, name_at in [
        (b"PK\x03\x04", 6, 22, 30),
        (b"PK\x01\x02", 8, 24, 46),
    ]:
        position = 0
        while True:
            position = data.find(signature, position)
            if position < 0:
                break
            if data[position + name_at : position + name_at + len(encoded)] == encoded:
                if flags is not None:
                    struct.pack_into("<H", patched, position + flags_at, flags)
                if size is not None:
                    struct.pack_into("<I", patched, position + size_at, size)
            position += 4
    return bytes(patched)


# a CHARX file as a post


def test_module_registers_the_file_type():
    registry.load(["cards"])
    ((_module, file_type),) = registry.file_types()
    assert file_type.post_type == "charx"
    assert file_type.mime_type == "application/x-charx"
    assert file_type.extension == "charx"
    assert len(file_type.mime_type) <= 32


def test_upload_with_an_icon(site, user):
    client = site(["cards"])
    icon = cards.picture(shade=20)
    card = cards.charx_card()
    uploaded = cards.charx(card, icon, **{"assets/other/readme.txt": b"hello"})
    created = _upload(client, user, uploaded)

    assert created["type"] == "charx"
    assert created["mimeType"] == "application/x-charx"
    assert created["contentUrl"].endswith(".charx")
    assert created["fileSize"] == len(uploaded)
    assert created["canvasWidth"] is None and created["flags"] == []
    assert created["contentKinds"] == ["card_v3"]
    # downloads are the upload, byte for byte
    assert _stored(created["contentUrl"]) == uploaded
    # the thumbnail is the card's main icon
    thumbnail = Image.open(io.BytesIO(_stored(created["thumbnailUrl"])))
    assert thumbnail.format == "JPEG" and thumbnail.size == (300, 300)
    colour = thumbnail.convert("RGB").getpixel((150, 150))
    assert isinstance(colour, tuple)
    red, green, blue = colour[0], colour[1], colour[2]
    assert red < 60 and 60 < green < 120 and blue > 130
    # and the card is its content, with the same rules as for a picture
    (content,) = _content(client, user, created["id"])
    assert content["kind"] == "card_v3"
    assert content["content"] == {
        "format": "charx",
        "chunk": None,
        "card": card,
        "assets": [
            {"path": cards.ICON_PATH, "size": len(icon)},
            {"path": "assets/other/readme.txt", "size": 5},
        ],
    }
    # the icon makes it findable by picture
    assert db.session.query(model.PostSignature).count() == 1


def test_upload_without_an_icon_gets_the_placeholder(site, user):
    client = site(["cards"])
    uploaded = cards.charx()
    created = _upload(client, user, uploaded)
    assert created["type"] == "charx"
    assert created["contentKinds"] == ["card_v3"]
    assert _stored(created["contentUrl"]) == uploaded
    assert _stored(created["thumbnailUrl"]) == posts.EMPTY_PIXEL
    assert db.session.query(model.PostSignature).count() == 0


def test_stored_archive_compression_is_accepted(site, user):
    client = site(["cards"])
    content = {"card.json": json.dumps(cards.charx_card(None)).encode()}
    uploaded = cards.archive(content, zipfile.ZIP_STORED)
    assert _upload(client, user, uploaded)["type"] == "charx"


def test_embedded_data_is_taken_out_of_the_card(site, user):
    client = site(["cards"])
    uri = "data:image/png;base64," + base64.b64encode(b"\x89" * 5000).decode()
    card = cards.charx_card(None, extensions={"app": {"portrait": uri}})
    created = _upload(client, user, cards.charx(card))
    stored = _content(client, user, created["id"])[0]["content"]["card"]
    assert stored["data"]["extensions"]["app"]["portrait"] == {
        "embedded": {"type": "image/png", "name": "portrait", "size": 5000}
    }


def test_oversized_card_refuses_the_upload(site, user, monkeypatch):
    client = site(["cards"])
    monkeypatch.setattr(cards_module, "MAX_PAYLOAD_SIZE", 2000)
    data = cards.charx(cards.charx_card(None, description="x" * 3000))
    assert _refused(client, user, data).startswith("The character card is larger than")
    # never a charx post without its card
    assert db.session.query(model.Post).count() == 0
    with pytest.raises(registry.FileRejected):
        list(cards_module.extract_charx("application/x-charx", io.BytesIO(data)))


def test_without_the_module_a_charx_file_is_refused(site, user):
    client = site([])
    assert _refused(client, user, cards.charx(icon=cards.picture())) == UNKNOWN


def test_search_by_type(site, user):
    client = site(["cards"])
    file = _upload(client, user, cards.charx())["id"]
    picture = _upload(client, user, cards.png_card(cards.v2_card()))["id"]
    found = ok(client.get("/posts", user=user, query={"query": "type:charx"}))
    assert [post["id"] for post in found["results"]] == [file]
    found = ok(client.get("/posts", user=user, query={"query": "-type:charx"}))
    assert [post["id"] for post in found["results"]] == [picture]


# what is no CHARX file: left to the engine, which refuses what nobody knows


@pytest.mark.parametrize(
    "data",
    [
        # archives without a card
        cards.archive({}),
        cards.archive({"readme.txt": b"hello"}),
        cards.archive(
            {"folder/card.json": json.dumps(cards.charx_card(None)).encode()}
        ),
        cards.archive({"CARD.JSON": json.dumps(cards.charx_card(None)).encode()}),
        # with something else under the card's name
        cards.archive({"card.json": b"not json"}),
        cards.archive({"card.json": b""}),
        cards.archive({"card.json": b"[1, 2, 3]"}),
        cards.archive({"card.json": json.dumps({"spec": "chara_card_v3"}).encode()}),
        # a card, but not a V3 one
        cards.archive({"card.json": json.dumps(cards.v2_card()).encode()}),
        cards.archive({"card.json": json.dumps(cards.V1_CARD).encode()}),
        cards.archive({"card.json/": b""}),
        # broken archives
        cards.charx()[:100],
        cards.charx()[:-10],
        b"PK\x03\x04" + b"\x00" * 200,
        b"PK\x03\x04 and then nothing of an archive",
        b"PK\x05\x06",
        # not archives
        b"",
        b"hello",
        cards.picture(),
    ],
)
def test_file_that_is_no_charx_file(data):
    assert _detect(data) is False
    assert _thumbnail(data) is None
    assert (
        list(cards_module.extract_charx("application/x-charx", io.BytesIO(data))) == []
    )


@pytest.mark.parametrize(
    "data",
    [
        cards.archive({"readme.txt": b"hello"}),
        cards.archive({"card.json": b"not json"}),
        cards.archive({"card.json": json.dumps(cards.v2_card()).encode()}),
        cards.charx()[:-10],
        b"PK\x03\x04" + b"\x00" * 200,
    ],
)
def test_archive_without_a_valid_card_is_refused_as_unknown(site, user, data):
    client = site(["cards"])
    assert _refused(client, user, data) == UNKNOWN


def test_broken_card_entry_is_no_card():
    data = cards.charx()
    # flip a byte in the compressed card
    position = data.index(b"card.json") + len("card.json") + 5
    broken = data[:position] + bytes([data[position] ^ 0xFF]) + data[position + 1 :]
    assert _detect(broken) is False


# hostile archives


def _bomb(size=10 * MEGABYTE):
    return cards.charx(**{"assets/other/zeros.bin": b"\x00" * size})


def test_zip_bomb_is_refused(site, user):
    client = site(["cards"])
    bomb = _bomb()
    assert len(bomb) < 64 * 1024
    assert _refused(client, user, bomb) == (
        "CHARX file refused: The archive has an entry that is compressed more "
        "than 100:1."
    )


def test_compression_ratio_at_the_limit_is_fine(monkeypatch):
    data = _bomb(MEGABYTE)
    entry = zipfile.ZipFile(io.BytesIO(data)).getinfo("assets/other/zeros.bin")
    ratio = -(-entry.file_size // entry.compress_size)
    monkeypatch.setattr(charx, "MAX_COMPRESSION_RATIO", ratio)
    assert _detect(data) is True
    monkeypatch.setattr(charx, "MAX_COMPRESSION_RATIO", ratio - 1)
    assert "compressed more than %d:1" % (ratio - 1) in _rejected(data)


def test_archive_that_unpacks_to_too_much_is_refused(monkeypatch):
    entries = {"card.json": json.dumps(cards.charx_card(None)).encode()}
    for number in range(4):
        entries["assets/other/%d.bin" % number] = os.urandom(300 * 1024)
    data = cards.archive(entries, zipfile.ZIP_STORED)
    assert _detect(data) is True
    monkeypatch.setattr(charx, "MAX_TOTAL_SIZE", MEGABYTE)
    assert _rejected(data) == (
        "CHARX file refused: The archive unpacks to more than 1 MiB."
    )


def test_shipped_limits():
    assert charx.MAX_ENTRIES == 1000
    assert charx.MAX_TOTAL_SIZE == 512 * MEGABYTE
    assert charx.MAX_COMPRESSION_RATIO == 100
    assert charx.MAX_CARD_SIZE == 8 * MEGABYTE


@pytest.mark.parametrize(
    "name",
    [
        "../evil.txt",
        "assets/../../evil.txt",
        "assets/..",
        "/etc/passwd",
        "\\windows\\system32\\evil",
        "..\\evil.txt",
        "C:\\evil.txt",
        "C:/evil.txt",
    ],
)
def test_path_traversal_is_refused(site, user, name):
    client = site(["cards"])
    assert _refused(client, user, cards.charx(**{name: b"evil"})) == (
        "CHARX file refused: The archive has an entry whose name is an absolute "
        "path or points outside the archive."
    )


def test_name_with_a_nul_character_is_refused():
    # the reader would cut the name off at the NUL and show a harmless one
    data = cards.charx(**{"assets/Xevil.txt": b"evil"}).replace(
        b"assets/Xevil.txt", b"assets/\x00evil.txt"
    )
    assert "points outside the archive" in _rejected(data)


@pytest.mark.parametrize("flags", [0x1, 0x41])
def test_encrypted_entry_is_refused(site, user, flags):
    client = site(["cards"])
    data = _patch_entry(
        cards.charx(**{"assets/other/secret.bin": b"secret"}),
        "assets/other/secret.bin",
        flags=flags,
    )
    assert _refused(client, user, data) == (
        "CHARX file refused: The archive has encrypted entries."
    )


def test_encrypted_card_is_refused():
    data = _patch_entry(cards.charx(), "card.json", flags=0x1)
    assert "encrypted entries" in _rejected(data)


def test_too_many_entries_are_refused(site, user):
    client = site(["cards"])
    entries = {"card.json": json.dumps(cards.charx_card(None)).encode()}
    for number in range(charx.MAX_ENTRIES - 1):
        entries["assets/other/%d" % number] = b""
    at_the_limit = cards.archive(entries)
    assert _detect(at_the_limit) is True
    entries["assets/other/one_more"] = b""
    assert _refused(client, user, cards.archive(entries)) == (
        "CHARX file refused: The archive has more than 1000 entries."
    )


def test_table_of_contents_larger_than_the_limit_is_refused_unread(monkeypatch):
    # many entries with long names: the reader would hold them all in memory
    entries = {"card.json": json.dumps(cards.charx_card(None)).encode()}
    for number in range(600):
        entries["assets/other/%04d-%s" % (number, "x" * 2000)] = b""
    data = cards.archive(entries)
    read = []
    real_read = io.BytesIO.read

    class Watched(io.BytesIO):
        def read(self, size=-1):
            read.append(size)
            return real_read(self, size)

    with pytest.raises(registry.FileRejected) as refusal:
        cards_module.detect_charx(data[:512], Watched(data))
    assert str(refusal.value) == (
        "CHARX file refused: The table of contents of the archive is larger "
        "than 1048576 bytes."
    )
    # refused before the piece was read
    assert max(read) < charx.MAX_DIRECTORY_SIZE


def test_oversized_card_is_refused(site, user):
    client = site(["cards"])
    card = json.dumps(cards.charx_card(None)).encode()
    padded = card + b" " * (charx.MAX_CARD_SIZE + 1 - len(card))
    data = cards.archive({"card.json": padded}, zipfile.ZIP_STORED)
    assert _refused(client, user, data) == (
        "CHARX file refused: card.json is larger than 8 MiB."
    )
    fits = cards.archive({"card.json": padded[:-1]}, zipfile.ZIP_STORED)
    assert _detect(fits) is True


def test_card_that_says_it_is_small_and_is_not():
    # the archive lies about the size of the card: what is read ends where
    # the archive said it would
    card = json.dumps(cards.charx_card(None)).encode()
    padded = card + b" " * (2 * MEGABYTE)
    data = cards.archive({"card.json": padded})
    lying = _patch_entry(data, "card.json", size=1000)
    with zipfile.ZipFile(io.BytesIO(lying)) as archive:
        with pytest.raises(charx.NotCharx):
            charx._read_entry(archive, archive.getinfo("card.json"), 4 * MEGABYTE)
    assert _detect(lying) is False


def test_unsupported_compression_is_refused():
    data = cards.archive(
        {"card.json": json.dumps(cards.charx_card(None)).encode()}, zipfile.ZIP_BZIP2
    )
    assert _rejected(data) == (
        "CHARX file refused: The archive uses a compression method other than deflate."
    )


@pytest.mark.parametrize(
    "icon",
    [
        cards.archive({"inner.txt": b"x"}),
        cards.charx(),
        b"\x1f\x8b\x08\x00 gzip",
        b"7z\xbc\xaf\x27\x1c 7z",
        b"Rar!\x1a\x07\x00 rar",
        b"\xfd7zXZ\x00 xz",
        b"BZh9 bzip2",
    ],
)
def test_nested_archive_as_the_icon_is_refused(site, user, icon):
    client = site(["cards"])
    assert _refused(client, user, cards.charx(cards.charx_card(), icon)) == (
        "CHARX file refused: The icon of the card is an archive, not a picture."
    )


def test_nested_archive_that_is_not_the_icon_is_only_an_entry(site, user):
    client = site(["cards"])
    data = cards.charx(
        icon=cards.picture(), **{"assets/other/more.zip": cards.archive({"a": b"b"})}
    )
    assert _upload(client, user, data)["type"] == "charx"


def test_nothing_is_ever_extracted_to_disk(site, user, monkeypatch, tmp_path):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("an archive was extracted")

    for name in ["extract", "extractall", "_extract_member"]:
        monkeypatch.setattr(zipfile.ZipFile, name, forbidden)
    working_dir = tmp_path / "working"
    working_dir.mkdir()
    monkeypatch.chdir(working_dir)
    client = site(["cards"])
    created = _upload(
        client,
        user,
        cards.charx(icon=cards.picture(), **{"assets/other/readme.txt": b"hello"}),
    )
    client.post(
        "/posts",
        user=user,
        body={"safety": "safe"},
        files={"content": cards.charx(**{"../evil.txt": b"evil"})},
    )
    # the data directory holds the upload and its thumbnail, and nothing of
    # what was in the archives; nor does the working directory
    found = []
    for folder, _folders, files in os.walk(config.config["data_dir"]):
        found += [
            os.path.join(os.path.relpath(folder, config.config["data_dir"]), f)
            for f in files
        ]
    assert sorted(os.path.basename(path).split(".")[-1] for path in found) == [
        "charx",
        "jpg",
    ]
    assert os.listdir(working_dir) == []
    assert created["type"] == "charx"


# the thumbnail: the card's main icon


@pytest.mark.parametrize(
    "uri",
    [
        "embeded://" + cards.ICON_PATH,
        # spelled right, and the form the PNG chunks use
        "embedded://" + cards.ICON_PATH,
        "__asset:" + cards.ICON_PATH,
    ],
)
def test_icon_in_the_archive(uri):
    icon = cards.picture(shade=3)
    assert _thumbnail(cards.charx(cards.charx_card(uri), icon)) == icon


def test_icon_as_a_data_uri():
    icon = cards.picture(shade=3)
    uri = "data:image/png;base64," + base64.b64encode(icon).decode()
    assert _thumbnail(cards.charx(cards.charx_card(uri))) == icon


@pytest.mark.parametrize(
    "uri",
    [
        None,
        "ccdefault:",
        # never fetched
        "https://example.com/icon.png",
        "http://169.254.169.254/latest/meta-data",
        "file:///etc/passwd",
        # not in the archive, or not as the card says
        "embeded://assets/icon/images/missing.png",
        "embeded://ASSETS/ICON/IMAGES/MAIN.PNG",
        "embeded://../" + cards.ICON_PATH,
        "embeded://assets/icon/images/",
        "embeded://",
        "data:image/png;base64,!!!",
        "data:image/png,not base64",
        "",
    ],
)
def test_icon_that_is_not_in_the_file_means_no_picture(uri):
    data = cards.charx(cards.charx_card(uri), cards.picture())
    assert _detect(data) is True
    assert _thumbnail(data) is None


def test_main_icon_among_several():
    main, other = cards.picture(shade=1), cards.picture(shade=2)
    card = cards.charx_card(
        None,
        assets=[
            {
                "type": "background",
                "uri": "embeded://b.png",
                "name": "main",
                "ext": "png",
            },
            {"type": "icon", "uri": "embeded://other.png", "name": "alt", "ext": "png"},
            {"type": "icon", "uri": "embeded://main.png", "name": "main", "ext": "png"},
        ],
    )
    data = cards.charx(card, **{"main.png": main, "other.png": other, "b.png": other})
    assert _thumbnail(data) == main


def test_first_icon_where_none_is_called_main():
    first, second = cards.picture(shade=1), cards.picture(shade=2)
    card = cards.charx_card(
        None,
        assets=[
            {
                "type": "emotion",
                "uri": "embeded://b.png",
                "name": "happy",
                "ext": "png",
            },
            {
                "type": "icon",
                "uri": "embeded://a.png",
                "name": "portrait",
                "ext": "png",
            },
            {"type": "icon", "uri": "embeded://b.png", "name": "other", "ext": "png"},
        ],
    )
    assert _thumbnail(cards.charx(card, **{"a.png": first, "b.png": second})) == first


@pytest.mark.parametrize(
    "assets",
    [
        None,
        "icon",
        42,
        [],
        [None, "x", 3],
        [{"type": "icon"}],
        [{"type": "icon", "uri": 5}],
    ],
)
def test_assets_that_are_not_what_the_specification_says(assets):
    data = cards.charx(cards.charx_card(None, assets=assets), cards.picture())
    assert _detect(data) is True
    assert _thumbnail(data) is None


def test_icon_larger_than_the_limit_means_no_picture(monkeypatch):
    icon = cards.picture()
    data = cards.charx(cards.charx_card(), icon)
    monkeypatch.setattr(charx, "MAX_ICON_SIZE", len(icon) - 1)
    assert _thumbnail(data) is None
    uri = "data:image/png;base64," + base64.b64encode(icon).decode()
    assert _thumbnail(cards.charx(cards.charx_card(uri))) is None
    monkeypatch.setattr(charx, "MAX_ICON_SIZE", len(icon))
    assert _thumbnail(data) == icon


def test_icon_that_is_no_picture_gets_the_placeholder(site, user):
    client = site(["cards"])
    created = _upload(client, user, cards.charx(cards.charx_card(), b"not a picture"))
    assert created["type"] == "charx"
    assert _stored(created["thumbnailUrl"]) == posts.EMPTY_PIXEL


def test_unreadable_icon_entry_means_no_picture():
    data = cards.charx(cards.charx_card(), cards.picture())
    position = data.index(cards.ICON_PATH.encode()) + len(cards.ICON_PATH) + 20
    broken = data[:position] + bytes([data[position] ^ 0xFF]) + data[position + 1 :]
    assert _detect(broken) is True
    assert _thumbnail(broken) is None


def test_errors_module_is_what_the_api_answers_with(site, user):
    client = site(["cards"])
    response = client.post(
        "/posts", user=user, body={"safety": "safe"}, files={"content": _bomb()}
    )
    assert response.status_code == 400
    assert_error(response, errors.ValidationError)
