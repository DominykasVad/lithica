"""Card documents and their current projections.

A later data shape must bump schema_version and validation must convert every
older shape: restoring history feeds old versions through validation too.
"""

from copy import deepcopy
from typing import cast

import sqlalchemy as sa

from lithica import db, model, registry
from lithica.func import visibility
from lithica.modules.cards import card as card_format
from lithica.modules.cards.model import Card, CardLorebook, Lorebook


def validate_card(data: registry.Payload) -> registry.Payload:
    """Validate current and (after a schema bump) convert every older shape."""
    spec = data.get("spec")
    card = data.get("card")
    books = data.get("lorebooks")
    if (
        spec not in card_format.KINDS
        or not isinstance(card, dict)
        or not isinstance(books, list)
    ):
        raise registry.DocumentRejected("Invalid card document.")
    ids = cast(list[object], books)
    if (
        len(ids) > 100
        or any(type(i) is not int for i in ids)
        or len(set(ids)) != len(ids)
    ):
        raise registry.DocumentRejected(
            "Lorebooks must be distinct integer IDs (at most 100)."
        )
    if "character_book" in card_format.fields_of(spec, cast(registry.Payload, card)):
        raise registry.DocumentRejected(
            "Card documents link their lorebooks separately."
        )
    # Validation is independent of the viewer: restore drops deleted books only.
    existing = set(
        db.session.execute(
            sa.select(model.Post.post_id)
            .where(model.Post.post_id.in_(ids), model.Post.kind == "lorebook")
            .execution_options(**{visibility.ALL_POSTS: True})
        ).scalars()
    )
    return {"spec": spec, "card": card, "lorebooks": [i for i in ids if i in existing]}


def validate_lorebook(data: registry.Payload) -> registry.Payload:
    """Validate current and (after a schema bump) convert every older shape."""
    if data.get("spec") not in (
        card_format.KIND_V2,
        card_format.KIND_V3,
    ) or not isinstance(data.get("book"), dict):
        raise registry.DocumentRejected("Invalid lorebook document.")
    return {"spec": data["spec"], "book": data["book"]}


def after_card(post_id: int, data: registry.Payload) -> None:
    summary = card_format.summary(data["spec"], data["card"])
    db.session.merge(
        Card(
            post_id=post_id,
            spec=data["spec"],
            name=summary["name"],
            creator=summary["creator"],
            greetings=summary["greetings"],
        )
    )
    db.session.execute(
        sa.delete(CardLorebook).where(CardLorebook.card_post_id == post_id)
    )
    db.session.add_all(
        [
            CardLorebook(card_post_id=post_id, lorebook_post_id=book_id, position=i)
            for i, book_id in enumerate(data["lorebooks"])
        ]
    )


def after_lorebook(post_id: int, data: registry.Payload) -> None:
    book = data["book"]
    db.session.merge(
        Lorebook(
            post_id=post_id,
            name=card_format.as_text(book.get("name"))[:200],
            entries=len(card_format.lorebook_entries({"character_book": book})),
        )
    )


def split_card(
    spec: str, stored: registry.Payload
) -> tuple[registry.Payload, registry.Payload | None]:
    card = deepcopy(stored)
    fields = card_format.fields_of(spec, card)
    book = fields.pop("character_book", None)
    return (
        {"spec": spec, "card": card, "lorebooks": []},
        {"spec": spec, "book": book}
        if spec != card_format.KIND_V1 and isinstance(book, dict) and book
        else None,
    )
