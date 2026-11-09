"""Post kinds across uploads, edits, extraction and administrative backfill."""

from dataclasses import replace

import pytest

from lithica import config, db, model, registry
from lithica.func import post_content, post_kinds
from lithica.tests.api.http import ok, shipped_config
from lithica.tests.modules import cards
from lithica.tests.modules.test_cards_api import _search, _upload
from lithica.tests.test_admin import admin as kind_admin  # noqa: F401


def _info(client, user):
    defaults = shipped_config(config.config["data_dir"])
    config.config["privileges"] = defaults["privileges"] | config.config["privileges"]
    config.config.update(defaults | config.config)
    return ok(client.get("/info", user=user))


@pytest.mark.parametrize(
    "content,kind",
    [
        (cards.png_card(cards.v2_card()), "card"),
        (cards.png_with(), "media"),
        (cards.charx(), "card"),
    ],
    ids=["card-png", "plain-png", "charx"],
)
def test_upload(site, user, content, kind):
    client = site(["cards"])
    assert _upload(client, user, content)["kind"] == kind
    assert _info(client, user)["postKinds"] == ["media", "card"]


def test_cards_off(site, user):
    client = site([])
    assert _upload(client, user, cards.png_card(cards.v2_card()))["kind"] == "media"
    assert _info(client, user)["postKinds"] == ["media"]


def test_replace_and_search(site, user):
    client = site(["cards"])
    card = _upload(client, user, cards.png_card(cards.v2_card()))
    plain = _upload(client, user, cards.png_with(shade=50))
    assert _search(client, user, "kind:card") == [card["id"]]
    assert _search(client, user, "kind:media") == [plain["id"]]
    assert _search(client, user, "-kind:card") == [plain["id"]]
    assert (
        client.get("/posts", user=user, query={"query": "kind:nope"}).status_code == 400
    )
    for content, expected in [
        (cards.png_with(), "media"),
        (cards.png_card(cards.v2_card()), "card"),
    ]:
        card = ok(
            client.put(
                f"/post/{card['id']}",
                user=user,
                body={"version": card["version"]},
                files={"content": content},
            )
        )
        assert card["kind"] == expected


def test_reextract_and_backfill(site, user, kind_admin):  # noqa: F811
    content = cards.png_card(cards.v2_card())
    client = site([])
    created = _upload(client, user, content)
    site(["cards"])
    post = db.session.get(model.Post, created["id"])
    assert post_content.reextract_post_contents(post, content)
    assert post.kind == "card"
    post.kind = "media"
    assert post_content.reextract_post_contents(post, content)
    assert post.kind == "media"
    assert kind_admin.main(["backfill", "kinds"]) == 0
    assert post.kind == "card"
    assert post_content.reextract_post_contents(post, cards.png_with())
    assert post.kind == "media"
    assert post_content.reextract_post_contents(post, content)
    assert post.kind == "card"
    original = [(row.kind, row.payload) for row in post.contents]
    module = registry.modules()[0]

    def fail(*args):
        raise RuntimeError("extractor failed")

    registry.use(
        [
            replace(
                module, extractors=[registry.Extractor(frozenset({"image/png"}), fail)]
            )
        ]
    )
    assert not post_content.reextract_post_contents(post, content)
    assert post.kind == "card"
    assert [(row.kind, row.payload) for row in post.contents] == original
    config.config["modules"] = []
    registry.use([])
    assert post_content.reextract_post_contents(post, content)
    assert kind_admin.main(["backfill", "kinds"]) == 0
    assert post.kind == "card"


def test_engine_video_and_unowned_rows(post_factory):
    post = post_factory()
    post.type = model.Post.TYPE_VIDEO
    post.contents = [model.PostContent(kind="unknown", payload={})]
    assert post_kinds.supported_kinds(post) == ["media"]
    assert post_kinds.derived_kind(post) == "media"
