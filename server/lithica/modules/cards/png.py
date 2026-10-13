"""
Character cards in PNG files.

A card rides in a text chunk of the picture: `ccv3` for a V3 card, `chara`
for a V2 or V1 one, the card's JSON as base64 (see lithica.modules.cards.card
for the formats). A picture may have several chunks with the same keyword;
which of them is the card is the extractor's business (see
lithica.modules.cards). The V3 specification names `tEXt`; `zTXt` and `iTXt`, the
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

# How many card chunks of one picture are looked at and listed. A card is
# one chunk, or two where a V2 copy rides along; sites that re-export a
# picture leave the older chunks in. More than this is not a card's doing.
MAX_CARDS = 64

_TEXT_CHUNKS = (b"tEXt", b"zTXt", b"iTXt")


@dataclass(frozen=True)
class Asset:
    """A file embedded in a `chara-ext-asset_:` chunk: where, and how large."""

    path: str
    # in bytes, once decoded; None where it cannot be told without reading it
    size: int | None


@dataclass(frozen=True)
class CardChunk:
    """
    A text chunk that carries a card, found and not yet read: which keyword,
    the how-manyth chunk of the file it is (the first chunk of a PNG file,
    `IHDR`, is number 0), and how many bytes of data it has.
    """

    keyword: bytes
    position: int
    size: int
    # how the text is stored, and where: for read_text()
    chunk_type: bytes
    text_offset: int
    text_length: int


@dataclass
class Embedded:
    """What a PNG file carries besides the picture."""

    # the card chunks, in the order of the file
    cards: list[CardChunk] = field(default_factory=list[CardChunk])
    assets: list[Asset] = field(default_factory=list[Asset])


class Oversized(Exception):
    """A card chunk holds more text than is read of one."""


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


def _inflates_beyond(chunk_type: bytes, rest: bytes, limit: int) -> bool:
    """Whether a compressed text chunk is unreadable because it is too large."""
    if chunk_type == b"zTXt":
        data = rest[1:]
    else:
        parts = rest[2:].split(b"\x00", 2)
        if len(parts) < 3 or rest[:1] != b"\x01":
            return False
        data = parts[2]
    inflater = zlib.decompressobj()
    try:
        return len(inflater.decompress(data, limit + 1)) > limit
    except zlib.error:
        return False


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
    The card chunks and the asset chunks of a PNG file, found and measured.
    Nothing of their data is read here: a card chunk is read with read_text(),
    when it is its turn, and an asset's data never.
    """
    embedded = Embedded()
    file_size = handle.seek(0, 2)
    handle.seek(0)
    for position, (chunk_type, offset, length) in enumerate(_chunks(handle)):
        if chunk_type not in _TEXT_CHUNKS:
            continue
        if offset + length > file_size:
            # the file ends inside the chunk, whatever length it claims
            return embedded
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
        if keyword in (V3_KEYWORD, V2_KEYWORD) and len(embedded.cards) < MAX_CARDS:
            embedded.cards.append(
                CardChunk(
                    keyword, position, length, chunk_type, text_offset, text_length
                )
            )
    return embedded


def read_text(handle: BinaryIO, chunk: CardChunk) -> bytes | None:
    """
    The text of a card chunk, or None if it cannot be read (a compressed
    chunk that is not what it says). Raises Oversized for a chunk with more
    text than MAX_CARD_SIZE, as it is stored or once it is inflated: too
    large is not unreadable.
    """
    if chunk.text_length > card_format.MAX_CARD_SIZE:
        raise Oversized
    handle.seek(chunk.text_offset)
    rest = handle.read(chunk.text_length)
    if len(rest) < chunk.text_length:
        return None
    found = _text_of(chunk.chunk_type, rest, card_format.MAX_CARD_SIZE)
    if (
        found is None
        and chunk.chunk_type != b"tEXt"
        and _inflates_beyond(chunk.chunk_type, rest, card_format.MAX_CARD_SIZE)
    ):
        raise Oversized
    return found
