import threading
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from lithica import app as lithica_app
from lithica import config, errors
from lithica.func import file_uploads, posts


@pytest.fixture
def client():
    # not used as a context manager: the lifespan (startup work) does not run
    return TestClient(lithica_app.app, headers={"Accept": "application/json"})


def test_importing_the_app_does_not_start_it():
    # the startup work belongs to the lifespan; a second application object
    # can be built without it running
    assert lithica_app.create_app() is not lithica_app.app


@pytest.mark.parametrize("path", ["/no-such-path", "/no-such-path/", "/a/b/c"])
def test_unknown_path_is_answered_by_the_old_application(client, path):
    response = client.get(path)
    assert response.status_code == 404
    assert response.headers["content-type"] == "application/json"
    assert response.json() == {
        "name": "ValidationError",
        "title": "Not Found",
        "description": "Requested path %s was not found." % path,
    }


def test_old_application_still_checks_the_accept_header(client):
    response = client.get("/info", headers={"Accept": "text/html"})
    assert response.status_code == 406
    assert response.json()["name"] == "ValidationError"


def test_old_application_still_refuses_unknown_methods(client):
    response = client.request("PATCH", "/info")
    assert response.status_code == 405
    assert response.json()["title"] == "Method Not Allowed"


def test_no_redirect_for_a_trailing_slash(client):
    response = client.get("/info/", headers={"Accept": "text/html"})
    # answered (here: refused) by the route itself, not redirected to /info
    assert response.status_code == 406


def test_documentation_is_not_served(client):
    for path in ["/docs", "/redoc", "/openapi.json"]:
        assert client.get(path).status_code == 404


@pytest.fixture
def valid_config(config_injector, tmpdir):
    content = config._file_config("config.yaml.dist")
    content.update(
        {
            "secret": "5c6f0b6d1d5a4d0f9a2b",
            "data_dir": str(tmpdir),
            "data_url": "data/",
            "database": "postgresql://user:pass@host/db",
            "debug": 0,
            "show_sql": 0,
        }
    )
    config_injector(content)
    return content


@pytest.fixture
def no_logging_setup():
    # the real one installs a handler on the root logger for good
    with patch("lithica.app._configure_logging") as configure:
        yield configure


def _purge_threads() -> list[threading.Thread]:
    return [t for t in threading.enumerate() if t.name == "upload-purge"]


def test_startup_and_shutdown(valid_config, no_logging_setup):
    assert _purge_threads() == []
    with patch("lithica.func.file_uploads.purge_old_uploads_once") as purge:
        with TestClient(lithica_app.app) as client:
            no_logging_setup.assert_called_once_with()
            threads = _purge_threads()
            assert len(threads) == 1
            assert threads[0].daemon
            # the first purge runs right away, not after the first interval
            file_uploads.purge_old_uploads_once.assert_called_once_with()
            assert client.get("/no-such-path").status_code == 406
        threads[0].join(timeout=10)
        assert _purge_threads() == []
        purge.assert_called_once_with()


def test_refuses_to_start_with_the_default_secret(valid_config, no_logging_setup):
    valid_config["secret"] = config.default_secret()
    with pytest.raises(errors.ConfigError, match="default value"):
        with TestClient(lithica_app.app):
            pass
    assert _purge_threads() == []
    no_logging_setup.assert_not_called()


def test_refuses_to_start_with_smtp_and_no_domain(valid_config, no_logging_setup):
    valid_config["smtp"]["host"] = "mail.example.com"
    with pytest.raises(errors.ConfigError, match="'domain' is not set"):
        with TestClient(lithica_app.app):
            pass
    assert _purge_threads() == []


def test_starts_when_the_backfill_check_fails(valid_config, no_logging_setup, caplog):
    with (
        patch("lithica.func.file_uploads.purge_old_uploads_once"),
        patch(
            "lithica.func.posts.warn_about_pending_backfills",
            side_effect=RuntimeError("database is away"),
        ),
    ):
        with TestClient(lithica_app.app):
            posts.warn_about_pending_backfills.assert_called_once_with()
    assert "database is away" in caplog.text


def test_warns_about_pending_backfills_at_startup(
    valid_config, no_logging_setup, caplog, post_factory, session
):
    session.add(post_factory())
    session.commit()
    with patch("lithica.func.file_uploads.purge_old_uploads_once"):
        with TestClient(lithica_app.app):
            pass
    assert "lithica-admin backfill signatures" in caplog.text
