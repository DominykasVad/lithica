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

Which chunk is the card. A picture may carry more than one card chunk: a
`ccv3` chunk with a `chara` copy for older programs beside it, and often
several chunks with the same keyword. The card is the first `ccv3` chunk
that can be read as a V3 card, or else the first `chara` chunk that can be
read as a card. Among chunks with the same keyword the first readable one
is the card: a site that hosts cards (Chub, for one) writes its current
version of the card first and leaves the chunk of the picture that was
uploaded to it behind it, older and often with fewer tags and another
lorebook. Position decides, not size: the current version is not always
the larger one. A chunk that cannot be read as a card (bad base64, bad
JSON, the wrong shape) is passed over for the next one. The chunks that
were not used are listed in the payload, without their content.

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
    ignoredChunks
             the card chunks of a picture that were not used, in the order
             of the file: keyword, position (the how-manyth chunk of the
             file, from 0) and size in bytes of each, never their content.
             Empty for a CHARX file
    summary  name, creator, number of greetings and of lorebook entries: what
             lists and the search need, so that they need not read the card

Tags. A post gets tags from its card when the card is uploaded:

- the card's creator, in the tag category `creator`;
- the card's own tags, in the site's default category.

Names are made to fit: lower case, whitespace as `_`; a name the site's
rule for tag names still refuses is left out. The module does not create
the `creator` category: the site's administrator does, once, with the
colour and order the site wants. Until then the engine's rule for a
missing category applies and creators are created in the default category,
where they stay until someone moves them. As with every automatic tag,
tags are added when the file is uploaded or replaced and never taken away,
and `lithica-admin reextract` does not tag.

Search. `card-creator:<pattern>`, `card-spec:v1|v2|v3`,
`card-format:png|charx`, `card-lorebook:yes|no` and
`card-greetings:<number or range>` find posts by their card.

API. The post field `card` (only when asked for in `fields`) is the
summary of a post's card. `GET modules/cards/post/<id>` is the card read
for a viewer, and `GET modules/cards/post/<id>/download` the file.
"""

import json
from collections.abc import Iterator, Mapping, Sequence
from typing import BinaryIO, cast

from lithica import registry
from lithica.func import tag_categories
from lithica.modules.cards import api, charx, png, search
from lithica.modules.cards import card as card_format

NAME = "cards"

# Raised when the shape of the payload changes. Rows of an older version
# lack what was added until `lithica-admin reextract` has read their files
# again.
#   2: `summary` was added
#   3: `ignoredChunks` was added
SCHEMA_VERSION = 3

# the tag category the creator of a card is put in
CREATOR_CATEGORY = "creator"

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


def _payload(
    kind: str,
    file_format: str,
    chunk: str | None,
    card: dict[str, object],
    assets: list[dict[str, object]],
    ignored_chunks: list[dict[str, object]],
) -> registry.Payload:
    return {
        "format": file_format,
        "chunk": chunk,
        "card": card,
        "assets": assets,
        "ignoredChunks": ignored_chunks,
        "summary": card_format.summary(kind, card),
    }


def auto_tag(contents: Sequence[registry.ExtractedContent]) -> Mapping[str, list[str]]:
    """The tags a post gets from its card; see the module's description."""
    for content in contents:
        card = content.payload.get("card")
        if content.kind in card_format.KINDS and isinstance(card, dict):
            break
    else:
        return {}
    card = cast(dict[str, object], card)
    try:
        default_category = tag_categories.get_default_category_name()
    except tag_categories.TagCategoryNotFoundError:
        # a site without categories cannot have tags; the engine says so
        default_category = "default"
    tags: dict[str, list[str]] = {}
    creator = card_format.creator_tag(content.kind, card)
    if creator:
        tags[CREATOR_CATEGORY] = [creator]
    own = card_format.card_tags(content.kind, card)
    if own:
        tags.setdefault(default_category, []).extend(own)
    return tags


def _card_of(
    handle: BinaryIO, chunk: png.CardChunk
) -> tuple[str, dict[str, object]] | None:
    """
    The card in a chunk, as its kind and what is stored of it, or None if
    the chunk cannot be read as a card. Raises registry.FileRejected for a
    chunk too large to be read.
    """
    keyword = chunk.keyword.decode("ascii")
    try:
        text = png.read_text(handle, chunk)
    except png.Oversized as ex:
        raise registry.FileRejected(
            "The character card in the `%s` chunk of the picture is larger than %s."
            % (keyword, _megabytes(card_format.MAX_CARD_SIZE))
        ) from ex
    if text is None:
        return None
    card = card_format.decode(text)
    kind = card_format.kind_of(card)
    if kind is None:
        return None
    if chunk.keyword == png.V3_KEYWORD and kind != card_format.KIND_V3:
        # the chunk is for V3 cards; anything else in it is not a card
        return None
    stored = card_format.stored(card)
    if stored is None:
        return None
    return kind, stored


def extract_png(
    _mime_type: str, handle: BinaryIO
) -> Iterator[registry.ExtractedContent]:
    """
    The card of a PNG file, if it has one: the first `ccv3` chunk that can
    be read as a V3 card, or else the first `chara` chunk that can be read
    as a card (see "Which chunk is the card" in the module's description).
    The card chunks that were not used are listed in the payload.

    Raises registry.FileRejected for a card too large to be stored.
    """
    embedded = png.read(handle)
    candidates = [
        chunk
        for keyword in (png.V3_KEYWORD, png.V2_KEYWORD)
        for chunk in embedded.cards
        if chunk.keyword == keyword
    ]
    for chunk in candidates:
        found = _card_of(handle, chunk)
        if found is None:
            continue
        kind, stored = found
        assets: list[dict[str, object]] = [
            {"path": asset.path.replace("\x00", ""), "size": asset.size}
            for asset in embedded.assets
        ]
        ignored: list[dict[str, object]] = [
            {
                "keyword": other.keyword.decode("ascii"),
                "position": other.position,
                "size": other.size,
            }
            for other in embedded.cards
            if other is not chunk
        ]
        yield _content(
            kind,
            _payload(
                kind, "png", chunk.keyword.decode("ascii"), stored, assets, ignored
            ),
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
    assets: list[dict[str, object]] = [
        {"path": entry.filename, "size": entry.file_size}
        for entry in opened.entries
        if entry.filename != charx.CARD_NAME and not entry.is_dir()
    ]
    return _content(
        card_format.KIND_V3,
        _payload(card_format.KIND_V3, "charx", None, stored, assets, []),
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
    router=api.router,
    auto_tag=auto_tag,
    search_filters=search.FILTERS,
    requested_post_fields={"card": api.card_field},
    post_field_schemas={"card": api.CardSummary},
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
