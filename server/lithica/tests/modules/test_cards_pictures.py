"""Pixel identity is independent of card text, encoding and signature advice."""

import struct
import zlib
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

import pytest
from PIL import Image

from lithica.func.content import Content
from lithica.modules.cards import pictures
from lithica.tests.modules import cards


def test_png_picture_keeps_bytes(tmp_path: Path) -> None:
    content = cards.png_card(cards.v2_card())
    assert pictures.picture(content) == content
    path = tmp_path / "card.png"
    path.write_bytes(content)
    assert pictures.picture(Content(str(path))) == content


def test_charx_picture_is_main_icon() -> None:
    icon = cards.picture()
    assert pictures.picture(cards.charx(icon=icon)) == icon


@pytest.mark.parametrize("icon", [None, b"not a picture", b"<svg></svg>"])
def test_charx_without_engine_picture(icon: bytes | None) -> None:
    assert pictures.picture(cards.charx(icon=icon)) is None


def test_other_file_has_no_picture() -> None:
    assert pictures.picture(b"not a card") is None


def test_same_pixels_with_different_card_text() -> None:
    first = cards.png_card(cards.v2_card(name="First"))
    second = cards.png_card(cards.v2_card(name="Second"))
    assert first != second
    assert pictures.same_pixels(first, second)
    result = pictures.compare(first, second)
    assert result == {
        "samePixels": True,
        "similarity": 1.0,
        "oldPicture": True,
        "newPicture": True,
    }


def test_different_pixels_same_size() -> None:
    first, second = cards.picture(0), cards.picture(80)
    assert not pictures.same_pixels(first, second)
    result = pictures.compare(first, second)
    assert result["similarity"] is not None
    assert 0.0 <= result["similarity"] <= 1.0
    assert result["similarity"] == round(result["similarity"], 2)


def test_different_size_does_not_decode() -> None:
    buffer = BytesIO()
    Image.new("RGB", (32, 64)).save(buffer, "PNG")
    with patch.object(Image.Image, "convert", side_effect=AssertionError("decoded")):
        assert not pictures.same_pixels(cards.picture(), buffer.getvalue())


def test_rgba_identity_includes_alpha() -> None:
    first, second = BytesIO(), BytesIO()
    Image.new("RGBA", (32, 32), (20, 30, 40, 0)).save(first, "PNG")
    Image.new("RGBA", (32, 32), (20, 30, 40, 255)).save(second, "PNG")
    assert not pictures.same_pixels(first.getvalue(), second.getvalue())


def test_rgb_and_rgba_decode_to_same_pixels() -> None:
    first, second = BytesIO(), BytesIO()
    Image.new("RGB", (32, 32), (20, 30, 40)).save(first, "PNG")
    Image.new("RGBA", (32, 32), (20, 30, 40, 255)).save(second, "PNG")
    assert pictures.same_pixels(first.getvalue(), second.getvalue())


@pytest.mark.parametrize("old,new", [(None, None), (None, b"bad"), (b"bad", b"bad")])
def test_missing_or_undecodable_picture(old: bytes | None, new: bytes | None) -> None:
    assert pictures.compare(old, new) == {
        "samePixels": False,
        "similarity": None,
        "oldPicture": old is not None,
        "newPicture": new is not None,
    }


def test_decompression_bomb_limit_stays_in_force() -> None:
    content = cards.picture()
    with patch.object(Image, "MAX_IMAGE_PIXELS", 100):
        assert not pictures.same_pixels(content, content)
        assert pictures.compare(content, content)["similarity"] is None


@pytest.mark.parametrize("broken_first", [True, False])
def test_valid_png_header_with_undecodable_chunks(broken_first: bool) -> None:
    intact = cards.picture()
    start = intact.index(b"IDAT")
    # Keep a valid header and the zlib header, then put an invalid chunk where
    # the decoder needs the remaining compressed pixels. Image.open succeeds;
    # the failure happens only when the pixels are decoded.
    prefix = intact[start + 4 : start + 6]
    partial = (
        struct.pack(">I", len(prefix))
        + b"IDAT"
        + prefix
        + struct.pack(">I", zlib.crc32(b"IDAT" + prefix))
    )
    broken = intact[: start - 4] + partial + struct.pack(">I", 0) + b"!!!!" + b"\0" * 4
    with Image.open(BytesIO(broken)) as image:
        assert image.size == (64, 64)
    old, new = (broken, intact) if broken_first else (intact, broken)
    assert not pictures.same_pixels(old, new)
    assert pictures.compare(old, new) == {
        "samePixels": False,
        "similarity": None,
        "oldPicture": True,
        "newPicture": True,
    }
