from collections.abc import Callable

import pytest

from lithica import config, db, model
from lithica.func import documents, posts, util
from lithica.modules.cards import archived_links
from lithica.modules.cards.model import ArchivedLink, Card
from lithica.tests.api.http import ok
from lithica.tests.conftest import ApiClient
from lithica.tests.modules import cards
from lithica.tests.modules.test_card_data_creation import create
from lithica.tests.modules.test_card_image_links import EXPECTED, TEXT


@pytest.fixture
def client(site: Callable[[list[str]], ApiClient]) -> ApiClient:
    config.config["visibility"] = "nsfw-login"
    config.config["privileges"]["posts:view"] = "anonymous"
    config.config["privileges"]["posts:edit:document"] = "anonymous"
    return site(["cards"])


def test_replace_visible_archives_and_keep_other_text(
    client: ApiClient, user: model.User
) -> None:
    visible = ok(
        client.post(
            "/posts",
            user=user,
            body={"safety": "safe"},
            files={"content": cards.picture(30)},
        )
    )["id"]
    hidden = ok(
        client.post(
            "/posts",
            user=user,
            body={"safety": "unsafe", "tags": ["nsfw"]},
            files={"content": cards.picture(40)},
        )
    )["id"]
    hidden_url = "https://images.test/hidden"
    failed_url = "https://images.test/failed"
    new_url = "https://images.test/new"
    text = TEXT + "".join(
        f"![leave]({url}) " for url in (hidden_url, failed_url, new_url)
    )
    post_id = ok(create(client, user, cards.v3_card(first_mes=text)))["post"]["id"]
    post = posts.get_post_by_id(post_id)
    row = db.session.get(Card, post_id)
    previous = row.data_hash
    for url, target in {
        **dict.fromkeys(EXPECTED, visible),
        hidden_url: hidden,
        failed_url: None,
    }.items():
        db.session.add(
            ArchivedLink(
                card_post_id=post_id,
                url=url,
                url_hash=archived_links.url_hash(url),
                status="archived" if target is not None else "failed",
                reason=None if target is not None else "failed",
                post_id=target,
                attempts=1,
                last_attempt_time=util.utcnow(),
            )
        )
    db.session.commit()

    path = f"/modules/cards/post/{post_id}/archived-links/replace"
    assert client.post(path, body={}).status_code == 400
    result = ok(client.post(path, body={"version": 0}))
    assert result["post"]["id"] == post_id
    assert result["replaced"] == len(EXPECTED)
    doc = documents.get(post)
    expected = text
    for url in EXPECTED:
        expected = expected.replace(
            url.replace("&", "&amp;"), f"lithica:post/{visible}"
        )
    assert doc.data["card"]["data"]["first_mes"] == expected
    assert doc.version == 1 and row.data_hash != previous
    assert (
        documents.get_version(post, 1).note
        == "Archived links replaced with Lithica references."
    )
    assert (
        db.session.query(ArchivedLink).filter_by(card_post_id=post_id).count()
        == len(EXPECTED) + 2
    )

    assert client.post(path, body={"version": 0}).status_code == 409
    assert ok(client.post(path, body={"version": 1}))["replaced"] == 0
    assert doc.version == 1
    config.config["privileges"]["posts:edit:document"] = "regular"
    assert client.post(path, body={"version": 1}).status_code == 403
