"""
Character cards as JSON: telling the versions apart and making a card fit
to be stored.

The formats are described in
https://github.com/malfoyslastname/character-card-spec-v2 (V1 and V2) and
https://github.com/kwaroran/character-card-spec-v3 (V3). A card is somebody's
upload: nothing here trusts it, and nothing here raises for what it holds.
A card that is not one is `None`.
"""

import base64
import binascii
import json
import re
from typing import Any, cast

KIND_V1 = "card_v1"
KIND_V2 = "card_v2"
KIND_V3 = "card_v3"

# the value of `spec` and the kind it means
_SPECS = {"chara_card_v2": KIND_V2, "chara_card_v3": KIND_V3}

# The fields of a V1 card. The specification wants all of them; cards in the
# wild leave some out, so a card is taken for V1 when it has a name and at
# least one of the others, and none of them is something else than a text.
_V1_FIELDS = ("description", "personality", "scenario", "first_mes", "mes_example")

# The largest card text that is parsed. A card holds text, and with it
# sometimes pictures as data URIs, which are taken out before it is stored;
# this is what is held in memory meanwhile.
MAX_CARD_SIZE = 32 * 1024 * 1024

# A base64 data URI, alone or inside a longer text (a picture in the middle
# of the creator's notes): the media type, then the data.
_DATA_URI = re.compile(r"data:([\w.+-]+/[\w.+-]+)?((?:;[\w.+-]+=[^;,\s\"']*)*);base64,")
_BASE64_RUN = re.compile(r"[A-Za-z0-9+/_-]*={0,2}")

# what a lone half of a surrogate pair is replaced with: it is not text, and
# no database stores it
_REPLACEMENT = "�"
_SURROGATES = re.compile("[\ud800-\udfff]")


def decode(text: bytes) -> object | None:
    """
    The JSON a card chunk holds: base64 of UTF-8 text. None when it is not
    that. Line breaks and missing padding are forgiven, as the programs that
    read cards forgive them; anything else is not base64.
    """
    if len(text) > MAX_CARD_SIZE:
        return None
    compact = b"".join(text.split())
    compact += b"=" * (-len(compact) % 4)
    try:
        return parse(base64.b64decode(compact, validate=True))
    except (binascii.Error, ValueError):
        return None


def _refuse_constant(name: str) -> None:
    # NaN and the infinities: Python's extension of JSON, which no database
    # takes
    raise ValueError(name)


def parse(text: bytes) -> object | None:
    """The JSON value of a card file, or None when it is not JSON."""
    if len(text) > MAX_CARD_SIZE:
        return None
    try:
        # utf-8-sig: some editors put a byte order mark in front
        return json.loads(text.decode("utf-8-sig"), parse_constant=_refuse_constant)
    except (ValueError, RecursionError):
        return None


def _is_text(value: object) -> bool:
    return isinstance(value, str)


def kind_of(card: object) -> str | None:
    """
    Which version of a card this JSON value is, by what it says and holds,
    or None when it is not a card.

    V2 and V3 name themselves in `spec` and keep the card in `data`. A V1
    card is the bare fields. The specifications ask for more fields than
    cards in the wild have, so only what makes a card a card is asked for:
    a name.
    """
    if not isinstance(card, dict):
        return None
    fields = cast(dict[str, object], card)
    spec = fields.get("spec")
    if spec is not None:
        if not isinstance(spec, str) or spec not in _SPECS:
            return None
        data = fields.get("data")
        if not isinstance(data, dict):
            return None
        if not _is_text(cast(dict[str, object], data).get("name")):
            return None
        return _SPECS[spec]
    if not _is_text(fields.get("name")):
        return None
    present = [fields[name] for name in _V1_FIELDS if name in fields]
    if not present or not all(_is_text(value) for value in present):
        return None
    return KIND_V1


def _data_size(data: str) -> int:
    """How many bytes a run of base64 stands for."""
    length = len(data.rstrip("="))
    return length * 3 // 4


def _embedded(media_type: str, name: str | None, size: int) -> dict[str, Any]:
    return {"embedded": {"type": media_type or None, "name": name, "size": size}}


def _strip_text(text: str, name: str | None) -> str | dict[str, Any]:
    """
    The text without the binary data it carries as base64 data URIs. A text
    that is nothing but a data URI becomes what is known about the data; a
    data URI inside a longer text is cut out and its place marked.
    """
    if "\x00" in text:
        # PostgreSQL cannot store the character, and it is no part of a text
        text = text.replace("\x00", "")
    if _SURROGATES.search(text):
        text = _SURROGATES.sub(_REPLACEMENT, text)
    if ";base64," not in text:
        return text
    parts: list[str] = []
    position = 0
    while True:
        found = _DATA_URI.search(text, position)
        if found is None:
            break
        data = _BASE64_RUN.match(text, found.end())
        assert data is not None  # the pattern matches the empty text too
        media_type = found.group(1) or ""
        size = _data_size(data.group())
        if found.start() == 0 and data.end() == len(text):
            return _embedded(media_type, name, size)
        parts.append(text[position : found.start()])
        parts.append("[embedded %s removed: %d bytes]" % (media_type or "data", size))
        position = data.end()
    parts.append(text[position:])
    return "".join(parts)


def _strip(value: object, name: str | None) -> object:
    if isinstance(value, str):
        return _strip_text(value, name)
    if isinstance(value, list):
        return [_strip(item, name) for item in cast(list[object], value)]
    if isinstance(value, dict):
        fields = cast(dict[str, object], value)
        # an asset says what it is called itself
        asset_name = fields.get("name") if "uri" in fields else None
        stripped: dict[str, object] = {}
        for key, item in fields.items():
            key = _SURROGATES.sub(_REPLACEMENT, key.replace("\x00", ""))
            item_name = asset_name if isinstance(asset_name, str) else key
            stripped[key] = _strip(item, item_name)
        return stripped
    return value


def stored(card: object) -> dict[str, Any] | None:
    """
    The card as it is stored: as given, minus the binary data it embeds.
    Every base64 data URI is replaced by what is known about it
    (`{"embedded": {"type", "name", "size"}}`: the media type, the name of
    the asset or of the field it was in, and its size in bytes). Everything
    else stays, the lorebook (`character_book`) included.

    Two things that are no part of any text are taken out as well, because
    the database cannot hold them: NUL characters and lone surrogates.

    None for a card nested deeper than anything a card is.
    """
    try:
        stripped = _strip(card, None)
    except RecursionError:
        return None
    if not isinstance(stripped, dict):
        return None
    return cast(dict[str, Any], stripped)
