"""Every file door uses the same current, book-free card identity."""

from copy import deepcopy

import pytest

from lithica import config, db, model
from lithica.func import documents, post_import, posts
from lithica.modules.cards import documents as card_documents
from lithica.modules.cards import jobs
from lithica.modules.cards.model import Card
from lithica.tests.api.http import assert_error, ok
from lithica.tests.modules import cards
from lithica.tests.modules.test_card_file_replace import replace
from lithica.tests.modules.test_card_upload_documents import upload


@pytest.mark.parametrize(
    "source", [cards.V1_CARD, cards.v2_card(), cards.v3_card(), None]
)
def test_extracted_and_document_keys_agree(site, user, source):
    client = site(["cards"])
    content = cards.charx() if source is None else cards.png_card(source)
    post_id = ok(
        client.post(
            "/posts", user=user, body={"safety": "safe"}, files={"content": content}
        )
    )["id"]
    data = documents.get(posts.get_post_by_id(post_id)).data
    assert db.session.get(Card, post_id).data_hash == card_documents.card_key(
        data["spec"], data["card"]
    )
    # Another carrier with the same data is refused too.
    changed = (
        cards.charx(card=cards.charx_card(None), icon=cards.picture(80))
        if source is None
        else cards.png_card(source, shade=80)
    )
    error = assert_error(
        client.post(
            "/posts", user=user, body={"safety": "safe"}, files={"content": changed}
        ),
        posts.PostAlreadyUploadedError,
    )
    assert str(post_id) in error["description"]


def test_import_checks_current_data_in_dry_and_real_runs(site, user, tmp_path):
    client = site(["cards"])
    post_id = upload(client, user, cards.charx_card(None))
    folder = tmp_path / "import"
    folder.mkdir()
    (folder / "card.charx").write_bytes(cards.charx())
    for dry in (True, False):
        result = post_import.import_folder(
            str(folder), user.name, "safe", [], dry_run=dry
        )
        assert result.count(post_import.SKIPPED) == 1
        assert str(post_id) in result.outcomes[0].detail


def test_replace_refuses_other_card_but_allows_own_data(site, user):
    client = site(["cards"])
    config.config["privileges"]["posts:edit:typed_relations"] = "regular"
    first = upload(client, user, cards.v2_card(name="First"))
    second = upload(client, user, cards.v2_card(name="Second"), shade=40)
    assert_error(
        replace(
            client, user, first, cards.png_card(cards.v2_card(name="Second"), shade=80)
        ),
        posts.PostAlreadyUploadedError,
    )
    assert (
        ok(
            replace(
                client,
                user,
                second,
                cards.png_card(cards.v2_card(name="Second"), shade=80),
            )
        )["post"]["id"]
        == second
    )


def test_document_edits_are_not_deduplicated_and_conversion_backfills(site, user):
    client = site(["cards"])
    first = upload(client, user, cards.v2_card(name="First"))
    second = upload(client, user, cards.v2_card(name="Second"), shade=40)
    data = deepcopy(documents.get(posts.get_post_by_id(first)).data)
    documents.write(posts.get_post_by_id(second), data, 0, user)
    row = db.session.get(Card, first)
    expected = row.data_hash
    row.data_hash = None
    db.session.flush()
    assert jobs.pending().count() == 1
    jobs.run({"after": 0})
    assert db.session.get(Card, first).data_hash == expected
    assert jobs.pending().count() == 0
    assert documents.get(posts.get_post_by_id(first)).version == 0


def test_hidden_data_duplicate_has_bare_error(site, user, user_factory):
    client = site(["cards"])
    upload(client, user, cards.v2_card(), tags=["nsfw"])
    config.config["visibility"] = "nsfw-login"
    config.config["privileges"].update(
        {"posts:create:anonymous": "anonymous", "tags:create": "anonymous"}
    )
    response = client.post(
        "/posts",
        user=user_factory(rank=model.User.RANK_ANONYMOUS),
        body={"safety": "safe", "anonymous": True},
        files={"content": cards.png_card(cards.v2_card(), shade=80)},
    )
    error = assert_error(response, posts.PostAlreadyUploadedError)
    assert error["description"] == "Post already uploaded."
