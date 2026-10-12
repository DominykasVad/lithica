"""
Character cards in CHARX files.

A CHARX file is a ZIP archive with the card, a V3 one, as `card.json` at
its root, and the card's pictures and other files beside it (see "CHARX"
in https://github.com/kwaroran/character-card-spec-v3).

An archive is the most hostile thing a site can be handed: a few kilobytes
that unpack to gigabytes, names that climb out of the directory they are
unpacked to, a table of contents with millions of entries. So:

- nothing is ever unpacked to disk. An entry is read from the archive, into
  memory, up to a limit set before the first byte is read;
- the limits below are checked on what the archive says about itself
  before anything in it is read, and what is read is cut off at what was
  said, so an archive that lies gains nothing;
- an archive that breaks a limit, or is built to deceive, is refused with
  a message that names the limit. One that simply is no CHARX file (no
  readable V3 card as `card.json`) is not this module's: the engine
  refuses it as it refuses any file nobody knows.
"""

import base64
import binascii
import zipfile
import zlib
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import IO, BinaryIO, cast

from lithica.modules.cards import card as card_format

MIME_TYPE = "application/x-charx"
POST_TYPE = "charx"
EXTENSION = "charx"

CARD_NAME = "card.json"

# The limits. An upload that exceeds one is refused.
MAX_ENTRIES = 1000
MAX_TOTAL_SIZE = 512 * 1024 * 1024
MAX_COMPRESSION_RATIO = 100
MAX_CARD_SIZE = 8 * 1024 * 1024
# The table of contents of the archive, which is read whole before anything
# is known about the archive: room for MAX_ENTRIES entries with long names.
MAX_DIRECTORY_SIZE = 1024 * 1024

# the largest picture taken out of an archive for the thumbnail
MAX_ICON_SIZE = 16 * 1024 * 1024

# how a ZIP file starts: a file entry, or the end record of an empty archive
_ZIP_SIGNATURES = (b"PK\x03\x04", b"PK\x05\x06")

# The first bytes of the archive formats (ZIP, gzip, 7z, RAR, xz, bzip2): an
# icon that is one of these is an archive in the place of a picture.
_ARCHIVE_SIGNATURES = (
    b"PK\x03\x04",
    b"PK\x05\x06",
    b"PK\x07\x08",
    b"\x1f\x8b",
    b"7z\xbc\xaf\x27\x1c",
    b"Rar!\x1a\x07",
    b"\xfd7zXZ\x00",
    b"BZh",
)

_ENCRYPTED = 0x1
_STRONGLY_ENCRYPTED = 0x40

# the URI forms that point into the archive; the specification spells the
# first one this way, and programs that spell it right are read as well
_EMBEDDED_PREFIXES = ("embeded://", "embedded://", "__asset:")


class Rejected(Exception):
    """The archive breaks a limit or is built to deceive; the message says how."""


class NotCharx(Exception):
    """The file is not a CHARX file, for no fault that needs naming."""


class _Budget:
    """
    A file that may be read only so much. The ZIP reader reads an archive's
    table of contents in one piece of the size the archive names; this is
    what stops it before it allocates that piece.
    """

    def __init__(self, handle: BinaryIO, limit: int) -> None:
        self._handle = handle
        self._left: int | None = limit

    def unlimited(self) -> None:
        self._left = None

    def read(self, size: int = -1) -> bytes:
        if self._left is not None:
            if size < 0 or size > self._left:
                raise Rejected(
                    "The table of contents of the archive is larger than %d bytes."
                    % MAX_DIRECTORY_SIZE
                )
            self._left -= size
        return self._handle.read(size)

    def seek(self, offset: int, whence: int = 0) -> int:
        return self._handle.seek(offset, whence)

    def tell(self) -> int:
        return self._handle.tell()

    def seekable(self) -> bool:
        return True


def _megabytes(size: int) -> str:
    return "%d MiB" % (size // (1024 * 1024))


def _is_unsafe(name: str) -> bool:
    """Whether a name points anywhere but below the root of the archive."""
    if not name or "\x00" in name:
        return True
    unified = name.replace("\\", "/")
    if unified.startswith("/") or (len(unified) > 1 and unified[1] == ":"):
        return True
    return ".." in unified.split("/")


def _verify(entries: list[zipfile.ZipInfo]) -> None:
    """Check what the archive says about itself against the limits."""
    if len(entries) > MAX_ENTRIES:
        raise Rejected("The archive has more than %d entries." % MAX_ENTRIES)
    total = 0
    for entry in entries:
        if entry.flag_bits & (_ENCRYPTED | _STRONGLY_ENCRYPTED):
            raise Rejected("The archive has encrypted entries.")
        # the name as the archive has it, and as the reader tidied it
        if _is_unsafe(entry.orig_filename) or _is_unsafe(entry.filename):
            raise Rejected(
                "The archive has an entry whose name is an absolute path or "
                "points outside the archive."
            )
        if entry.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
            raise Rejected("The archive uses a compression method other than deflate.")
        if entry.file_size > entry.compress_size * MAX_COMPRESSION_RATIO:
            raise Rejected(
                "The archive has an entry that is compressed more than %d:1."
                % MAX_COMPRESSION_RATIO
            )
        total += entry.file_size
        if total > MAX_TOTAL_SIZE:
            raise Rejected(
                "The archive unpacks to more than %s." % _megabytes(MAX_TOTAL_SIZE)
            )


def _read_entry(archive: zipfile.ZipFile, entry: zipfile.ZipInfo, limit: int) -> bytes:
    """
    The data of an entry that says it is at most `limit` bytes long. What is
    read ends where the entry said it would, whatever the data does.
    """
    if entry.file_size > limit:
        raise NotCharx
    try:
        with archive.open(entry) as handle:
            data = handle.read(limit + 1)
    except (
        zipfile.BadZipFile,
        zlib.error,
        OSError,
        EOFError,
        ValueError,
        RuntimeError,
        NotImplementedError,
    ) as ex:
        # a broken entry: a wrong checksum, or data that is not deflate
        raise NotCharx from ex
    if len(data) > limit:
        raise NotCharx
    return data


@dataclass
class Charx:
    """An archive that passed the checks, and its card."""

    archive: zipfile.ZipFile
    entries: list[zipfile.ZipInfo]
    card: dict[str, object]

    def find(self, path: str) -> zipfile.ZipInfo | None:
        """The file entry with exactly this name."""
        for entry in self.entries:
            if entry.filename == path and not entry.is_dir():
                return entry
        return None


@contextmanager
def opened(handle: BinaryIO) -> Generator[Charx]:
    """
    Open a CHARX file: check the archive against the limits and read its
    card. Raises Rejected for an archive that must be refused, and NotCharx
    for a file that is no CHARX file.
    """
    handle.seek(0)
    if handle.read(4) not in _ZIP_SIGNATURES:
        raise NotCharx
    budget = _Budget(handle, MAX_DIRECTORY_SIZE)
    try:
        # the budget has the few methods of a file the reader uses
        archive = zipfile.ZipFile(cast(IO[bytes], budget))
    except (
        zipfile.BadZipFile,
        OSError,
        EOFError,
        ValueError,
        NotImplementedError,
    ) as ex:
        raise NotCharx from ex
    with archive:
        # the table of contents is in memory; the entries have limits of
        # their own
        budget.unlimited()
        entries = archive.infolist()
        card_entry = next(
            (entry for entry in entries if entry.filename == CARD_NAME), None
        )
        if card_entry is None:
            # some other archive: not ours to judge
            raise NotCharx
        _verify(entries)
        if card_entry.file_size > MAX_CARD_SIZE:
            raise Rejected(
                "%s is larger than %s." % (CARD_NAME, _megabytes(MAX_CARD_SIZE))
            )
        card = card_format.parse(_read_entry(archive, card_entry, MAX_CARD_SIZE))
        if card_format.kind_of(card) != card_format.KIND_V3:
            raise NotCharx
        yield Charx(archive, entries, cast(dict[str, object], card))


def verify_icon(charx: Charx) -> None:
    """Refuse a card whose main icon is an archive in the place of a picture."""
    icon = main_icon(charx)
    if icon is not None and icon.startswith(_ARCHIVE_SIGNATURES):
        raise Rejected("The icon of the card is an archive, not a picture.")


def _icon_uri(card: dict[str, object]) -> str | None:
    """The URI of the main icon: the icon named `main`, or else the first."""
    data = cast(dict[str, object], card["data"])
    assets = data.get("assets")
    if not isinstance(assets, list):
        return None
    icons: list[dict[str, object]] = []
    for asset in cast(list[object], assets):
        if isinstance(asset, dict):
            fields = cast(dict[str, object], asset)
            if fields.get("type") == "icon" and isinstance(fields.get("uri"), str):
                icons.append(fields)
    if not icons:
        return None
    main = next((icon for icon in icons if icon.get("name") == "main"), icons[0])
    return cast(str, main["uri"])


def _data_uri_bytes(uri: str) -> bytes | None:
    header, separator, data = uri.partition(",")
    if not separator or not header.endswith(";base64"):
        return None
    if len(data) > MAX_ICON_SIZE * 4 // 3 + 4:
        return None
    try:
        picture = base64.b64decode(data + "=" * (-len(data) % 4), validate=True)
    except (binascii.Error, ValueError):
        return None
    return picture if len(picture) <= MAX_ICON_SIZE else None


def main_icon(charx: Charx) -> bytes | None:
    """
    The picture the card names as its main icon, if it is in the file: an
    entry of the archive or a data URI. A picture elsewhere (`https://`) is
    never fetched, and `ccdefault:` names none. None as well for a picture
    that is missing, too large or unreadable.
    """
    uri = _icon_uri(charx.card)
    if uri is None:
        return None
    if uri.startswith("data:"):
        return _data_uri_bytes(uri)
    for prefix in _EMBEDDED_PREFIXES:
        if uri.startswith(prefix):
            entry = charx.find(uri[len(prefix) :])
            if entry is None:
                return None
            try:
                return _read_entry(charx.archive, entry, MAX_ICON_SIZE)
            except NotCharx:
                return None
    return None
