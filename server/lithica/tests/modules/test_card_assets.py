"""File image selection and chunk preservation at the untrusted boundary."""

import base64
from collections.abc import Callable
from io import BytesIO

import pytest

from lithica.modules.cards import assets, pictures, png
from lithica.tests.modules import cards


def test_stripped_preserves_other_chunks() -> None:
    keep = [
        cards.text_chunk(b"parameters", b"generation info"),
        cards._chunk(b"acTL", b"12345678"),
    ]
    original = cards.png_with(
        cards.text_chunk(b"chara", cards.encoded(cards.v2_card())),
        keep[0],
        cards.compressed_text_chunk(b"ccv3", b"anything"),
        cards.international_text_chunk(b"chara-ext-asset_:x", b"asset", True),
        keep[1],
    )
    result = png.stripped(BytesIO(original))
    assert result is not None
    assert result == cards.png_with(*keep)
    assert pictures.same_pixels(original, result)
    assert png.read(BytesIO(result)).cards == []
    assert png.read(BytesIO(result)).assets == []
    assert (
        png.stripped(
            BytesIO(cards.png_with(cards.text_chunk(b"chara-ext-asset_:x", b"data")))
        )
        == cards.picture()
    )


@pytest.mark.parametrize("data", [b"bad", png.SIGNATURE, cards.picture()[:-1]])
def test_unreadable_png(data: bytes) -> None:
    assert png.stripped(BytesIO(data)) is None


@pytest.mark.parametrize(
    "chunk",
    [cards.text_chunk, cards.compressed_text_chunk, cards.international_text_chunk],
)
def test_asset_read_and_limit(chunk: Callable[[bytes, bytes], bytes]) -> None:
    data = cards.picture()
    original = cards.png_with(chunk(b"chara-ext-asset_:x", base64.b64encode(data)))
    assert png.read_asset(BytesIO(original), "x", len(data)) == data
    assert png.read_asset(BytesIO(original), "x", len(data) - 1) is None
    assert png.read_asset(BytesIO(original), "missing", len(data)) is None


def test_roles_sources_and_order() -> None:
    raw = cards.v3_card(
        assets=[
            {"type": "emotion", "name": " happy ", "uri": "__asset:happy"},
            {"type": "emotion", "uri": "__asset:unnamed"},
            {"type": "icon", "name": "other", "uri": "__asset:other"},
            {"type": "icon", "name": "main", "uri": "ccdefault:"},
            {"type": "background", "uri": "__asset:bg"},
            {"type": "background", "uri": "https://example.test/image"},
            {"type": "icon", "uri": "ccdefault:"},
        ]
    )
    found = assets.images(raw, True)
    assert [(i.uri, i.relation, i.label, i.main) for i in found] == [
        ("ccdefault:", "avatar-of", "main", True),
        ("__asset:happy", "expression-of", "happy", False),
        ("__asset:unnamed", "embedded-in", None, False),
        ("__asset:other", "avatar-of", "other", False),
        ("__asset:bg", "embedded-in", None, False),
    ]
    assert [i.position for i in found] == [3, 0, 1, 2, 4]
    assert assets.images(cards.v2_card(), True)[0].main
    assert not assets.images(cards.v3_card(), False)


def test_data_uri_and_non_media() -> None:
    uri = "data:image/png;base64," + base64.b64encode(cards.picture()).decode()
    raw = cards.v3_card(assets=[{"type": "icon", "name": "main", "uri": uri}])
    with assets.opened(cards.png_card(raw, b"ccv3")) as source:
        assert source.picture(source.images[0]) == cards.picture()
    raw["data"]["assets"][0]["uri"] = "__asset:font"
    content = cards.png_with(
        cards.text_chunk(b"ccv3", cards.encoded(raw)),
        cards.text_chunk(b"chara-ext-asset_:font", base64.b64encode(b"not media")),
    )
    with assets.opened(content) as source:
        assert source.picture(source.images[0]) is None


def test_image_count_and_uri_limits() -> None:
    raw = cards.v3_card(
        assets=[{"type": "background", "uri": f"__asset:{i}"} for i in range(205)]
        + [{"type": "icon", "name": "main", "uri": "ccdefault:"}]
    )
    found = assets.images(raw, True)
    assert len(found) == 200
    assert found[0].main and found[-1].uri == "__asset:198"
    raw["data"]["assets"] = [{"type": "icon", "uri": "__asset:" + "x" * 1024}]
    assert assets.images(raw, True) == []


@pytest.mark.parametrize("format_", ["WEBP", "GIF"])
def test_charx_engine_asset_bytes(format_: str) -> None:
    from PIL import Image

    data = BytesIO()
    Image.new("RGB", (16, 16), (10, 50, 80)).save(data, format_)
    raw = cards.v3_card(
        assets=[{"type": "emotion", "name": "smile", "uri": "embedded://assets/x"}]
    )
    content = cards.charx(raw, **{"assets/x": data.getvalue()})
    with assets.opened(content) as source:
        assert source.images[0].relation == "expression-of"
        assert source.picture(source.images[0]) == data.getvalue()


def test_corrupt_and_oversized_compressed_asset() -> None:
    content = cards.png_with(cards.text_chunk(b"chara-ext-asset_:x", b"!!!"))
    assert png.read_asset(BytesIO(content), "x", 20) is None
    content = cards.png_with(
        cards.compressed_text_chunk(
            b"chara-ext-asset_:x", base64.b64encode(b"a" * 10000)
        )
    )
    assert png.read_asset(BytesIO(content), "x", 20) is None
    assert png.stripped(BytesIO(cards.picture()), limit=10) is None
