"""A whole library imports twice without growing per-create query counts."""

from collections.abc import Callable

import sqlalchemy as sa
import sqlalchemy.event as sa_event

from lithica import db, model, registry
from lithica.modules.cards.model import CardLorebook, Lorebook
from lithica.tests.api.http import ok
from lithica.tests.conftest import ApiClient
from lithica.tests.modules import cards
from lithica.tests.modules.test_card_data_creation import (
    create,
    external,
    privileges,  # noqa: F401
)
from lithica.tests.modules.test_card_related_images import token


def test_bulk_import_twice(
    site: Callable[[list[str]], ApiClient],
    user: model.User,
    record_property: Callable[[str, object], None],
) -> None:
    client = site(["cards"])
    # Payloads are heterogeneous JSON bodies retained for the second API run.
    bodies: list[registry.Payload] = []
    ids: list[int] = []
    query_counts: list[int] = []
    for index in range(200):
        # Each tenth card shares a book; the others have a book of their own.
        book = (
            cards.LOREBOOK
            if (index + 1) % 10 == 0
            else {**cards.LOREBOOK, "name": f"Book {index}"}
        )
        card = cards.v3_card(name=f"Card {index}", character_book=book)
        images = []
        for role_index, role in enumerate(
            ("avatar", "gallery", "expression", "expression")
        ):
            content = (
                cards.picture((index * 4 + role_index) % 256)
                + index.to_bytes(2, "big")
                + bytes([role_index])
            )
            images.append(
                {
                    "role": role,
                    "token": token(client, user, content),
                    **(
                        {"label": f"Expression {role_index}"}
                        if role == "expression"
                        else {}
                    ),
                }
            )
        body: registry.Payload = {
            "card": card,
            "images": images,
            "externalIds": external(f"bulk-{index}"),
        }
        bodies.append(body)
        count = 0

        def queried(*_args: object) -> None:
            nonlocal count
            count += 1

        sa_event.listen(sa.engine.Engine, "before_cursor_execute", queried)
        try:
            answer = ok(create(client, user, **body))
        finally:
            sa_event.remove(sa.engine.Engine, "before_cursor_execute", queried)
        assert answer["outcome"] == "created" and answer["skippedImages"] == []
        ids.append(answer["post"]["id"])
        query_counts.append(count)
    count_before = db.session.query(model.Post).count()
    assert count_before == 200 + 800 + 181
    assert db.session.query(Lorebook).count() == 181
    shared = (
        db.session.query(CardLorebook.lorebook_post_id)
        .group_by(CardLorebook.lorebook_post_id)
        .having(sa.func.count() == 20)
        .one()[0]
    )
    assert shared is not None
    assert query_counts[-1] <= query_counts[0]
    record_property("create_queries_card_1", query_counts[0])
    record_property("create_queries_card_200", query_counts[-1])
    record_property("posts_after_first_run", count_before)
    changed = {0, 40, 80, 120, 160}
    for index, body in enumerate(bodies):
        if index in changed:
            body["card"]["data"]["description"] = f"Changed {index}"
        answer = ok(create(client, user, **body))
        assert answer["post"]["id"] == ids[index]
        assert answer["outcome"] == ("updated" if index in changed else "unchanged")
        assert answer["skippedImages"] == []
    assert db.session.query(model.Post).count() == count_before
    assert db.session.query(model.PostTypedRelation).count() == 800
    versions = (
        db.session.query(model.PostDocument.version)
        .filter(model.PostDocument.kind == "card")
        .all()
    )
    assert sorted(v[0] for v in versions) == [0] * 195 + [1] * 5
    assert (
        db.session.query(model.PostDocumentVersion)
        .filter(model.PostDocumentVersion.post_id.in_(ids))
        .count()
        == 205
    )
