import pytest
import sqlalchemy.event as sa_event
import sqlalchemy.exc as sa_exc

from lithica import db, errors, model
from lithica.func import site_settings, util, visibility
from lithica.tests.api.http import enabled_config


def test_precedence_reset_and_scope(config_injector):
    config_injector(enabled_config({"name": "Starting"}))
    with db.session_scope():
        assert site_settings.get("name") == "Starting"
        site_settings.update(1, {"name": "Stored"}, None)
        assert site_settings.get("name") == "Stored"
        assert site_settings.version() == 2
        site_settings.update(2, {"name": "Stored"}, None)
        assert site_settings.version() == 2
        site_settings.update(2, {"name": None}, None)
        assert site_settings.get("name") == "Starting"
        assert site_settings.version() == 3


@pytest.mark.parametrize(
    "name,value",
    [
        ("secret", "x"),
        ("modules", []),
        ("name", " "),
        ("name", "x" * 101),
        ("nsfw_tag", "x" * 129),
        ("default_rank", "administrator"),
        ("default_rank", "moderator"),
        ("password_reset_mail_interval", True),
        ("password_reset_mail_interval", -1),
        ("features.pools", 1),
    ],
)
def test_invalid_atomic(name, value):
    with db.session_scope():
        with pytest.raises(errors.ValidationError, match=name):
            site_settings.update(1, {"name": "Valid", name: value}, None)
        assert not site_settings.stored()
        assert site_settings.version() == 1


def test_stale_version():
    with db.session_scope():
        site_settings.update(1, {"name": "New"}, None)
        with pytest.raises(errors.IntegrityError):
            site_settings.update(1, {"name": "Stale"}, None)
        assert site_settings.get("name") == "New"


def test_invalid_stored_value(config_injector, caplog):
    config_injector(enabled_config({"visibility": "open"}))
    db.session.add(
        model.SiteSetting(
            name="visibility", value="removed-choice", last_edit_time=util.utcnow()
        )
    )
    db.session.flush()
    with db.session_scope():
        assert site_settings.get("visibility") == "open"
    assert "visibility" in caplog.text
    assert "removed-choice" not in caplog.text


def test_one_core_read_per_scope(session):
    queries = []

    def record(conn, cursor, statement, parameters, context, executemany):
        if "site_setting.value" in statement:
            queries.append(statement)

    sa_event.listen(session.get_bind(), "before_cursor_execute", record)
    try:
        for count in (1, 2):
            with db.session_scope():
                visibility.begin_request()
                for _ in range(10):
                    site_settings.get("visibility")
                    db.session.query(model.Post).all()
                assert len(queries) == count
    finally:
        sa_event.remove(session.get_bind(), "before_cursor_execute", record)


def test_snapshot_version_and_refresh_after_lock():
    with db.session_scope():
        before = site_settings.describe()
        with db.session_scope():
            site_settings.update(1, {"name": "Another writer"}, None)
            db.session.commit()
        # A cached response keeps its matching version, even after another save.
        assert site_settings.describe() == before
        # A later edit from the new version must refresh that older snapshot.
        site_settings.update(2, {"nsfw_tag": "adult"}, None)
        assert site_settings.get("name") == "Another writer"
        assert site_settings.get("nsfw_tag") == "adult"
        assert site_settings.describe()["version"] == 3


def test_valid_integer_replaces_invalid_boolean_even_when_equal():
    db.session.add(
        model.SiteSetting(
            name="password_reset_mail_interval",
            value=True,
            last_edit_time=util.utcnow(),
        )
    )
    db.session.flush()
    with db.session_scope():
        site_settings.update(1, {"password_reset_mail_interval": 1}, None)
        assert site_settings.version() == 2
        assert type(site_settings.get("password_reset_mail_interval")) is int


def test_version_table_refuses_a_second_row(session):
    with pytest.raises(sa_exc.IntegrityError), session.begin_nested():
        session.add(model.SiteSettingsVersion(id=2, version=1))
        session.flush()


def test_starting_does_not_supply_missing_config_values(config_injector):
    config_injector({})
    with pytest.raises(KeyError, match="visibility"):
        site_settings.starting("visibility")
    with pytest.raises(KeyError, match="features"):
        site_settings.starting("features.pools")
