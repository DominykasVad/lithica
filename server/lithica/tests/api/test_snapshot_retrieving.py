from datetime import datetime

import pytest

from lithica import db, errors, model
from lithica.tests.api.http import assert_error, ok


def snapshot_factory():
    snapshot = model.Snapshot()
    snapshot.creation_time = datetime(1999, 1, 1)
    snapshot.resource_type = "dummy"
    snapshot.resource_pkey = 1
    snapshot.resource_name = "dummy"
    snapshot.operation = "added"
    snapshot.data = "{}"
    return snapshot


@pytest.fixture(autouse=True)
def inject_config(config_injector):
    config_injector(
        {
            "privileges": {"snapshots:list": model.User.RANK_REGULAR},
        }
    )


def test_retrieving_multiple(user_factory, client):
    snapshot1 = snapshot_factory()
    snapshot2 = snapshot_factory()
    db.session.add_all([snapshot1, snapshot2])
    db.session.flush()
    result = ok(
        client.get(
            "/snapshots",
            user=user_factory(rank=model.User.RANK_REGULAR),
            query={"query": "", "offset": 0},
        )
    )
    assert result is not None
    assert result["query"] == ""
    assert result["offset"] == 0
    assert result["limit"] == 100
    assert result["total"] == 2
    assert len(result["results"]) == 2


def test_trying_to_retrieve_multiple_without_privileges(user_factory, client):
    assert_error(
        client.get(
            "/snapshots",
            user=user_factory(rank=model.User.RANK_ANONYMOUS),
            query={"query": "", "offset": 0},
        ),
        errors.AuthError,
    )


def test_snapshot_fits_its_response_model(
    user_factory, tag_factory, client, config_injector
):
    from lithica.api import resources
    from lithica.func import snapshots
    from lithica.tests.api.http import assert_fits

    config_injector(
        {
            "thumbnails": {"avatar_width": 30, "avatar_height": 30},
            "privileges": {"snapshots:list": model.User.RANK_REGULAR},
            "webhooks": [],
        }
    )
    user = user_factory(name="editor", rank=model.User.RANK_REGULAR)
    tag = tag_factory(names=["tag"])
    db.session.add_all([user, tag])
    db.session.flush()
    snapshots.create(tag, user)
    snapshots.create(tag, None)
    db.session.flush()

    listed = ok(client.get("/snapshots", user=user))
    assert listed["total"] == 2
    assert {snapshot["type"] for snapshot in listed["results"]} == {"tag"}
    assert {snapshot["id"] for snapshot in listed["results"]} == {"tag"}
    assert sorted(
        (snapshot["user"] or {}).get("name", "") for snapshot in listed["results"]
    ) == ["", "editor"]
    assert_fits(resources.Paged[resources.Snapshot], listed)
