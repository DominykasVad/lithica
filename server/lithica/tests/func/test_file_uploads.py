import os
import threading
from datetime import timedelta
from unittest.mock import patch

import pytest

from lithica.func import file_uploads, files, util


@pytest.fixture(autouse=True)
def inject_config(tmpdir, config_injector):
    config_injector({"data_dir": str(tmpdir.mkdir("data"))})


def _stored_names():
    return sorted(entry.name for entry in files.scan("temporary-uploads"))


def _later(minutes):
    return util.utcnow() + timedelta(minutes=minutes)


def test_save_and_get():
    token = file_uploads.save(b"content")
    assert file_uploads.get(token) == b"content"
    assert _stored_names() == [token + ".dat"]
    # the same content gives the same token and is stored once
    assert file_uploads.save(b"content") == token
    assert _stored_names() == [token + ".dat"]


def test_get_unknown_token():
    assert file_uploads.get("0" * 40) is None


def test_purge_without_uploads():
    file_uploads.purge_old_uploads()


def test_purge_keeps_fresh_uploads(fake_datetime):
    token = file_uploads.save(b"content")
    with fake_datetime(_later(file_uploads.MAX_MINUTES - 1)):
        file_uploads.purge_old_uploads()
    assert file_uploads.get(token) == b"content"


def test_purge_deletes_old_uploads(fake_datetime):
    token = file_uploads.save(b"content")
    with fake_datetime(_later(file_uploads.MAX_MINUTES + 1)):
        file_uploads.purge_old_uploads()
    assert file_uploads.get(token) is None
    assert _stored_names() == []


def test_purge_is_repeatable(fake_datetime):
    file_uploads.save(b"content")
    with fake_datetime(_later(file_uploads.MAX_MINUTES + 1)):
        file_uploads.purge_old_uploads()
        file_uploads.purge_old_uploads()
    assert _stored_names() == []


def test_purge_survives_file_deleted_by_another_process(fake_datetime):
    kept = file_uploads.save(b"first")
    file_uploads.save(b"second")
    file_uploads.save(b"third")
    real_scan = files.scan

    def scan_then_lose_everything_but_one(path):
        entries = real_scan(path)
        for entry in entries:
            if entry.name != kept + ".dat":
                os.unlink(entry.path)
        return entries

    with fake_datetime(_later(file_uploads.MAX_MINUTES + 1)):
        with patch(
            "lithica.func.files.scan", side_effect=scan_then_lose_everything_but_one
        ):
            file_uploads.purge_old_uploads()
    assert _stored_names() == []


def test_purge_survives_file_deleted_between_check_and_delete(fake_datetime):
    file_uploads.save(b"content")
    real_unlink = os.unlink

    def unlink_twice(path, *args, **kwargs):
        real_unlink(path, *args, **kwargs)
        real_unlink(path, *args, **kwargs)

    with fake_datetime(_later(file_uploads.MAX_MINUTES + 1)):
        with patch("os.unlink", side_effect=unlink_twice):
            file_uploads.purge_old_uploads()
    assert _stored_names() == []


def test_delete_is_idempotent():
    files.save("some/file.dat", b"content")
    files.delete("some/file.dat")
    files.delete("some/file.dat")
    files.delete("never/existed.dat")
    assert not files.has("some/file.dat")


def test_concurrent_purges(fake_datetime):
    for number in range(200):
        file_uploads.save(b"content %d" % number)
    errors = []
    start = threading.Barrier(8)

    def purge():
        try:
            start.wait()
            file_uploads.purge_old_uploads()
        except Exception as ex:
            errors.append(ex)

    with fake_datetime(_later(file_uploads.MAX_MINUTES + 1)):
        threads = [threading.Thread(target=purge) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
    assert errors == []
    assert _stored_names() == []


def test_background_run_closes_its_session(fake_datetime):
    token = file_uploads.save(b"content")
    with fake_datetime(_later(file_uploads.MAX_MINUTES + 1)):
        with patch("lithica.func.file_uploads.db") as db:
            file_uploads.purge_old_uploads_once()
    db.session_scope.assert_called_once_with()
    db.session_scope.return_value.__exit__.assert_called_once()
    assert file_uploads.get(token) is None


def test_background_run_survives_errors():
    with patch("lithica.func.file_uploads.db") as db:
        with patch(
            "lithica.func.file_uploads.purge_old_uploads",
            side_effect=OSError("disk gone"),
        ):
            file_uploads.purge_old_uploads_once()
    db.session_scope.assert_called_once_with()
    db.session_scope.return_value.__exit__.assert_called_once()
