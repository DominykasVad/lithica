"""The cards module: cards in PNG pictures (PLAN.md 4.4)."""

import base64
import io
import json
from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
from pathlib import Path

import pytest

from lithica import db, model, registry
from lithica.func import post_content
from lithica.modules import cards as cards_module
from lithica.modules.cards import card as card_format
from lithica.modules.cards import png
from lithica.tests.api.http import ok
from lithica.tests.modules import cards

ADMIN_PATH = Path(__file__).resolve().parent.parent.parent.parent / "lithica-admin"


@pytest.fixture(scope="module")
def admin():
    # lithica-admin is a script without the .py suffix
    loader = SourceFileLoader("lithica_admin", str(ADMIN_PATH))
    spec = spec_from_loader("lithica_admin", loader)
    assert spec
    module = module_from_spec(spec)
    loader.exec_module(module)
    return module


def _extract(content):
    return list(cards_module.extract_png("image/png", io.BytesIO(content)))


def _one(content):
    (found,) = _extract(content)
    return found.kind, found.payload


def _upload(client, user, content):
    return ok(
        client.post(
            "/posts", user=user, body={"safety": "safe"}, files={"content": content}
        )
    )


def _content(client, user, post_id):
    return ok(client.get("/post/%d/content" % post_id, user=user))["results"]


# which card, of which kind


def test_module_describes_itself():
    registry.load(["cards"])
    (module,) = registry.modules()
    assert module.name == "cards"
    assert sorted(registry.content_kinds()) == ["card_v1", "card_v2", "card_v3"]
    assert post_content.get_extracted_mime_types() == {
        "image/png",
        "application/x-charx",
    }


def test_v1_card():
    kind, payload = _one(cards.png_card(cards.V1_CARD))
    assert kind == "card_v1"
    assert payload == {
        "format": "png",
        "chunk": "chara",
        "card": cards.V1_CARD,
        "assets": [],
    }


def test_v2_card():
    card = cards.v2_card()
    kind, payload = _one(cards.png_card(card))
    assert kind == "card_v2"
    assert payload == {"format": "png", "chunk": "chara", "card": card, "assets": []}
    # the lorebook stays inside the card
    assert payload["card"]["data"]["character_book"] == cards.LOREBOOK


def test_v3_card():
    card = cards.v3_card()
    kind, payload = _one(cards.png_card(card, b"ccv3"))
    assert kind == "card_v3"
    assert payload == {"format": "png", "chunk": "ccv3", "card": card, "assets": []}


def test_v3_chunk_wins_over_the_v2_chunk():
    v2, v3 = cards.v2_card(name="Old"), cards.v3_card(name="New")
    for chunks in [
        (
            cards.text_chunk(b"chara", cards.encoded(v2)),
            cards.text_chunk(b"ccv3", cards.encoded(v3)),
        ),
        (
            cards.text_chunk(b"ccv3", cards.encoded(v3)),
            cards.text_chunk(b"chara", cards.encoded(v2)),
        ),
    ]:
        found = _extract(cards.png_with(*chunks))
        assert [(content.kind, content.payload["chunk"]) for content in found] == [
            ("card_v3", "ccv3")
        ]
        assert found[0].payload["card"]["data"]["name"] == "New"


def test_unreadable_v3_chunk_does_not_make_way_for_the_v2_chunk():
    picture = cards.png_with(
        cards.text_chunk(b"ccv3", b"!!! not base64 !!!"),
        cards.text_chunk(b"chara", cards.encoded(cards.v2_card())),
    )
    assert _extract(picture) == []


def test_first_of_two_chunks_with_the_same_keyword_counts():
    picture = cards.png_with(
        cards.text_chunk(b"chara", cards.encoded(cards.v2_card(name="First"))),
        cards.text_chunk(b"chara", cards.encoded(cards.v2_card(name="Second"))),
    )
    assert _one(picture)[1]["card"]["data"]["name"] == "First"


def test_card_that_names_itself_v3_in_the_v2_chunk_is_v3():
    kind, payload = _one(cards.png_card(cards.v3_card(), b"chara"))
    assert (kind, payload["chunk"]) == ("card_v3", "chara")


@pytest.mark.parametrize("card", [cards.V1_CARD, cards.v2_card()])
def test_v3_chunk_holds_v3_cards_only(card):
    assert _extract(cards.png_card(card, b"ccv3")) == []


@pytest.mark.parametrize(
    "chunk",
    [
        cards.compressed_text_chunk,
        cards.international_text_chunk,
        lambda keyword, text: cards.international_text_chunk(keyword, text, True),
    ],
)
def test_other_text_chunks_are_read_too(chunk):
    card = cards.v2_card()
    kind, payload = _one(cards.png_with(chunk(b"chara", cards.encoded(card))))
    assert kind == "card_v2" and payload["card"] == card


def test_card_of_a_newer_v3_version_is_a_v3_card():
    card = cards.v3_card()
    card["spec_version"] = "3.1"
    card["data"]["a_field_of_the_future"] = {"x": 1}
    kind, payload = _one(cards.png_card(card, b"ccv3"))
    assert kind == "card_v3" and payload["card"] == card


def test_card_with_fewer_fields_than_the_specification_asks_for():
    # cards in the wild leave fields out
    assert _one(cards.png_card({"name": "Ada", "description": "x"}))[0] == "card_v1"
    card = {"spec": "chara_card_v2", "data": {"name": "Ada"}}
    assert _one(cards.png_card(card)) == (
        "card_v2",
        {"format": "png", "chunk": "chara", "card": card, "assets": []},
    )


def test_unicode_survives():
    card = cards.v2_card(name="アダ", description="naïve — “quoted” 🙂")
    assert _one(cards.png_card(card))[1]["card"] == card


def test_base64_with_line_breaks_and_without_padding():
    text = cards.encoded(cards.v2_card()).rstrip(b"=")
    broken = b"\n".join(text[i : i + 76] for i in range(0, len(text), 76))
    assert _one(cards.png_with(cards.text_chunk(b"chara", broken)))[0] == "card_v2"


def test_byte_order_mark_in_front_of_the_json():
    text = base64.b64encode(b"\xef\xbb\xbf" + json.dumps(cards.V1_CARD).encode())
    assert _one(cards.png_with(cards.text_chunk(b"chara", text)))[0] == "card_v1"


# what is not a card


def test_picture_without_a_card():
    assert _extract(cards.picture()) == []
    assert _extract(cards.png_with(cards.text_chunk(b"Title", b"A picture"))) == []


@pytest.mark.parametrize(
    "text",
    [
        b"",
        b"!!! not base64 !!!",
        base64.b64encode(b"not json"),
        base64.b64encode(b"\xff\xfe\x00 not utf-8"),
        base64.b64encode(b'{"name": "Ada", "description": "cut off'),
        base64.b64encode(b'{"name": NaN, "description": Infinity}'),
        # JSON, but not a card
        cards.encoded(None),
        cards.encoded("a string"),
        cards.encoded(42),
        cards.encoded([cards.V1_CARD]),
        cards.encoded({}),
        cards.encoded({"description": "no name"}),
        cards.encoded({"name": "only a name"}),
        cards.encoded({"name": 42, "description": "x"}),
        cards.encoded({"name": "Ada", "description": ["not", "a", "text"]}),
        cards.encoded({"spec": "chara_card_v2"}),
        cards.encoded({"spec": "chara_card_v2", "data": "x"}),
        cards.encoded({"spec": "chara_card_v2", "data": {}}),
        cards.encoded({"spec": "chara_card_v2", "data": {"name": None}}),
        cards.encoded({"spec": "chara_card_v9", "data": {"name": "Ada"}}),
        cards.encoded({"spec": 2, "data": {"name": "Ada"}}),
        # nested deeper than a parser goes
        base64.b64encode(b"[" * 100000 + b"]" * 100000),
    ],
)
def test_malformed_card_is_no_card(text):
    assert _extract(cards.png_with(cards.text_chunk(b"chara", text))) == []
    assert _extract(cards.png_with(cards.text_chunk(b"ccv3", text))) == []


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"not a picture",
        png.SIGNATURE,
        png.SIGNATURE + b"\x00\x00",
        # a chunk that says it is longer than the file
        png.SIGNATURE + b"\x7f\xff\xff\xfftEXtchara\x00abc",
        # a text chunk without the end of its keyword
        cards.png_with(cards._chunk(b"tEXt", b"chara")),
        # compressed chunks that are not
        cards.png_with(cards._chunk(b"zTXt", b"chara\x00\x00not zlib")),
        cards.png_with(cards._chunk(b"zTXt", b"chara\x00\x07" + b"x" * 8)),
        cards.png_with(cards._chunk(b"iTXt", b"chara\x00\x01\x00\x00\x00not zlib")),
        cards.png_with(cards._chunk(b"iTXt", b"chara\x00\x00")),
        cards.png_with(cards._chunk(b"iTXt", b"chara\x00")),
    ],
)
def test_broken_file_is_no_card(data):
    assert _extract(data) == []


def test_file_that_ends_inside_the_card_chunk():
    whole = cards.png_card(cards.v2_card())
    cut = whole[: whole.index(b"chara") + 200]
    assert _extract(cut) == []


def test_card_chunk_larger_than_the_limit_is_not_read(monkeypatch):
    picture = cards.png_card(cards.v2_card())
    monkeypatch.setattr(card_format, "MAX_CARD_SIZE", 100)
    assert _extract(picture) == []


def test_compressed_chunk_is_not_inflated_beyond_the_limit(monkeypatch):
    # a megabyte of zeros is a kilobyte compressed
    bomb = cards.compressed_text_chunk(b"chara", b"A" * 1024 * 1024)
    assert len(bomb) < 2048
    monkeypatch.setattr(card_format, "MAX_CARD_SIZE", 64 * 1024)
    inflated = []
    real = png._inflate

    def watching(data, limit):
        result = real(data, limit)
        inflated.append(result)
        return result

    monkeypatch.setattr(png, "_inflate", watching)
    assert _extract(cards.png_with(bomb)) == []
    assert inflated == [None]


# embedded binary data


def _data_uri(size, media_type="image/png"):
    return "data:%s;base64,%s" % (media_type, base64.b64encode(b"\x89" * size).decode())


def test_embedded_data_is_replaced_by_what_is_known_about_it():
    card = cards.v3_card(
        assets=[
            {"type": "icon", "uri": _data_uri(3000), "name": "main", "ext": "png"},
            {
                "type": "emotion",
                "uri": _data_uri(10, "image/webp"),
                "name": "happy",
                "ext": "webp",
            },
            {
                "type": "background",
                "uri": "https://example.com/b.png",
                "name": "sea",
                "ext": "png",
            },
            {
                "type": "icon",
                "uri": "embeded://assets/icon/x.png",
                "name": "x",
                "ext": "png",
            },
        ],
        extensions={"some_app": {"avatar": _data_uri(7, "image/jpeg")}},
    )
    stored = _one(cards.png_card(card, b"ccv3"))[1]["card"]
    assert stored["data"]["assets"] == [
        {
            "type": "icon",
            "uri": {"embedded": {"type": "image/png", "name": "main", "size": 3000}},
            "name": "main",
            "ext": "png",
        },
        {
            "type": "emotion",
            "uri": {"embedded": {"type": "image/webp", "name": "happy", "size": 10}},
            "name": "happy",
            "ext": "webp",
        },
        # what is not embedded stays as it is
        {
            "type": "background",
            "uri": "https://example.com/b.png",
            "name": "sea",
            "ext": "png",
        },
        {
            "type": "icon",
            "uri": "embeded://assets/icon/x.png",
            "name": "x",
            "ext": "png",
        },
    ]
    assert stored["data"]["extensions"] == {
        "some_app": {
            "avatar": {"embedded": {"type": "image/jpeg", "name": "avatar", "size": 7}}
        }
    }
    # and nothing else changed
    for name in [
        "name",
        "description",
        "character_book",
        "tags",
        "alternate_greetings",
    ]:
        assert stored["data"][name] == card["data"][name]


def test_data_inside_a_text_is_cut_out_and_its_place_marked():
    notes = "Look: ![her](%s) and ![him](%s). Bye." % (
        _data_uri(2000),
        _data_uri(5, "image/gif"),
    )
    card = cards.v2_card(creator_notes=notes)
    stored = _one(cards.png_card(card))[1]["card"]
    assert stored["data"]["creator_notes"] == (
        "Look: ![her]([embedded image/png removed: 2000 bytes]) and "
        "![him]([embedded image/gif removed: 5 bytes]). Bye."
    )


def test_text_that_only_looks_like_embedded_data_stays():
    card = cards.v2_card(
        description="Write data:text/plain,hello and ;base64, as you like.",
        scenario="data:image/png;base64",
    )
    assert _one(cards.png_card(card))[1]["card"] == card


def test_size_of_embedded_data_is_exact():
    for size in range(0, 7):
        card = cards.v2_card(extensions={"x": _data_uri(size)})
        stored = _one(cards.png_card(card))[1]["card"]
        assert stored["data"]["extensions"]["x"]["embedded"]["size"] == size


def test_card_with_large_pictures_fits_once_they_are_out():
    card = cards.v3_card(
        assets=[
            {
                "type": "icon",
                "uri": _data_uri(2 * 1024 * 1024),
                "name": "main",
                "ext": "png",
            }
        ]
    )
    picture = cards.png_card(card, b"ccv3")
    assert len(picture) > post_content.MAX_PAYLOAD_SIZE
    registry.load(["cards"])
    extraction = post_content.extract("image/png", picture)
    assert extraction.failed_kinds == set()
    (found,) = extraction.contents
    assert len(json.dumps(found.payload)) < 8 * 1024


def test_characters_no_database_holds_are_taken_out():
    text = json.dumps(cards.v2_card()).replace("Ada", "A\\u0000d\\ud83da")
    picture = cards.png_with(
        cards.text_chunk(b"chara", base64.b64encode(text.encode()))
    )
    registry.load(["cards"])
    extraction = post_content.extract("image/png", picture)
    assert extraction.failed_kinds == set()
    assert extraction.contents[0].payload["card"]["data"]["name"] == "Ad�a"


# assets embedded in the picture


def test_embedded_assets_are_listed_not_stored():
    data = base64.b64encode(b"\x01" * 4001)
    picture = cards.png_with(
        cards.text_chunk(b"ccv3", cards.encoded(cards.v3_card())),
        cards.text_chunk(b"chara-ext-asset_:assets/icon/main.png", data),
        cards.text_chunk(b"chara-ext-asset_:0", base64.b64encode(b"ab")),
        cards.text_chunk(b"chara-ext-asset_:empty", b""),
        cards.compressed_text_chunk(b"chara-ext-asset_:packed", data),
    )
    kind, payload = _one(picture)
    assert kind == "card_v3"
    assert payload["assets"] == [
        {"path": "assets/icon/main.png", "size": 4001},
        {"path": "0", "size": 2},
        {"path": "empty", "size": 0},
        # compressed: its size is not known without reading it
        {"path": "packed", "size": None},
    ]
    assert len(json.dumps(payload)) < len(data)


def test_assets_without_a_card_are_nothing():
    picture = cards.png_with(cards.text_chunk(b"chara-ext-asset_:x", b"AAAA"))
    assert _extract(picture) == []


def test_number_of_listed_assets_is_limited(monkeypatch):
    monkeypatch.setattr(png, "MAX_ASSETS", 3)
    picture = cards.png_with(
        cards.text_chunk(b"ccv3", cards.encoded(cards.v3_card())),
        *[cards.text_chunk(b"chara-ext-asset_:%d" % i, b"AAAA") for i in range(10)],
    )
    assert [asset["path"] for asset in _one(picture)[1]["assets"]] == ["0", "1", "2"]


# through the API


@pytest.mark.parametrize(
    "card,keyword,kind",
    [
        (cards.V1_CARD, b"chara", "card_v1"),
        (cards.v2_card(), b"chara", "card_v2"),
        (cards.v3_card(), b"ccv3", "card_v3"),
    ],
)
def test_upload_of_a_card(site, user, card, keyword, kind):
    client = site(["cards"])
    uploaded = cards.png_card(card, keyword)
    created = _upload(client, user, uploaded)
    # a card is a picture like any other
    assert created["type"] == "image"
    assert created["mimeType"] == "image/png"
    assert created["contentKinds"] == [kind]
    (content,) = _content(client, user, created["id"])
    assert content["kind"] == kind
    assert content["schemaVersion"] == 1
    assert content["content"] == {
        "format": "png",
        "chunk": keyword.decode(),
        "card": card,
        "assets": [],
    }


def test_upload_of_a_picture_with_both_chunks(site, user):
    client = site(["cards"])
    picture = cards.png_with(
        cards.text_chunk(b"chara", cards.encoded(cards.v2_card(name="Old"))),
        cards.text_chunk(b"ccv3", cards.encoded(cards.v3_card(name="New"))),
    )
    created = _upload(client, user, picture)
    assert created["contentKinds"] == ["card_v3"]
    (content,) = _content(client, user, created["id"])
    assert content["content"]["card"]["data"]["name"] == "New"


@pytest.mark.parametrize(
    "text",
    [
        b"!!! not base64 !!!",
        base64.b64encode(b"not json"),
        cards.encoded({"spec": "chara_card_v2", "data": []}),
    ],
)
def test_malformed_card_uploads_as_a_plain_picture(site, user, text, caplog):
    client = site(["cards"])
    picture = cards.png_with(cards.text_chunk(b"chara", text))
    created = _upload(client, user, picture)
    assert created["type"] == "image"
    assert created["contentKinds"] == []
    assert _content(client, user, created["id"]) == []
    assert db.session.query(model.PostContent).count() == 0
    # not an error of the module either: the picture just has no card
    assert "extractor" not in caplog.text


def test_without_the_module_a_card_is_a_plain_picture(site, user):
    client = site([])
    created = _upload(client, user, cards.png_card(cards.v2_card()))
    assert created["contentKinds"] == []
    assert db.session.query(model.PostContent).count() == 0


def test_reextract_reads_the_cards_of_existing_posts(site, user, admin, capsys):
    client = site([])
    v1 = _upload(client, user, cards.png_card(cards.V1_CARD, shade=1))["id"]
    v2 = _upload(client, user, cards.png_card(cards.v2_card(), shade=2))["id"]
    v3 = _upload(client, user, cards.png_card(cards.v3_card(), b"ccv3", shade=3))["id"]
    plain = _upload(client, user, cards.picture(shade=4))["id"]
    db.session.commit()
    assert db.session.query(model.PostContent).count() == 0

    client = site(["cards"])
    admin.main(["reextract", "--kind", "card_v2"])
    assert "4 posts to process" in capsys.readouterr().out
    db.session.expire_all()
    # only the kind that was asked for
    assert [
        ok(client.get("/post/%d" % post_id, user=user))["contentKinds"]
        for post_id in (v1, v2, v3, plain)
    ] == [[], ["card_v2"], [], []]
    (content,) = _content(client, user, v2)
    assert content["content"]["card"] == cards.v2_card()

    admin.main(["reextract"])
    db.session.expire_all()
    assert [
        ok(client.get("/post/%d" % post_id, user=user))["contentKinds"]
        for post_id in (v1, v2, v3, plain)
    ] == [["card_v1"], ["card_v2"], ["card_v3"], []]
    # the card of the second post was not stored a second time
    assert db.session.query(model.PostContent).count() == 3
