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

What is stored for a card (the payload):

    format   "png"
    chunk    the text chunk the card was in: "ccv3" or "chara"
    card     the card's JSON as it was in the file, minus the binary data
             embedded in it (see lithica.modules.cards.card.stored)
    assets   the files embedded in the picture next to the card
             (`chara-ext-asset_:` chunks): path and size of each, never
             their data
"""

from collections.abc import Iterator
from typing import BinaryIO

from lithica import registry
from lithica.modules.cards import card as card_format
from lithica.modules.cards import png

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


module = registry.Module(
    name=NAME,
    content_kinds=[
        registry.ContentKind(card_format.KIND_V1, SCHEMA_VERSION),
        registry.ContentKind(card_format.KIND_V2, SCHEMA_VERSION),
        registry.ContentKind(card_format.KIND_V3, SCHEMA_VERSION),
    ],
    extractors=[registry.Extractor(frozenset({"image/png"}), extract_png)],
)
