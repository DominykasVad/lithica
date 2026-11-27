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

import base64
import binascii
import json
import struct
import zlib
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, BinaryIO, cast

from lithica.func.content import Content, ContentLike
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


def stripped(handle: BinaryIO, *, limit: int | None = None) -> bytes | None:
    """Copy complete chunks verbatim, excluding all card and asset text chunks.

    The optional bound is used by image ingestion before allocating picture bytes.
    Chunk lengths are checked against the actual file before reading or seeking.
    """
    size = handle.seek(0, 2)
    handle.seek(0)
    if handle.read(8) != SIGNATURE:
        return None
    result = bytearray(SIGNATURE)
    position = 8
    first = True
    saw_data = False
    while position + 12 <= size:
        handle.seek(position)
        header = handle.read(8)
        length, kind = struct.unpack(">I4s", header)
        end = position + 12 + length
        if end > size or (first and (kind != b"IHDR" or length != 13)):
            return None
        if not first and kind == b"IHDR":
            return None
        first = False
        if kind == b"IDAT" and length:
            saw_data = True
        remove = False
        if kind in _TEXT_CHUNKS:
            keyword = handle.read(min(length, MAX_KEYWORD_SIZE + 1)).partition(b"\x00")
            remove = keyword[0].startswith(ASSET_PREFIX) or (
                bool(keyword[1]) and keyword[0] in (V3_KEYWORD, V2_KEYWORD)
            )
        if not remove:
            if limit is not None and len(result) + length + 12 > limit:
                return None
            handle.seek(position)
            result.extend(handle.read(length + 12))
        if kind == b"IEND":
            return bytes(result) if length == 0 and saw_data else None
        position = end
    return None


def read_asset(handle: BinaryIO, path: str, limit: int) -> bytes | None:
    """Decode one asset; compressed and encoded bytes have explicit bounds too."""
    try:
        wanted = ASSET_PREFIX + path.encode("latin-1")
    except UnicodeEncodeError:
        return None
    size = handle.seek(0, 2)
    handle.seek(0)
    encoded_limit = (limit + 2) // 3 * 4
    for kind, offset, length in _chunks(handle):
        if offset + length + 4 > size:
            return None
        if kind not in _TEXT_CHUNKS:
            continue
        handle.seek(offset)
        start = handle.read(min(length, MAX_KEYWORD_SIZE + 1))
        keyword, sep, _ = start.partition(b"\x00")
        if not sep or keyword != wanted:
            continue
        remaining = length - len(keyword) - 1
        if remaining > encoded_limit + MAX_KEYWORD_SIZE:
            return None
        handle.seek(offset + len(keyword) + 1)
        text = _text_of(kind, handle.read(remaining), encoded_limit)
        if text is None or len(text) > encoded_limit:
            return None
        try:
            decoded = base64.b64decode(text, validate=True)
        except (binascii.Error, ValueError):
            return None
        return decoded if len(decoded) <= limit else None
    return None


def read_card(handle: BinaryIO) -> dict[str, object] | None:
    """Read the same first valid card as extraction, retaining its data URIs."""
    embedded = read(handle)
    for keyword in (V3_KEYWORD, V2_KEYWORD):
        for chunk in embedded.cards:
            if chunk.keyword != keyword:
                continue
            try:
                text = read_text(handle, chunk)
            except Oversized:
                return None
            value = card_format.decode(text) if text is not None else None
            kind = card_format.kind_of(value)
            if kind is not None and (
                keyword != V3_KEYWORD or kind == card_format.KIND_V3
            ):
                if card_format.stored(value) is not None:
                    return cast(dict[str, object], value)
    return None


_COPY_BLOCK = 64 * 1024


def _write_text_chunk(dest: BinaryIO, keyword: bytes, text: bytes) -> None:
    length = len(keyword) + 1 + len(text)
    dest.write(struct.pack(">I4s", length, b"tEXt"))
    crc = zlib.crc32(b"tEXt")
    dest.write(keyword)
    crc = zlib.crc32(keyword, crc)
    dest.write(b"\x00")
    crc = zlib.crc32(b"\x00", crc)
    dest.write(text)
    crc = zlib.crc32(text, crc)
    dest.write(struct.pack(">I", crc & 0xFFFFFFFF))


def _encode_card(card: Mapping[str, Any]) -> bytes:
    raw = json.dumps(card, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return base64.b64encode(raw)


def _content_size(content: ContentLike) -> int:
    return content.size if isinstance(content, Content) else len(content)


def _copy_exact(src: BinaryIO, dest: BinaryIO, count: int) -> None:
    remaining = count
    while remaining > 0:
        block = src.read(min(_COPY_BLOCK, remaining))
        if not block:
            raise ValueError("Unexpected end of PNG carrier.")
        dest.write(block)
        remaining -= len(block)


def write(
    carrier: BinaryIO,
    dest: BinaryIO,
    *,
    v3: Mapping[str, Any] | None = None,
    v2: Mapping[str, Any] | None = None,
    assets: Sequence[tuple[str, ContentLike]] = (),
    max_assets: int = MAX_ASSETS,
    max_asset_size: int | None = None,
) -> None:
    """Stream carrier chunks to dest and insert card and asset tEXt chunks."""
    v3_text = _encode_card(v3) if v3 is not None else b""
    v2_text = _encode_card(v2) if v2 is not None else b""
    if len(v3_text) + len(v2_text) > card_format.MAX_CARD_SIZE:
        limit_mib = card_format.MAX_CARD_SIZE // (1024 * 1024)
        raise Oversized(
            f"The exported PNG card data exceeds the {limit_mib} MiB chunk limit. "
            "Export with share links instead."
        )
    if len(assets) > max_assets:
        raise Oversized(
            f"The exported PNG has more than {max_assets} embedded images. "
            "Export with share links instead."
        )
    prepared: list[tuple[bytes, ContentLike]] = []
    for path, content in assets:
        keyword = ASSET_PREFIX + path.encode("latin-1")
        if len(keyword) > MAX_KEYWORD_SIZE:
            raise Oversized("An embedded PNG asset name is too long.")
        size = _content_size(content)
        if max_asset_size is not None and size > max_asset_size:
            limit_mib = max_asset_size // (1024 * 1024)
            raise Oversized(
                f"An embedded image exceeds the {limit_mib} MiB PNG asset limit. "
                "Export with share links instead."
            )
        prepared.append((keyword, content))

    size = carrier.seek(0, 2)
    carrier.seek(0)
    if carrier.read(len(SIGNATURE)) != SIGNATURE:
        raise ValueError("Carrier is not a valid PNG.")
    dest.write(SIGNATURE)

    position = len(SIGNATURE)
    first = True
    saw_data = False
    while position + 12 <= size:
        carrier.seek(position)
        header = carrier.read(8)
        length, kind = struct.unpack(">I4s", header)
        end = position + 12 + length
        if end > size or (first and (kind != b"IHDR" or length != 13)):
            raise ValueError("Carrier is not a valid PNG.")
        if not first and kind == b"IHDR":
            raise ValueError("Carrier is not a valid PNG.")
        first = False
        if kind == b"IDAT" and length:
            saw_data = True
        if kind == b"IEND":
            if length != 0 or not saw_data:
                raise ValueError("Carrier is not a valid PNG.")
            if v3 is not None:
                _write_text_chunk(dest, V3_KEYWORD, v3_text)
            if v2 is not None:
                _write_text_chunk(dest, V2_KEYWORD, v2_text)
            for keyword, content in prepared:
                if isinstance(content, Content):
                    with content.open() as src:
                        raw = src.read()
                else:
                    raw = content
                _write_text_chunk(dest, keyword, base64.b64encode(raw))
            carrier.seek(position)
            _copy_exact(carrier, dest, 12)
            return
        remove = False
        if kind in _TEXT_CHUNKS:
            keyword_part = carrier.read(min(length, MAX_KEYWORD_SIZE + 1)).partition(
                b"\x00"
            )
            remove = keyword_part[0].startswith(ASSET_PREFIX) or (
                bool(keyword_part[1]) and keyword_part[0] in (V3_KEYWORD, V2_KEYWORD)
            )
        if not remove:
            carrier.seek(position)
            _copy_exact(carrier, dest, length + 12)
        position = end
    raise ValueError("Carrier is not a valid PNG.")
