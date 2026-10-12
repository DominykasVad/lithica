"""
The cards module: character cards for AI chat programs as posts.

A character card is a description of a character (who it is, how it
speaks, how a conversation with it opens, and often a lorebook) that chat
programs load. Cards travel as PNG pictures with the card's JSON in a text
chunk. This module reads the card out of an uploaded picture and keeps it
as extracted content of the post, of the kind `card_v1`, `card_v2` or
`card_v3` after the version of the card format.

A picture without a card, or with one that cannot be read, is an ordinary
picture: the module never refuses a PNG file.

Cards also travel as CHARX files: ZIP archives with the card as `card.json`
and its pictures beside it. The module makes them a file type of the site:
a post of the type `charx`, with the card's main icon as its thumbnail. See
lithica.modules.cards.charx for what is asked of such an archive.

A card that is too large to be stored (see MAX_PAYLOAD_SIZE) refuses the
upload, picture or CHARX file alike: a card that silently went missing
would leave a post that looks like a card and is none.

What is stored for a card (the payload):

    format   "png" or "charx"
    chunk    for a picture, the text chunk the card was in: "ccv3" or
             "chara"; null for a CHARX file
    card     the card's JSON as it was in the file, minus the binary data
             embedded in it (see lithica.modules.cards.card.stored)
    assets   the files that came with the card: path and size of each, never
             their data. For a picture, its `chara-ext-asset_:` chunks; for
             a CHARX file, the entries of the archive besides the card
"""

import json
from collections.abc import Iterator
from typing import BinaryIO

from lithica import registry
from lithica.modules.cards import card as card_format
from lithica.modules.cards import charx, png

NAME = "cards"

# raised when the shape of the payload changes
SCHEMA_VERSION = 1

# How large a stored card may be, as JSON, once the binary data embedded in
# it is taken out. Cards with lorebooks of thousands of entries are several
# megabytes of text; the engine's default of 1 MiB would lose them.
MAX_PAYLOAD_SIZE = 16 * 1024 * 1024


def _megabytes(size: int) -> str:
    return "%d MiB" % (size // (1024 * 1024))


def _content(kind: str, payload: registry.Payload) -> registry.ExtractedContent:
    """
    The content to store, or the refusal of the file if it is more than a
    card may be. The size is measured as the engine measures it.
    """
    size = len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
    if size > MAX_PAYLOAD_SIZE:
        raise registry.FileRejected(
            "The character card is larger than %s, also without the files "
            "embedded in it." % _megabytes(MAX_PAYLOAD_SIZE)
        )
    return registry.ExtractedContent(kind, payload)


def extract_png(
    _mime_type: str, handle: BinaryIO
) -> Iterator[registry.ExtractedContent]:
    """
    The card of a PNG file, if it has one. Where a picture carries both
    chunks, `ccv3` is the card: programs write `chara` next to it as a copy
    for older programs. Only where the `ccv3` chunk cannot be read as a V3
    card is a readable `chara` chunk taken instead.

    Raises registry.FileRejected for a card too large to be stored.
    """
    embedded = png.read(handle)
    for keyword in (png.V3_KEYWORD, png.V2_KEYWORD):
        if keyword not in embedded.cards:
            continue
        if keyword in embedded.oversized:
            raise registry.FileRejected(
                "The character card in the `%s` chunk of the picture is larger "
                "than %s."
                % (keyword.decode("ascii"), _megabytes(card_format.MAX_CARD_SIZE))
            )
        card = card_format.decode(embedded.cards[keyword])
        kind = card_format.kind_of(card)
        if kind is None:
            continue
        if keyword == png.V3_KEYWORD and kind != card_format.KIND_V3:
            # the chunk is for V3 cards; anything else in it is not a card
            continue
        stored = card_format.stored(card)
        if stored is None:
            continue
        yield _content(
            kind,
            {
                "format": "png",
                "chunk": keyword.decode("ascii"),
                "card": stored,
                "assets": [
                    {"path": asset.path.replace("\x00", ""), "size": asset.size}
                    for asset in embedded.assets
                ],
            },
        )
        return


def _charx_content(opened: charx.Charx) -> registry.ExtractedContent:
    """
    What is stored for a CHARX file. Raises charx.NotCharx for a card that
    cannot be stored at all, and registry.FileRejected for one too large.
    """
    stored = card_format.stored(opened.card)
    if stored is None:
        raise charx.NotCharx
    assets = [
        {"path": entry.filename, "size": entry.file_size}
        for entry in opened.entries
        if entry.filename != charx.CARD_NAME and not entry.is_dir()
    ]
    return _content(
        card_format.KIND_V3,
        {"format": "charx", "chunk": None, "card": stored, "assets": assets},
    )


def detect_charx(_head: bytes, handle: BinaryIO) -> bool:
    """
    Whether an upload is a CHARX file. A file that is none, a broken or
    another archive included, is left to the engine, which refuses what
    nobody knows. An archive with a card that breaks one of the limits is
    refused here, with the limit named.
    """
    try:
        with charx.opened(handle) as opened:
            charx.verify_icon(opened)
            # A CHARX file is accepted with its card or not at all: what the
            # extractor will store is made here once, to see that it can be.
            _charx_content(opened)
            return True
    except charx.NotCharx:
        return False
    except charx.Rejected as ex:
        raise registry.FileRejected("CHARX file refused: %s" % ex) from ex


def extract_charx(
    _mime_type: str, handle: BinaryIO
) -> Iterator[registry.ExtractedContent]:
    """The card of a CHARX file. The stored files passed detect_charx once."""
    try:
        with charx.opened(handle) as opened:
            content = _charx_content(opened)
    except charx.NotCharx:
        return
    except charx.Rejected as ex:
        raise registry.FileRejected("CHARX file refused: %s" % ex) from ex
    yield content


def charx_thumbnail(handle: BinaryIO) -> bytes | None:
    """The main icon of the card in a CHARX file, for the post's thumbnail."""
    try:
        with charx.opened(handle) as opened:
            return charx.main_icon(opened)
    except (charx.NotCharx, charx.Rejected):
        return None


module = registry.Module(
    name=NAME,
    content_kinds=[
        registry.ContentKind(kind, SCHEMA_VERSION, max_payload_size=MAX_PAYLOAD_SIZE)
        for kind in (card_format.KIND_V1, card_format.KIND_V2, card_format.KIND_V3)
    ],
    file_types=[
        registry.FileType(
            post_type=charx.POST_TYPE,
            mime_type=charx.MIME_TYPE,
            extension=charx.EXTENSION,
            detect=detect_charx,
            thumbnail=charx_thumbnail,
        )
    ],
    extractors=[
        registry.Extractor(frozenset({"image/png"}), extract_png),
        registry.Extractor(frozenset({charx.MIME_TYPE}), extract_charx),
    ],
)
