"""
Character cards for the tests of the cards module, made in code: no card
anybody published is part of this repository.
"""

import base64
import io
import json
import struct
import zipfile
import zlib
from typing import Any

from PIL import Image

V1_CARD: dict[str, Any] = {
    "name": "Ada",
    "description": "A lighthouse keeper who talks to the sea.",
    "personality": "patient, dry",
    "scenario": "A storm is coming in.",
    "first_mes": "You made it up the stairs. Tea?",
    "mes_example": "<START>\n{{user}}: hi\n{{char}}: Mind the lamp.",
}

LOREBOOK: dict[str, Any] = {
    "name": "The coast",
    "extensions": {},
    "entries": [
        {
            "keys": ["lamp", "light"],
            "content": "The lamp was lit in 1871 and has never gone out.",
            "extensions": {},
            "enabled": True,
            "insertion_order": 10,
        },
        {
            "keys": ["storm"],
            "content": "Storms come from the north-west.",
            "extensions": {},
            "enabled": False,
            "insertion_order": 20,
            "constant": False,
        },
    ],
}


def v2_card(**data: Any) -> dict[str, Any]:
    return {
        "spec": "chara_card_v2",
        "spec_version": "2.0",
        "data": {
            **V1_CARD,
            "creator_notes": "Works best with a long context.",
            "system_prompt": "",
            "post_history_instructions": "",
            "alternate_greetings": ["The door was open.", "Back again?"],
            "character_book": LOREBOOK,
            "tags": ["lighthouse", "Slice of Life"],
            "creator": "somebody",
            "character_version": "1.2",
            "extensions": {"some_app": {"depth": 4}},
            **data,
        },
    }


def v3_card(**data: Any) -> dict[str, Any]:
    card = v2_card(
        **{
            "group_only_greetings": [],
            "nickname": "Keeper",
            "assets": [
                {"type": "icon", "uri": "ccdefault:", "name": "main", "ext": "png"}
            ],
            **data,
        }
    )
    card["spec"] = "chara_card_v3"
    card["spec_version"] = "3.0"
    return card


def encoded(card: Any) -> bytes:
    """A card as the chunks hold it: base64 of its JSON."""
    return base64.b64encode(json.dumps(card).encode("utf-8"))


def _chunk(chunk_type: bytes, data: bytes) -> bytes:
    checksum = zlib.crc32(chunk_type + data)
    return (
        struct.pack(">I", len(data)) + chunk_type + data + struct.pack(">I", checksum)
    )


def text_chunk(keyword: bytes, text: bytes) -> bytes:
    return _chunk(b"tEXt", keyword + b"\x00" + text)


def compressed_text_chunk(keyword: bytes, text: bytes) -> bytes:
    return _chunk(b"zTXt", keyword + b"\x00\x00" + zlib.compress(text))


def international_text_chunk(
    keyword: bytes, text: bytes, compress: bool = False
) -> bytes:
    body = zlib.compress(text) if compress else text
    flag = b"\x01" if compress else b"\x00"
    return _chunk(
        b"iTXt", keyword + b"\x00" + flag + b"\x00" + b"\x00" + b"\x00" + body
    )


def picture(shade: int = 0) -> bytes:
    """A small PNG picture; `shade` tells one from another."""
    image = Image.new("RGB", (64, 64), (shade, 90, 160))
    for x in range(0, 64, 4):
        image.putpixel((x, (x * 5 + shade) % 64), (250, 250, shade))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def png_with(*chunks: bytes, shade: int = 0) -> bytes:
    """A PNG picture with these chunks put in front of its end."""
    plain = picture(shade)
    end = plain.rindex(b"IEND") - 4
    return plain[:end] + b"".join(chunks) + plain[end:]


def png_card(card: Any, keyword: bytes = b"chara", shade: int = 0) -> bytes:
    """A PNG picture that carries the card in a `tEXt` chunk."""
    return png_with(text_chunk(keyword, encoded(card)), shade=shade)


ICON_PATH = "assets/icon/images/main.png"


def charx_card(icon_uri: str | None = "embeded://" + ICON_PATH, **data: Any) -> Any:
    """A V3 card as a CHARX file holds it, with its main icon at this URI."""
    assets = (
        []
        if icon_uri is None
        else [{"type": "icon", "uri": icon_uri, "name": "main", "ext": "png"}]
    )
    return v3_card(**{"assets": assets, **data})


def archive(
    entries: dict[str, bytes], compression: int = zipfile.ZIP_DEFLATED
) -> bytes:
    """A ZIP archive with these entries, in this order."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression) as zip_file:
        for name, data in entries.items():
            # a fixed date: the same entries make the same archive every time
            entry = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            entry.compress_type = compression
            zip_file.writestr(entry, data)
    return buffer.getvalue()


def charx(card: Any = None, icon: bytes | None = None, **entries: bytes) -> bytes:
    """A CHARX file: the card, its icon if given, and any other entries."""
    if card is None:
        card = charx_card() if icon is not None else charx_card(None)
    content = {"card.json": json.dumps(card).encode("utf-8")}
    if icon is not None:
        content[ICON_PATH] = icon
    content.update(entries)
    return archive(content)
