"""
Character cards in PNG files.

A card rides in a text chunk of the picture: `ccv3` for a V3 card, `chara`
for a V2 or V1 one, the card's JSON as base64 (see lithica.modules.cards.card
for the formats). The V3 specification names `tEXt`; `zTXt` and `iTXt`, the
other two text chunks of PNG, are read the same way, since a PNG library
may pick either for the same text. A V3 picture may also carry files in
chunks named `chara-ext-asset_:<path>`.

The file is somebody's upload. Nothing is read without a limit, nothing is
trusted, and nothing here raises for what the file holds: a picture whose
card cannot be read is a picture.
"""

import struct
import zlib
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import BinaryIO

from lithica.modules.cards import card as card_format

SIGNATURE = b"\x89PNG\r\n\x1a\n"

V3_KEYWORD = b"ccv3"
V2_KEYWORD = b"chara"
ASSET_PREFIX = b"chara-ext-asset_:"

# A keyword of a text chunk is at most 79 bytes by the PNG specification.
# The asset chunks put a path there and do not keep to it, so more is read.
MAX_KEYWORD_SIZE = 1024

# how many embedded assets of one picture are listed
MAX_ASSETS = 1000

_TEXT_CHUNKS = (b"tEXt", b"zTXt", b"iTXt")


@dataclass(frozen=True)
class Asset:
    """A file embedded in a `chara-ext-asset_:` chunk: where, and how large."""

    path: str
    # in bytes, once decoded; None where it cannot be told without reading it
    size: int | None


@dataclass
class Embedded:
    """What a PNG file carries besides the picture."""

    # keyword -> the text of the first chunk with it; empty if unreadable
    cards: dict[bytes, bytes] = field(default_factory=dict[bytes, bytes])
    assets: list[Asset] = field(default_factory=list[Asset])


def _inflate(data: bytes, limit: int) -> bytes | None:
    """Decompress, but never to more than `limit` bytes. None if it is not zlib."""
    inflater = zlib.decompressobj()
    try:
        inflated = inflater.decompress(data, limit + 1)
    except zlib.error:
        return None
    if len(inflated) > limit or not inflater.eof:
        return None
    return inflated


def _chunks(handle: BinaryIO) -> Iterator[tuple[bytes, int, int]]:
    """
    The (type, offset of the data, length of the data) of every chunk of a
    PNG file. The caller may read the data or not.
    """
    if handle.read(len(SIGNATURE)) != SIGNATURE:
        return
    position = len(SIGNATURE)
    while True:
        handle.seek(position)
        header = handle.read(8)
        if len(header) < 8:
            return
        length: int
        chunk_type: bytes
        length, chunk_type = struct.unpack(">I4s", header)
        if chunk_type == b"IEND":
            return
        yield chunk_type, position + 8, length
        # past the data and its checksum
        position += 8 + length + 4


def _text_of(chunk_type: bytes, rest: bytes, limit: int) -> bytes | None:
    """The text of a text chunk, given what follows its keyword."""
    if chunk_type == b"tEXt":
        return rest
    if chunk_type == b"zTXt":
        # one byte for the compression method, of which there is one
        if rest[:1] != b"\x00":
            return None
        return _inflate(rest[1:], limit)
    # iTXt: compression flag and method, language tag, translated keyword
    if len(rest) < 2:
        return None
    compressed = rest[0]
    parts = rest[2:].split(b"\x00", 2)
    if len(parts) < 3:
        return None
    if compressed == 0:
        return parts[2]
    if compressed == 1 and rest[1] == 0:
        return _inflate(parts[2], limit)
    return None


def _base64_size(handle: BinaryIO, offset: int, length: int) -> int:
    """How many bytes the base64 text at this place stands for, unread."""
    if length == 0:
        return 0
    handle.seek(offset + max(length - 2, 0))
    padding = handle.read(min(length, 2)).count(b"=")
    return max(length * 3 // 4 - padding, 0)


def read(handle: BinaryIO) -> Embedded:
    """
    The card chunks and the asset chunks of a PNG file. Of several chunks
    with the same keyword the first one counts. An asset's data is not
    read, only measured.
    """
    embedded = Embedded()
    for chunk_type, offset, length in _chunks(handle):
        if chunk_type not in _TEXT_CHUNKS:
            continue
        handle.seek(offset)
        start = handle.read(min(length, MAX_KEYWORD_SIZE + 1))
        keyword, separator, _rest = start.partition(b"\x00")
        if not separator:
            continue
        text_offset = offset + len(keyword) + 1
        text_length = length - len(keyword) - 1
        if keyword.startswith(ASSET_PREFIX):
            if len(embedded.assets) < MAX_ASSETS:
                size = (
                    _base64_size(handle, text_offset, text_length)
                    if chunk_type == b"tEXt"
                    else None
                )
                # the PNG specification says Latin-1; NUL ended the keyword
                path = keyword[len(ASSET_PREFIX) :].decode("latin-1")
                embedded.assets.append(Asset(path, size))
            continue
        if keyword not in (V3_KEYWORD, V2_KEYWORD) or keyword in embedded.cards:
            continue
        # A chunk that is there counts, readable or not: a broken `ccv3`
        # chunk does not make way for the `chara` chunk.
        embedded.cards[keyword] = b""
        if text_length > card_format.MAX_CARD_SIZE:
            continue
        handle.seek(text_offset)
        rest = handle.read(text_length)
        if len(rest) < text_length:
            # the file ends inside the chunk
            continue
        text = _text_of(chunk_type, rest, card_format.MAX_CARD_SIZE)
        if text is not None:
            embedded.cards[keyword] = text
    return embedded
