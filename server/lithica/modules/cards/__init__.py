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

from collections.abc import Iterator
from typing import BinaryIO

from lithica import registry
from lithica.modules.cards import card as card_format
from lithica.modules.cards import charx, png

NAME = "cards"

# raised when the shape of the payload changes
SCHEMA_VERSION = 1


def extract_png(
    _mime_type: str, handle: BinaryIO
) -> Iterator[registry.ExtractedContent]:
    """
    The card of a PNG file, if it has one. Where a picture carries both
    chunks, `ccv3` is the card and `chara` is ignored, also when the `ccv3`
    chunk cannot be read: programs write `chara` next to it as a copy for
    older programs, and a copy is not what was uploaded.
    """
    embedded = png.read(handle)
    for keyword in (png.V3_KEYWORD, png.V2_KEYWORD):
        if keyword in embedded.cards:
            break
    else:
        return
    card = card_format.decode(embedded.cards[keyword])
    kind = card_format.kind_of(card)
    if kind is None:
        return
    if keyword == png.V3_KEYWORD and kind != card_format.KIND_V3:
        # the chunk is for V3 cards; anything else in it is not a card
        return
    stored = card_format.stored(card)
    if stored is None:
        return
    yield registry.ExtractedContent(
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
            stored = card_format.stored(opened.card)
            assets = [
                {"path": entry.filename, "size": entry.file_size}
                for entry in opened.entries
                if entry.filename != charx.CARD_NAME and not entry.is_dir()
            ]
    except (charx.NotCharx, charx.Rejected):
        return
    if stored is None:
        return
    yield registry.ExtractedContent(
        card_format.KIND_V3,
        {"format": "charx", "chunk": None, "card": stored, "assets": assets},
    )


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
        registry.ContentKind(card_format.KIND_V1, SCHEMA_VERSION),
        registry.ContentKind(card_format.KIND_V2, SCHEMA_VERSION),
        registry.ContentKind(card_format.KIND_V3, SCHEMA_VERSION),
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
