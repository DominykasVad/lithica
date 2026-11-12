"""Current documents and visibility-aware lorebook composition."""

from copy import deepcopy
from typing import Any, cast

# Any: heterogeneous JSON book data, normalised at the API boundary.
import sqlalchemy as sa

from lithica import db, model
from lithica.modules.cards.model import CardLorebook


def visible_books(card_id: int) -> list[tuple[int, dict[str, Any]]]:
    return list(
        db.session.execute(
            sa.select(model.Post.post_id, model.PostDocument.data)
            .join(CardLorebook, CardLorebook.lorebook_post_id == model.Post.post_id)
            .join(model.PostDocument, model.PostDocument.post_id == model.Post.post_id)
            .where(CardLorebook.card_post_id == card_id, model.Post.kind == "lorebook")
            .order_by(CardLorebook.position)
        ).tuples()
    )


def merge_books(books: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Merge raw books in link order; export uses the same composition."""
    if not books:
        return None
    merged = deepcopy(books[0])
    entries: list[object] = []
    for book in books:
        raw = book.get("entries")
        if isinstance(raw, list):
            entries.extend(cast(list[object], raw))
    merged["entries"] = entries
    return merged
