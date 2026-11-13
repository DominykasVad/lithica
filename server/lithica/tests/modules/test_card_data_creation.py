"""Data imports resolve identities, preserve ownership and write atomically."""

import json
from copy import deepcopy

import pytest

from lithica import config, db, errors, model
from lithica.func import documents, post_metadata, posts
from lithica.modules.cards.model import CardLorebook, Lorebook
from lithica.tests.api.http import assert_error, ok
from lithica.tests.modules import cards
from lithica.tests.modules.test_card_upload_documents import upload


@pytest.fixture(autouse=True)
def privileges(site):
    config.config["privileges"].update(
        {
            "posts:edit:document": "regular",
            "posts:edit:external_ids": "regular",
            "posts:edit:typed_relations": "regular",
            "uploads:create": "regular",
        }
    )


def create(client, user, card=None, **options):
    return client.post(
        "/modules/cards/cards",
        user=user,
        body={"card": card or cards.v3_card(), "safety": "safe", **options},
    )


def external(id_):
    return [{"host": "test", "id": str(id_)}]


@pytest.mark.parametrize("card", [cards.V1_CARD, cards.v2_card(), cards.v3_card()])
def test_create_and_update_outcomes(site, user, card):
    client = site(["cards"])
    first = ok(create(client, user, card, externalIds=external(1), note="Import"))
    assert first["outcome"] == "created" and first["skippedImages"] == []
    post = posts.get_post_by_id(first["post"]["id"])
    assert post.kind == "card" and not posts.has_file(post)
    assert documents.get(post).version == 0
    assert documents.get_version(post, 0).note == "Import"
    assert (
        ok(create(client, user, card, externalIds=external(1)))["outcome"]
        == "unchanged"
    )
    changed = deepcopy(card)
    changed.get("data", changed)["description"] = "Updated"
    result = ok(
        create(
            client,
            user,
            changed,
            externalIds=external(1),
            safety="unsafe",
            tags=["ignored"],
            version=0,
        )
    )
    assert result["outcome"] == "updated"
    assert result["post"]["id"] == post.post_id
    assert post.safety == "safe" and "ignored" not in {t.first_name for t in post.tags}
    assert documents.get(post).version == 1
    assert documents.get_version(post, 1).note == "Updated from data."
    assert (
        create(client, user, changed, externalIds=external(1), version=0).status_code
        == 409
    )
    assert documents.get(post).version == 1


def test_hash_resolution_adds_ids_but_no_id_refuses_duplicate(site, user):
    client = site(["cards"])
    post_id = upload(client, user, cards.v3_card())
    assert_error(create(client, user), posts.PostAlreadyUploadedError)
    result = ok(create(client, user, externalIds=external(1)))
    assert result["post"]["id"] == post_id and result["outcome"] == "unchanged"
    ok(create(client, user, externalIds=external(2)))
    assert {
        (row.host, row.external_id)
        for row in posts.get_post_by_id(post_id).external_ids
    } == {("test", "1"), ("test", "2")}


def test_external_resolution_conflicts_and_wrong_kind(site, user):
    client = site(["cards"])
    first = ok(
        create(client, user, cards.v3_card(name="First"), externalIds=external(1))
    )
    second = ok(
        create(client, user, cards.v3_card(name="Second"), externalIds=external(2))
    )
    response = create(client, user, externalIds=external(1) + external(2))
    error = assert_error(response, post_metadata.ExternalIdTakenError)
    assert response.status_code == 409 and set(error) == {
        "name",
        "title",
        "description",
    }
    media = ok(
        client.post(
            "/posts",
            user=user,
            body={"safety": "safe"},
            files={"content": cards.picture(40)},
        )
    )
    post_metadata.replace_external_ids(
        posts.get_post_by_id(media["id"]), [("test", "media")], user
    )
    assert_error(
        create(client, user, externalIds=external("media")),
        post_metadata.ExternalIdTakenError,
    )
    assert first["post"]["id"] != second["post"]["id"]


def test_ten_cards_share_one_embedded_book_and_nsfw_is_separate(site, user):
    client = site(["cards"])
    ids = [
        ok(create(client, user, cards.v3_card(name=str(i))))["post"]["id"]
        for i in range(10)
    ]
    assert db.session.query(Lorebook).count() == 1
    assert db.session.query(CardLorebook).count() == 10
    book_id = documents.get(posts.get_post_by_id(ids[0])).data["lorebooks"][0]
    assert {r.lorebook_post_id for r in db.session.query(CardLorebook)} == {book_id}
    nsfw = ok(
        create(client, user, cards.v3_card(name="NSFW"), tags=["nsfw"], safety="unsafe")
    )
    other_book = posts.get_post_by_id(
        documents.get(posts.get_post_by_id(nsfw["post"]["id"])).data["lorebooks"][0]
    )
    assert other_book.post_id != book_id and other_book.safety == "unsafe"
    assert [t.first_name for t in other_book.tags] == ["nsfw"]


def test_explicit_lorebooks_and_replacement_of_links(site, user):
    client = site(["cards"])
    book = ok(
        client.post(
            "/modules/cards/lorebooks",
            user=user,
            body={"book": {"name": "Extra"}, "safety": "safe"},
        )
    )["post"]["id"]
    result = ok(create(client, user, lorebooks=[book, book], externalIds=external(1)))
    post = posts.get_post_by_id(result["post"]["id"])
    assert documents.get(post).data["lorebooks"][-1] == book
    assert len(documents.get(post).data["lorebooks"]) == 2
    ok(create(client, user, cards.v3_card(character_book={}), externalIds=external(1)))
    assert documents.get(post).data["lorebooks"] == []


def test_lorebook_resolution_versions_and_nsfw(site, user):
    client = site(["cards"])
    body = {
        "book": cards.LOREBOOK,
        "spec": "v3",
        "safety": "safe",
        "tags": ["manual"],
        "externalIds": external(1),
    }
    first = ok(client.post("/modules/cards/lorebooks", user=user, body=body))
    assert first["outcome"] == "created" and "skippedImages" not in first
    assert (
        ok(client.post("/modules/cards/lorebooks", user=user, body=body))["outcome"]
        == "unchanged"
    )
    changed = {**body, "book": {**cards.LOREBOOK, "name": "New"}, "version": 0}
    assert (
        ok(client.post("/modules/cards/lorebooks", user=user, body=changed))["outcome"]
        == "updated"
    )
    assert (
        client.post("/modules/cards/lorebooks", user=user, body=changed).status_code
        == 409
    )
    post = posts.get_post_by_id(first["post"]["id"])
    assert post.safety == "safe" and [t.first_name for t in post.tags] == ["manual"]
    body.pop("externalIds")
    ok(client.post("/modules/cards/lorebooks", user=user, body=body))
    assert_error(
        client.post("/modules/cards/lorebooks", user=user, body=body),
        posts.PostAlreadyUploadedError,
    )
    adopted = ok(
        client.post(
            "/modules/cards/lorebooks",
            user=user,
            body={**body, "externalIds": external(2)},
        )
    )
    assert adopted["outcome"] == "unchanged"
    assert (
        ok(
            client.post(
                "/modules/cards/lorebooks", user=user, body={**body, "tags": ["nsfw"]}
            )
        )["outcome"]
        == "created"
    )


@pytest.mark.parametrize(
    "privilege,options",
    [
        ("posts:create:identified", {}),
        ("tags:create", {"tags": ["new"]}),
        ("posts:edit:external_ids", {"externalIds": external(1)}),
    ],
)
def test_create_privileges_leave_no_rows(site, user, privilege, options):
    client = site(["cards"])
    config.config["privileges"][privilege] = "administrator"
    assert_error(create(client, user, **options), errors.AuthError)
    assert db.session.query(model.Post).count() == 0
    assert db.session.query(model.PostDocument).count() == 0


def test_document_privilege_and_validation_rollback(site, user):
    client = site(["cards"])
    first = ok(create(client, user, externalIds=external(1)))
    config.config["privileges"]["posts:edit:document"] = "administrator"
    assert_error(create(client, user, externalIds=external(1)), errors.AuthError)
    config.config["privileges"]["posts:edit:document"] = "regular"
    before = db.session.query(model.Post).count()
    assert_error(
        create(client, user, cards.v3_card(name="New"), lorebooks=[99999]),
        errors.ValidationError,
    )
    assert db.session.query(model.Post).count() == before
    assert documents.get(posts.get_post_by_id(first["post"]["id"])).version == 0


def test_hidden_identity_resolution_is_private(site, user, user_factory):
    client = site(["cards"])
    post_id = upload(client, user, cards.v3_card(), tags=["nsfw"])
    post_metadata.replace_external_ids(
        posts.get_post_by_id(post_id), [("test", "known")], user
    )
    db.session.commit()
    config.config["visibility"] = "nsfw-login"
    config.config["privileges"].update(
        {
            "posts:create:identified": "anonymous",
            "posts:edit:document": "anonymous",
            "posts:edit:external_ids": "anonymous",
        }
    )
    anonymous = user_factory(rank=model.User.RANK_ANONYMOUS)
    error = assert_error(create(client, anonymous), posts.PostAlreadyUploadedError)
    assert error["description"] == "Post already uploaded."
    assert set(error) == {"name", "title", "description"}
    for external_id in ("known", "unknown"):
        error = assert_error(
            create(client, anonymous, externalIds=external(external_id)),
            post_metadata.ExternalIdTakenError,
        )
        assert set(error) == {"name", "title", "description"}


@pytest.mark.parametrize(
    "options",
    [
        {"note": "a" * 257},
        {"note": "a\x00b"},
        {"note": "\ud800"},
        {"externalIds": [{"host": "Bad Host", "id": "1"}]},
    ],
)
def test_bad_options_leave_nothing(site, user, options):
    client = site(["cards"])
    # JSON escaping keeps the lone surrogate on the wire; httpx's json= encoder
    # would reject it in the client before the server sees the request.
    response = client.post(
        "/modules/cards/cards",
        user=user,
        files={
            "metadata": json.dumps(
                {"card": cards.v3_card(), "safety": "safe", **options}
            ).encode()
        },
    )
    assert_error(response, errors.ValidationError)
    assert db.session.query(model.Post).count() == 0
    assert db.session.query(model.PostDocumentVersion).count() == 0
