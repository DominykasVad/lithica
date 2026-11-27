"""Unit tests for PNG and CHARX writers, verified with the module's readers."""

import io
import zipfile

import pytest
from PIL import Image

from lithica.modules.cards import card as card_format
from lithica.modules.cards import charx, png
from lithica.tests.modules import cards


def _pixels(data: bytes) -> tuple[tuple[int, int], bytes]:
    with Image.open(io.BytesIO(data)) as image:
        rgba = image.convert("RGBA")
        return rgba.size, rgba.tobytes()


def test_png_write_v3_v2_and_both_read_back() -> None:
    carrier = cards.png_card(cards.v2_card(name="Old"), shade=20)
    v3 = cards.v3_card(name="Exported V3")
    v2 = cards.v2_card(name="Exported V2")
    asset_one = cards.picture(50)
    asset_two = cards.picture(90)

    out = io.BytesIO()
    png.write(
        io.BytesIO(carrier),
        out,
        v3=v3,
        v2=v2,
        assets=[("0.png", asset_one), ("1.png", asset_two)],
    )
    out.seek(0)

    embedded = png.read(out)
    assert [chunk.keyword for chunk in embedded.cards] == [
        png.V3_KEYWORD,
        png.V2_KEYWORD,
    ]
    assert [asset.path for asset in embedded.assets] == ["0.png", "1.png"]
    assert png.read_card(out) == v3

    # Verify the V2 chunk directly as well.
    v2_chunk = next(c for c in embedded.cards if c.keyword == png.V2_KEYWORD)
    v2_text = png.read_text(out, v2_chunk)
    assert v2_text is not None
    assert card_format.decode(v2_text) == v2

    # Assets are byte-identical and pixels equal the carrier's.
    assert png.read_asset(out, "0.png", 1024 * 1024) == asset_one
    assert png.read_asset(out, "1.png", 1024 * 1024) == asset_two
    assert _pixels(out.getvalue()) == _pixels(carrier)
    stripped_orig = png.stripped(io.BytesIO(carrier))
    assert stripped_orig is not None
    assert png.stripped(out) == stripped_orig


def test_png_write_v3_only_and_v2_only() -> None:
    carrier = cards.picture(10)
    v3 = cards.v3_card(name="Only V3")
    out_v3 = io.BytesIO()
    png.write(io.BytesIO(carrier), out_v3, v3=v3)
    out_v3.seek(0)
    assert [c.keyword for c in png.read(out_v3).cards] == [png.V3_KEYWORD]
    assert png.read_card(out_v3) == v3

    v2 = cards.v2_card(name="Only V2")
    out_v2 = io.BytesIO()
    png.write(io.BytesIO(carrier), out_v2, v2=v2)
    out_v2.seek(0)
    assert [c.keyword for c in png.read(out_v2).cards] == [png.V2_KEYWORD]
    assert png.read_card(out_v2) == v2


def test_png_write_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    carrier = cards.picture(15)
    v3 = cards.v3_card(name="Big")
    v2 = cards.v2_card(name="Big")

    # Combined v3+v2 chunk size limit.
    monkeypatch.setattr(card_format, "MAX_CARD_SIZE", 500)
    with pytest.raises(png.Oversized, match="chunk limit"):
        png.write(io.BytesIO(carrier), io.BytesIO(), v3=v3, v2=v2)

    monkeypatch.undo()
    with pytest.raises(png.Oversized, match="embedded images"):
        png.write(
            io.BytesIO(carrier),
            io.BytesIO(),
            v3=v3,
            assets=[("0.png", b"a"), ("1.png", b"b")],
            max_assets=1,
        )
    with pytest.raises(png.Oversized, match="PNG asset limit"):
        png.write(
            io.BytesIO(carrier),
            io.BytesIO(),
            v3=v3,
            assets=[("0.png", b"0123456789")],
            max_asset_size=5,
        )


def test_charx_write_reads_back_with_assets() -> None:
    icon = cards.picture(30)
    emotion = cards.picture(70)
    card = cards.v3_card(
        name="Charx Export",
        assets=[
            {
                "type": "icon",
                "uri": "embeded://assets/icon/images/0.png",
                "name": "main",
                "ext": "png",
            },
            {
                "type": "emotion",
                "uri": "embeded://assets/emotion/images/1.png",
                "name": "smile",
                "ext": "png",
            },
        ],
    )
    out = io.BytesIO()
    charx.write(
        out,
        card,
        [
            ("assets/icon/images/0.png", icon),
            ("assets/emotion/images/1.png", emotion),
        ],
        icon_path="assets/icon/images/0.png",
    )
    out.seek(0)
    with charx.opened(out) as opened:
        assert opened.card == card
        assert charx.main_icon(opened) == icon
        assert (
            charx.asset_bytes(opened, "embeded://assets/emotion/images/1.png", 1024**2)
            == emotion
        )


def test_charx_write_repetitive_card_avoids_ratio_rejection() -> None:
    card = cards.v3_card(description="a" * 200_000)
    out = io.BytesIO()
    charx.write(out, card)
    out.seek(0)
    with charx.opened(out) as opened:
        assert opened.card == card
        card_entry = opened.find(charx.CARD_NAME)
        assert card_entry is not None
        assert card_entry.compress_type == zipfile.ZIP_STORED


def test_charx_write_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    card = cards.v3_card(name="Limited")
    monkeypatch.setattr(charx, "MAX_CARD_SIZE", 50)
    with pytest.raises(charx.Rejected, match="card.json"):
        charx.write(io.BytesIO(), card)
    monkeypatch.undo()

    monkeypatch.setattr(charx, "MAX_ENTRIES", 2)
    with pytest.raises(charx.Rejected, match="entry limit"):
        charx.write(
            io.BytesIO(),
            card,
            [("assets/other/images/0.png", b"a"), ("assets/other/images/1.png", b"b")],
        )
    monkeypatch.undo()

    monkeypatch.setattr(charx, "MAX_ICON_SIZE", 10)
    with pytest.raises(charx.Rejected, match="icon limit"):
        charx.write(
            io.BytesIO(),
            card,
            [("assets/icon/images/0.png", b"0" * 20)],
            icon_path="assets/icon/images/0.png",
        )
    monkeypatch.undo()

    monkeypatch.setattr(charx, "MAX_TOTAL_SIZE", 1024)
    with pytest.raises(charx.Rejected, match="unpacked size limit"):
        charx.write(
            io.BytesIO(),
            card,
            [("assets/other/images/0.png", b"0" * 1024)],
        )
