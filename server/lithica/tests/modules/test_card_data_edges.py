"""Integration edges of data cards, original carriers, and hash backfills."""

from collections.abc import Callable
from pathlib import Path

from lithica import config, db, model
from lithica.func import documents, post_import, post_kinds, posts
from lithica.modules.cards import jobs
from lithica.modules.cards.model import Card, CardLorebook
from lithica.tests.api.http import ok
from lithica.tests.conftest import ApiClient
from lithica.tests.modules import cards
from lithica.tests.modules.test_card_data_creation import (
    create,
    external,
    privileges,  # noqa: F401
)
from lithica.tests.modules.test_card_file_replace import replace
from lithica.tests.modules.test_card_related_images import token

Site = Callable[[list[str]], ApiClient]


def test_file_upload_prefers_card_data_over_its_media_carrier(
    site: Site, user: model.User, tmp_path: Path
) -> None:
    client = site(["cards"])
    content = cards.png_card(cards.v3_card())
    uploaded = token(client, user, content)
    answer = ok(
        create(
            client,
            user,
            images=[{"role": "avatar", "token": uploaded}],
            externalIds=external(1),
        )
    )
    post_id = answer["post"]["id"]
    avatar_id = documents.get(posts.get_post_by_id(post_id)).data["avatar"]
    response = client.post(
        "/posts", user=user, body={"safety": "safe"}, files={"content": content}
    )
    assert response.status_code == 400
    assert response.json()["name"] == "PostAlreadyUploadedError"
    assert response.json()["otherPostId"] == post_id != avatar_id
    folder = tmp_path / "import"
    folder.mkdir()
    (folder / "card.png").write_bytes(content)
    for dry in (True, False):
        result = post_import.import_folder(
            str(folder), user.name, "safe", [], dry_run=dry
        )
        assert result.count(post_import.SKIPPED) == 1
        assert result.outcomes[0].detail == f"Post already uploaded ({post_id})"


def test_backfill_only_updates_hash_when_linked_book_was_deleted(
    site: Site, user: model.User
) -> None:
    client = site(["cards"])
    post_id = ok(create(client, user))["post"]["id"]
    document = documents.get(posts.get_post_by_id(post_id))
    book_id = document.data["lorebooks"][0]
    row = db.session.get(Card, post_id)
    assert row is not None
    expected = row.data_hash
    db.session.delete(posts.get_post_by_id(book_id))
    row.data_hash = None
    db.session.flush()
    assert db.session.query(CardLorebook).count() == 0
    jobs.run({"after": 0})
    assert row.data_hash == expected and document.version == 0
    assert db.session.query(CardLorebook).count() == 0
    assert jobs.pending().count() == 0


def test_fileless_card_can_gain_a_file_and_keep_its_avatar(
    site: Site, user: model.User
) -> None:
    client = site(["cards"])
    uploaded = token(client, user, cards.picture(80))
    post_id = ok(create(client, user, images=[{"role": "avatar", "token": uploaded}]))[
        "post"
    ]["id"]
    post = posts.get_post_by_id(post_id)
    avatar = documents.get(post).data["avatar"]
    answer = ok(
        replace(client, user, post_id, cards.png_card(cards.v3_card(name="New")))
    )
    assert answer["keptPostId"] is None
    assert posts.has_file(post) and post.kind == "card"
    assert documents.get(post).version == 1
    assert documents.get(post).data["avatar"] == avatar


def test_kind_promotion_cannot_duplicate_an_imported_card(
    site: Site, user: model.User
) -> None:
    client = site(["cards"])
    config.config["privileges"]["posts:edit:kind"] = "regular"
    uploaded = token(client, user, cards.png_card(cards.v3_card()))
    parent = ok(create(client, user, images=[{"role": "avatar", "token": uploaded}]))[
        "post"
    ]["id"]
    image_id = documents.get(posts.get_post_by_id(parent)).data["avatar"]
    image = posts.get_post_by_id(image_id)
    response = client.put(
        f"/post/{image_id}/kind",
        user=user,
        body={"version": image.version, "kind": "card"},
    )
    assert response.status_code == 400
    assert response.json()["name"] == "PostAlreadyUploadedError"
    assert response.json()["otherPostId"] == parent
    db.session.rollback()
    image = posts.get_post_by_id(image_id)
    assert (
        image.kind == "media" and db.session.get(model.PostDocument, image_id) is None
    )
    post_kinds.derive_existing(image)
    assert image.kind == "media" and db.session.query(Card).count() == 1


def test_promoted_avatar_is_hidden_from_detail_and_summary(
    site: Site, user: model.User
) -> None:
    client = site(["cards"])
    config.config["privileges"]["posts:edit:kind"] = "regular"
    uploaded = token(client, user, cards.png_card(cards.v3_card(name="Different card")))
    parent = ok(create(client, user, images=[{"role": "avatar", "token": uploaded}]))[
        "post"
    ]["id"]
    image_id = documents.get(posts.get_post_by_id(parent)).data["avatar"]
    image = posts.get_post_by_id(image_id)
    ok(
        client.put(
            f"/post/{image_id}/kind",
            user=user,
            body={"version": image.version, "kind": "card"},
        )
    )
    assert ok(client.get(f"/modules/cards/post/{parent}", user=user))["avatar"] is None
    assert (
        ok(client.get(f"/post/{parent}", user=user, query={"fields": "card"}))["card"][
            "avatar"
        ]
        is None
    )
