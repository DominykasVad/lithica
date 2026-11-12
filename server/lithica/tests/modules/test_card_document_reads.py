"""Document-backed card and lorebook reads respect visibility and restores."""

from copy import deepcopy

from lithica import config, db, model
from lithica.func import documents, posts
from lithica.modules.cards.model import Card
from lithica.tests.api.http import ok
from lithica.tests.modules import cards
from lithica.tests.modules.test_card_upload_documents import upload


def test_card_answer_matches_file_and_lorebook_endpoint(site, user):
    from lithica.modules.cards import api, view

    client = site(["cards"])
    source = cards.v2_card()
    post_id = upload(client, user, source)
    answer = ok(client.get(f"/modules/cards/post/{post_id}", user=user))
    expected = view.normalised(post_id, "card_v2", {"format": "png", "card": source})
    assert {k: v for k, v in answer.items() if k != "lorebooks"} == expected
    book_id = answer["lorebooks"][0]["id"]
    book = ok(client.get(f"/modules/cards/lorebook/{book_id}", user=user))
    assert book["cardIds"] == [post_id]
    assert book["lorebook"] == expected["lorebook"]
    from lithica.tests.api.http import assert_error

    assert_error(
        client.get(f"/modules/cards/lorebook/{post_id}", user=user),
        api.LorebookNotFoundError,
    )


def test_hidden_books_and_linking_cards(site, user, user_factory):
    from lithica.modules.cards import api
    from lithica.tests.api.http import assert_error

    client = site(["cards"])
    config.config["visibility"] = "nsfw-login"
    config.config["privileges"]["posts:view"] = model.User.RANK_ANONYMOUS
    anon = user_factory(rank=model.User.RANK_ANONYMOUS)
    post_id = upload(client, user, cards.v2_card())
    book_id = documents.get(posts.get_post_by_id(post_id)).data["lorebooks"][0]
    posts.update_post_tags(posts.get_post_by_id(post_id), ["nsfw"])
    db.session.commit()
    book = ok(client.get(f"/modules/cards/lorebook/{book_id}", user=anon))
    assert book["cardIds"] == []
    posts.update_post_tags(posts.get_post_by_id(post_id), [])
    posts.update_post_tags(posts.get_post_by_id(book_id), ["nsfw"])
    db.session.commit()
    card = ok(client.get(f"/modules/cards/post/{post_id}", user=anon))
    assert card["lorebooks"] == [] and card["lorebook"] is None
    assert_error(
        client.get(f"/modules/cards/lorebook/{book_id}", user=anon),
        api.LorebookNotFoundError,
    )


def test_multiple_books_merge_in_order(site, user):
    client = site(["cards"])
    post_id = upload(client, user, cards.v2_card())
    post = posts.get_post_by_id(post_id)
    original = documents.get(post)
    other = posts.create_fileless_post("lorebook", user)
    db.session.flush()
    documents.create(
        other,
        "lorebook",
        {
            "spec": "card_v3",
            "book": {"name": "Second", "entries": [{"content": "Last"}]},
        },
        user,
    )
    data = deepcopy(original.data)
    data["lorebooks"].append(other.post_id)
    documents.write(post, data, 0, user)
    db.session.commit()
    answer = ok(client.get(f"/modules/cards/post/{post_id}", user=user))
    assert answer["lorebook"]["name"] == cards.LOREBOOK["name"]
    assert answer["lorebook"]["entries"][-1]["content"] == "Last"
    assert [b["id"] for b in answer["lorebooks"]] == data["lorebooks"]
    assert db.session.get(Card, post_id).greetings == 3


def test_search_reads_document_and_restore(site, user):
    client = site(["cards"])
    post_id = upload(client, user, cards.v2_card())
    post = posts.get_post_by_id(post_id)
    changed = deepcopy(documents.get(post).data)
    changed["card"]["data"].update(
        creator="New author", first_mes="", alternate_greetings=["New"]
    )
    changed["lorebooks"] = []
    documents.write(post, changed, 0, user)
    db.session.commit()

    def hits(query):
        return [
            row["id"]
            for row in ok(
                client.get("/posts", user=user, query={"query": query, "fields": "id"})
            )["results"]
        ]

    assert hits("card-creator:New* card-greetings:1 card-lorebook:no") == [post_id]
    assert hits("card-creator:somebody") == []
    documents.restore(post, 0, 1, user)
    db.session.commit()
    assert hits("card-creator:somebody card-greetings:3 card-lorebook:yes") == [post_id]
    assert hits("card-creator:New*") == []


def test_unconverted_card_and_successful_reextract(site, user):
    from dataclasses import replace

    from lithica import registry
    from lithica.func import post_content
    from lithica.modules.cards import uploads

    client = site(["cards"])
    registry.use(
        [replace(module, after_file_or_kind=None) for module in registry.modules()]
    )
    source = cards.png_card(cards.v2_card())
    post_id = ok(
        client.post(
            "/posts", user=user, body={"safety": "safe"}, files={"content": source}
        )
    )["id"]
    response = client.get(f"/modules/cards/post/{post_id}", user=user)
    assert response.status_code == 404
    assert response.json()["name"] == "CardNotFoundError"
    assert "hasn't been converted" in response.json()["description"]
    download = client.get(f"/modules/cards/post/{post_id}/download", user=user)
    assert download.status_code == 200 and download.content == source
    assert (
        ok(client.get(f"/post/{post_id}", user=user, query={"fields": "card"}))["card"]
        is None
    )
    post = posts.get_post_by_id(post_id)
    post.contents = []
    db.session.flush()
    uploads.convert(post, user)
    assert db.session.get(model.PostDocument, post_id) is None
    assert post_content.reextract_post_contents(post, source)
    assert db.session.get(model.PostDocument, post_id) is None
    uploads.convert(post, user)
    db.session.commit()
    assert client.get(f"/modules/cards/post/{post_id}", user=user).status_code == 200
