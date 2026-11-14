"""Main avatars survive compatible restores and obey post visibility."""

import zlib
from collections.abc import Callable
from copy import deepcopy

from lithica import config, db, model
from lithica.func import documents, posts
from lithica.modules.cards.model import Card
from lithica.tests.api.http import ok
from lithica.tests.conftest import ApiClient
from lithica.tests.modules import cards
from lithica.tests.modules.test_card_file_replace import replace
from lithica.tests.modules.test_card_upload_documents import upload


def test_avatar_schema_restore_delete_and_replace(
    site: Callable[[list[str]], ApiClient], user: model.User
) -> None:
    client = site(["cards"])
    config.config["privileges"]["posts:edit:typed_relations"] = "regular"
    post_id = upload(client, user, cards.v2_card())
    image = ok(
        client.post(
            "/posts",
            user=user,
            body={"safety": "safe"},
            files={"content": cards.picture(40)},
        )
    )["id"]
    post = posts.get_post_by_id(post_id)
    document = documents.get(post)
    assert document.schema_version == 2 and document.data["avatar"] is None
    data = deepcopy(document.data)
    data["avatar"] = image
    documents.write(post, data, 0, user)
    assert db.session.get(Card, post_id).avatar_post_id == image
    assert (
        ok(client.get(f"/modules/cards/post/{post_id}", user=user))["avatar"]["id"]
        == image
    )
    ok(
        replace(
            client, user, post_id, cards.png_card(cards.v2_card(name="New"), shade=80)
        )
    )
    assert documents.get(post).data["avatar"] == image
    db.session.delete(posts.get_post_by_id(image))
    db.session.flush()
    db.session.expire_all()
    assert db.session.get(Card, post_id).avatar_post_id is None
    restored = documents.restore(post, 1, 2, user)
    assert restored.data["avatar"] is None
    # Restoring a real pre-bump history row goes through the same validator.
    old = deepcopy(data)
    old.pop("avatar")
    legacy = documents.get_version(post, 0)
    legacy.schema_version = 1
    legacy.data = zlib.compress(documents.encode_content(old))
    db.session.flush()
    restored = documents.restore(post, 0, 3, user)
    assert restored.schema_version == 2 and restored.data["avatar"] is None


def test_avatar_hidden_from_card_and_batched_field(
    site: Callable[[list[str]], ApiClient],
    user: model.User,
    user_factory: Callable[..., model.User],
) -> None:
    client = site(["cards"])
    config.config["privileges"]["posts:view"] = "anonymous"
    post_id = upload(client, user, cards.v2_card())
    image = ok(
        client.post(
            "/posts",
            user=user,
            body={"safety": "safe", "tags": ["nsfw"]},
            files={"content": cards.picture(40)},
        )
    )["id"]
    post = posts.get_post_by_id(post_id)
    data = deepcopy(documents.get(post).data)
    data["avatar"] = image
    documents.write(post, data, 0, user)
    config.config["visibility"] = "nsfw-login"
    anonymous = user_factory(rank=model.User.RANK_ANONYMOUS)
    answer = ok(client.get(f"/modules/cards/post/{post_id}", user=anonymous))
    assert answer["avatar"] is None
    answer = ok(
        client.get(f"/post/{post_id}", user=anonymous, query={"fields": "card"})
    )
    assert answer["card"]["avatar"] is None
    assert (
        ok(client.get(f"/post/{post_id}", user=user, query={"fields": "card"}))["card"][
            "avatar"
        ]["id"]
        == image
    )


def test_fileless_card_has_null_format(
    site: Callable[[list[str]], ApiClient], user: model.User
) -> None:
    client = site(["cards"])
    post = posts.create_fileless_post("card", user)
    db.session.flush()
    documents.create(
        post, "card", {"spec": "card_v1", "card": cards.V1_CARD, "lorebooks": []}, user
    )
    answer = ok(client.get(f"/modules/cards/post/{post.post_id}", user=user))
    assert answer["format"] is None
    assert answer["avatar"] is None
