import pytest
import sqlalchemy.event as sa_event

from lithica import db, errors, model
from lithica.func import site_settings, util, visibility


def test_precedence_reset_and_scope(config_injector):
    config_injector({"name": "Starting"})
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
    config_injector({"visibility": "open"})
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
        if "FROM site_setting" in statement:
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
