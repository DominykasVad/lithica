"""Kind edits and snapshots, with actual transaction isolation."""

import pytest

from lithica import config, db, model
from lithica.tests.api.http import ok
from lithica.tests.modules import cards
from lithica.tests.modules.test_cards_api import _upload


@pytest.fixture(autouse=True)
def session(query_logger, postgresql_db):
    # Snapshots compare against the previously committed version through a
    # separate session; a transaction wrapped around the test would hide it.
    db.session = postgresql_db.session
    postgresql_db.create_table(*model.Base.metadata.sorted_tables)
    try:
        yield postgresql_db.session
    finally:
        postgresql_db.reset_db()


def test_endpoint(site, user):
    client = site(["cards"])
    db.session.commit()
    config.config["privileges"]["posts:edit:kind"] = "regular"
    card = _upload(client, user, cards.png_card(cards.v2_card()))
    path = f"/post/{card['id']}/kind"
    before = db.session.query(model.Snapshot).count()
    assert (
        ok(
            client.put(
                path, user=user, body={"version": card["version"], "kind": "card"}
            )
        )["version"]
        == card["version"]
    )
    assert db.session.query(model.Snapshot).count() == before
    assert (
        client.put(path, user=user, body={"version": card["version"]}).status_code
        == 400
    )
    assert (
        client.put(path, user=user, body={"version": 999, "kind": "media"}).status_code
        == 409
    )
    assert (
        client.put(
            path, user=user, body={"version": card["version"], "kind": "nope"}
        ).json()["name"]
        == "InvalidPostKindError"
    )
    for kind in ["media", "card"]:
        card = ok(
            client.put(path, user=user, body={"version": card["version"], "kind": kind})
        )
        assert card["kind"] == kind
        latest = (
            db.session.query(model.Snapshot)
            .filter_by(
                resource_type="post", operation=model.Snapshot.OPERATION_MODIFIED
            )
            .order_by(model.Snapshot.snapshot_id.desc())
            .first()
        )
        assert latest.data["value"]["kind"]["new-value"] == kind
    for content, wanted in [(cards.png_with(), "card"), (cards.charx(), "media")]:
        post = _upload(client, user, content)
        answer = client.put(
            f"/post/{post['id']}/kind",
            user=user,
            body={"version": post["version"], "kind": wanted},
        )
        assert answer.status_code == 400
        assert "Supported kinds:" in answer.json()["description"]
    config.config["privileges"]["posts:edit:kind"] = "administrator"
    assert (
        client.put(
            path, user=user, body={"version": card["version"], "kind": "media"}
        ).status_code
        == 403
    )
