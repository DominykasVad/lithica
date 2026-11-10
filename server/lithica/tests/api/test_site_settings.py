import pytest

from lithica import model
from lithica.func import site_settings
from lithica.tests.api.http import shipped_config


@pytest.fixture
def site(config_injector, tmpdir, user_factory):
    config_injector(shipped_config(str(tmpdir.mkdir("data"))))
    return user_factory(rank=model.User.RANK_ADMINISTRATOR)


def test_settings_roundtrip(client, site):
    answer = client.get("/site-settings", user=site)
    assert answer.status_code == 200
    initial = answer.json()
    assert initial["version"] == 1
    assert {item["name"] for item in initial["settings"]} == set(site_settings.SETTINGS)
    assert not any(item["stored"] for item in initial["settings"])
    updated = client.put(
        "/site-settings", user=site, body={"version": 1, "values": {"name": "New site"}}
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["version"] == 2
    assert client.get("/info", user=site).json()["config"]["name"] == "New site"
    assert (
        client.put(
            "/site-settings",
            user=site,
            body={"version": 1, "values": {"name": "stale"}},
        ).status_code
        == 409
    )
    reset = client.put(
        "/site-settings", user=site, body={"version": 2, "values": {"name": None}}
    )
    assert reset.status_code == 200
    assert not any(item["stored"] for item in reset.json()["settings"])


def test_regular_user_refused(client, site, user_factory):
    user = user_factory()
    assert client.get("/site-settings", user=user).status_code == 403
    assert (
        client.put(
            "/site-settings", user=user, body={"version": 1, "values": {}}
        ).status_code
        == 403
    )


@pytest.mark.parametrize("method", ["get", "put"])
def test_admin_app_token_refused(client, site, method, monkeypatch):
    monkeypatch.setattr(
        "lithica.func.app_token_rights.current_rights", lambda: ("read", "write")
    )
    kwargs = {"body": {"version": 1, "values": {}}} if method == "put" else {}
    answer = getattr(client, method)("/site-settings", user=site, **kwargs)
    assert answer.status_code == 403, answer.text


def test_concurrent_edits_use_one_version(config_injector, tmpdir, committing_session):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from lithica import db
    from lithica.func import util

    config_injector(shipped_config(str(tmpdir.mkdir("concurrent-data"))))
    barrier = Barrier(2)

    def edit(name: str) -> str:
        from lithica import errors

        with db.session_scope():
            # Both callers have loaded the same version before either updates.
            assert site_settings.version() == 1
            site_settings.get("name")
            barrier.wait(timeout=10)
            try:
                site_settings.update(1, {"name": name}, None)
                db.session.commit()
                return "saved"
            except errors.IntegrityError:
                db.session.rollback()
                return "conflict"

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(edit, ["One", "Two"])) == ["conflict", "saved"]
    with db.session_scope():
        assert site_settings.version() == 2
        assert site_settings.get("name") in ("One", "Two")
        assert db.session.query(model.SiteSetting).one().last_edit_time <= util.utcnow()
