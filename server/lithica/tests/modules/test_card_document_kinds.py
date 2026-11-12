"""Card document validation and current projections are independent of files."""

from copy import deepcopy

import pytest

from lithica import db, errors
from lithica.func import documents, posts
from lithica.modules.cards.model import Card, CardLorebook, Lorebook
from lithica.tests.modules import cards


def test_kinds_and_restore(site, user):
    site(["cards"])
    book = posts.create_fileless_post("lorebook", user)
    db.session.flush()
    documents.create(
        book, "lorebook", {"spec": "card_v2", "book": cards.LOREBOOK}, user
    )
    post = posts.create_fileless_post("card", user)
    db.session.flush()
    card = cards.v2_card()
    del card["data"]["character_book"]
    data = {"spec": "card_v2", "card": card, "lorebooks": [book.post_id]}
    documents.create(post, "card", data, user)
    assert db.session.get(Card, post.post_id).greetings == 3
    assert db.session.get(Lorebook, book.post_id).entries == 2
    assert db.session.query(CardLorebook).one().lorebook_post_id == book.post_id
    changed = deepcopy(data)
    changed["card"]["data"]["creator"] = "Changed"
    documents.write(post, changed, 0, user)
    db.session.delete(book)
    db.session.flush()
    restored = documents.restore(post, 0, 1, user)
    assert restored.data["lorebooks"] == []
    assert db.session.query(CardLorebook).count() == 0
    assert db.session.get(Card, post.post_id).creator == "somebody"


@pytest.mark.parametrize("links", [[True], [1, 1], ["1"], list(range(101)), [{}]])
def test_invalid_links(site, user, links):
    site(["cards"])
    post = posts.create_fileless_post("card", user)
    db.session.flush()
    with pytest.raises(errors.ValidationError):
        documents.create(
            post,
            "card",
            {"spec": "card_v1", "card": cards.V1_CARD, "lorebooks": links},
            user,
        )
