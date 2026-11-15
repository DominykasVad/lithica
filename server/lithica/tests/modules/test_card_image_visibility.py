"""Existing media is rechecked while newly created own images stay attachable."""

from collections.abc import Callable

import pytest

from lithica import config, db, errors, model
from lithica.func import documents, posts, visibility
from lithica.modules.cards import assets, file_images, related_images
from lithica.modules.cards.model import CardImage
from lithica.tests.conftest import ApiClient
from lithica.tests.modules import cards
from lithica.tests.modules.test_card_file_images import upload

Site = Callable[[list[str]], ApiClient]


def test_existing_media_hidden_after_preparation_is_refused(
    site: Site, user: model.User, user_factory: Callable[..., model.User]
) -> None:
    client = site(["cards"])
    source_id = upload(client, user, cards.picture(50))
    upload(client, user, cards.picture(60), tags=["nsfw"])
    parent = posts.create_fileless_post("card", user)
    db.session.flush()
    config.config["visibility"] = "nsfw-login"
    config.config["privileges"]["posts:edit:typed_relations"] = "anonymous"
    anonymous = user_factory(rank=model.User.RANK_ANONYMOUS)
    with db.session_scope():
        visibility.begin_request()
        visibility.set_viewer(anonymous)
        prepared = related_images.prepare(
            [related_images.Image("gallery", post_id=source_id)], anonymous
        )
        posts.update_post_tags(posts.get_post_by_id(source_id), ["nsfw"])
        db.session.flush()
        with pytest.raises(
            errors.ValidationError, match="postId must name visible media"
        ):
            related_images.attach(parent, prepared, anonymous)
    assert (
        db.session.query(model.PostTypedRelation)
        .filter_by(to_post_id=parent.post_id)
        .count()
        == 0
    )


def test_hidden_mapped_main_does_not_supply_an_avatar(
    site: Site, user: model.User, user_factory: Callable[..., model.User]
) -> None:
    client = site(["cards"])
    content = cards.png_card(cards.v2_card())
    parent_id = upload(client, user, content)
    parent = posts.get_post_by_id(parent_id)
    document = documents.get(parent)
    avatar = document.data["avatar"]
    posts.update_post_tags(posts.get_post_by_id(avatar), ["nsfw"])
    documents.write(parent, {**document.data, "avatar": None}, document.version, user)
    db.session.commit()
    config.config["visibility"] = "nsfw-login"
    anonymous = user_factory(rank=model.User.RANK_ANONYMOUS)
    with db.session_scope(), assets.opened(content) as source:
        visibility.begin_request()
        visibility.set_viewer(anonymous)
        result = file_images.attach(parent, source, source.images, None)
    assert result.avatar is None and result.created == []
    assert document.data["avatar"] is None and document.version == 1
    assert db.session.query(CardImage).filter_by(card_post_id=parent_id).count() == 1


@pytest.mark.parametrize("uploader", ["anonymous", "deleted", "authenticated"])
@pytest.mark.parametrize("worker", ["images", "convert"])
def test_jobs_resolve_existing_media_as_card_uploader(
    site: Site,
    user: model.User,
    user_factory: Callable[..., model.User],
    uploader: str,
    worker: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    import base64
    import logging

    from lithica.modules.cards import jobs
    from lithica.modules.cards.model import Card

    client = site(["cards"])
    sprite = cards.picture(23)
    hidden_id = upload(client, user, sprite, tags=["nsfw"])
    content = cards.png_with(
        cards.text_chunk(
            b"ccv3",
            cards.encoded(
                cards.v3_card(
                    assets=[
                        {"type": "icon", "name": "main", "uri": "__asset:main"},
                        {"type": "emotion", "name": "happy", "uri": "__asset:happy"},
                    ]
                )
            ),
        ),
        cards.text_chunk(b"chara-ext-asset_:main", base64.b64encode(sprite)),
        cards.text_chunk(b"chara-ext-asset_:happy", base64.b64encode(sprite)),
    )
    config.config["visibility"] = "nsfw-login"
    config.config["privileges"]["posts:create:identified"] = "anonymous"
    config.config["privileges"]["tags:create"] = "anonymous"
    anonymous = user_factory(rank=model.User.RANK_ANONYMOUS)
    viewer = user if uploader == "authenticated" else anonymous
    with caplog.at_level(logging.INFO, logger="lithica.modules.cards.file_images"):
        parent_id = upload(client, viewer, content)
        parent = posts.get_post_by_id(parent_id)
        if uploader == "deleted":
            parent.user = None
            db.session.flush()
        initial_avatar = documents.get(parent).data["avatar"]
        payload = (
            db.session.query(model.Job).filter_by(type="cards-images").one().payload
        )
        # Workers start without request visibility, including when posts are
        # already in the identity map from earlier work in the same session.
        with db.session_scope():
            assert not visibility.hides_nsfw()
            if worker == "images":
                jobs.run_images(payload)
            else:
                jobs.run({"after": 0})
            assert not visibility.hides_nsfw()
    assert db.session.get(Card, parent_id).images_read
    relations = (
        db.session.query(model.PostTypedRelation).filter_by(to_post_id=parent_id).all()
    )
    if uploader == "authenticated":
        assert initial_avatar == hidden_id
        assert {relation.from_post_id for relation in relations} == {hidden_id}
        assert (
            db.session.query(CardImage).filter_by(card_post_id=parent_id).count() == 2
        )
    else:
        assert initial_avatar is None
        assert relations == []
        assert (
            db.session.query(CardImage).filter_by(card_post_id=parent_id).count() == 0
        )
        messages = [
            record.message
            for record in caplog.records
            if record.name == "lithica.modules.cards.file_images"
        ]
        assert messages == [
            "Card file images skipped: 1",
            "Card file images skipped: 1",
            "Card file images skipped: 1",
        ]
