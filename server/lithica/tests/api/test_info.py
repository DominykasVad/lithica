import threading
from datetime import datetime

import pytest

from lithica import api, db, model


class _ImmediateThread:
    "Runs the target inline instead of on a real thread"

    def __init__(self, target=None, args=(), kwargs=None, **_ignored):
        self._target = target
        self._args = args
        self._kwargs = kwargs or {}

    def start(self):
        self._target(*self._args, **self._kwargs)


def test_info_api(
    tmpdir,
    config_injector,
    context_factory,
    post_factory,
    user_factory,
    fake_datetime,
    monkeypatch,
):
    monkeypatch.setattr(api.info_api.threading, "Thread", _ImmediateThread)
    monkeypatch.setattr(api.info_api, "_disk_usage", api.info_api._DiskUsage())
    directory = tmpdir.mkdir("data")
    directory.join("test.txt").write("abc")
    auth_user = user_factory(rank=model.User.RANK_REGULAR)
    anon_user = user_factory(rank=model.User.RANK_ANONYMOUS)
    config_injector(
        {
            "name": "test installation",
            "contact_email": "test@example.com",
            "enable_safety": True,
            "data_dir": str(directory),
            "user_name_regex": "1",
            "password_regex": "2",
            "tag_name_regex": "3",
            "tag_category_name_regex": "4",
            "default_rank": "5",
            "privileges": {
                "test_key1": "test_value1",
                "test_key2": "test_value2",
                "posts:view:featured": "regular",
            },
            "smtp": {
                "host": "example.com",
            },
        }
    )
    db.session.add_all([post_factory(), post_factory()])
    db.session.flush()

    expected_config_key = {
        "name": "test installation",
        "contactEmail": "test@example.com",
        "enableSafety": True,
        "userNameRegex": "1",
        "passwordRegex": "2",
        "tagNameRegex": "3",
        "tagCategoryNameRegex": "4",
        "defaultUserRank": "5",
        "privileges": {
            "testKey1": "test_value1",
            "testKey2": "test_value2",
            "posts:view:featured": "regular",
        },
        "canSendMails": True,
    }

    with fake_datetime("2016-01-01 13:00"):
        assert api.info_api.get_info(context_factory(user=auth_user)) == {
            "postCount": 2,
            "diskUsage": 3,
            "featuredPost": None,
            "featuringTime": None,
            "featuringUser": None,
            "serverTime": datetime(2016, 1, 1, 13, 0),
            "config": expected_config_key,
        }
    directory.join("test2.txt").write("abc")
    with fake_datetime("2016-01-03 13:01"):
        assert api.info_api.get_info(context_factory(user=auth_user)) == {
            "postCount": 2,
            "diskUsage": 6,  # cache expired
            "featuredPost": None,
            "featuringTime": None,
            "featuringUser": None,
            "serverTime": datetime(2016, 1, 3, 13, 1),
            "config": expected_config_key,
        }
    with fake_datetime("2016-01-03 13:01"):
        assert api.info_api.get_info(context_factory(user=anon_user)) == {
            "postCount": 2,
            "diskUsage": 6,  # cache expired
            "serverTime": datetime(2016, 1, 3, 13, 1),
            "config": expected_config_key,
        }


@pytest.fixture
def data_dir(tmpdir, config_injector):
    directory = tmpdir.mkdir("data")
    directory.join("test.txt").write("abc")
    config_injector({"data_dir": str(directory)})
    return directory


def test_disk_usage_is_measured_in_the_background(data_dir):
    disk_usage = api.info_api._DiskUsage()
    # the request that starts the first measurement does not wait for it
    first = disk_usage.get()
    assert first in (None, 3)
    for thread in threading.enumerate():
        if thread is not threading.current_thread() and thread.daemon:
            thread.join(timeout=5)
    assert disk_usage.get() == 3


def test_disk_usage_is_kept_for_the_ttl(data_dir, fake_datetime, monkeypatch):
    monkeypatch.setattr(api.info_api.threading, "Thread", _ImmediateThread)
    disk_usage = api.info_api._DiskUsage()
    with fake_datetime("2016-01-01 13:00:00"):
        assert disk_usage.get() == 3
    data_dir.join("test2.txt").write("abc")
    with fake_datetime("2016-01-01 14:00:00"):
        assert disk_usage.get() == 3
    with fake_datetime("2016-01-01 14:00:01"):
        assert disk_usage.get() == 6


def test_disk_usage_starts_one_measurement_at_a_time(data_dir, monkeypatch):
    started = []
    release = threading.Event()
    disk_usage = api.info_api._DiskUsage()
    real_measure = disk_usage._measure

    def slow_measure():
        started.append(1)
        release.wait(timeout=5)
        real_measure()

    monkeypatch.setattr(disk_usage, "_measure", slow_measure)
    callers = [threading.Thread(target=disk_usage.get) for _ in range(16)]
    for caller in callers:
        caller.start()
    for caller in callers:
        caller.join()
    assert disk_usage.get() is None
    assert len(started) == 1
    release.set()
    for thread in threading.enumerate():
        if thread is not threading.current_thread() and thread.daemon:
            thread.join(timeout=5)
    assert disk_usage.get() == 3
    assert len(started) == 1


def test_disk_usage_recovers_from_a_failed_measurement(
    data_dir, fake_datetime, monkeypatch
):
    class _FailingOnceThread(_ImmediateThread):
        def start(self):
            try:
                super().start()
            except OSError:
                pass

    monkeypatch.setattr(api.info_api.threading, "Thread", _FailingOnceThread)
    disk_usage = api.info_api._DiskUsage()
    with monkeypatch.context() as patched:
        patched.setattr(
            api.info_api.os, "walk", lambda _path: (_ for _ in ()).throw(OSError())
        )
        assert disk_usage.get() is None
    # the failure did not leave the "measuring" flag set
    assert disk_usage.get() == 3
