import threading

import pytest

from lithica import db, model
from lithica.api import dependencies, info_api
from lithica.func import mime
from lithica.tests.api.http import assert_fits, ok


class _ImmediateThread:
    "Runs the target inline instead of on a real thread"

    def __init__(self, target=None, args=(), kwargs=None, **_ignored):
        self._target = target
        self._args = args
        self._kwargs = kwargs or {}

    def start(self):
        assert self._target is not None
        self._target(*self._args, **self._kwargs)


def test_info_api(
    tmpdir,
    config_injector,
    client,
    post_factory,
    user_factory,
    fake_datetime,
    monkeypatch,
):
    # measure inline instead of on a thread, so the result is there at once
    monkeypatch.setattr(
        info_api._DiskUsage, "_start_measuring", lambda self: self._measure()
    )
    monkeypatch.setattr(info_api, "_disk_usage", info_api._DiskUsage())
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

    # without modules: the engine's types; the limit unset, so the default
    accepted = [
        {"mime": [mime_type], "extensions": list(extensions)}
        for mime_type, extensions in mime.ACCEPTED_TYPES
    ]
    limit = dependencies.DEFAULT_MAX_UPLOAD_SIZE

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
        assert ok(client.get("/info", user=auth_user)) == {
            "postCount": 2,
            "diskUsage": 3,
            "featuredPost": None,
            "featuringTime": None,
            "featuringUser": None,
            "serverTime": "2016-01-01T13:00:00Z",
            "modules": [],
            "maxUploadSize": limit,
            "acceptedTypes": accepted,
            "config": expected_config_key,
        }
    directory.join("test2.txt").write("abc")
    with fake_datetime("2016-01-03 13:01"):
        assert ok(client.get("/info", user=auth_user)) == {
            "postCount": 2,
            "diskUsage": 6,  # cache expired
            "featuredPost": None,
            "featuringTime": None,
            "featuringUser": None,
            "serverTime": "2016-01-03T13:01:00Z",
            "modules": [],
            "maxUploadSize": limit,
            "acceptedTypes": accepted,
            "config": expected_config_key,
        }
    with fake_datetime("2016-01-03 13:01"):
        assert ok(client.get("/info", user=anon_user)) == {
            "postCount": 2,
            "diskUsage": 6,  # cache expired
            "serverTime": "2016-01-03T13:01:00Z",
            "modules": [],
            "maxUploadSize": limit,
            "acceptedTypes": accepted,
            "config": expected_config_key,
        }


@pytest.fixture
def data_dir(tmpdir, config_injector):
    directory = tmpdir.mkdir("data")
    directory.join("test.txt").write("abc")
    config_injector({"data_dir": str(directory)})
    return directory


def test_disk_usage_is_measured_in_the_background(data_dir):
    disk_usage = info_api._DiskUsage()
    # the request that starts the first measurement does not wait for it
    first = disk_usage.get()
    assert first in (None, 3)
    for thread in threading.enumerate():
        if thread is not threading.current_thread() and thread.daemon:
            thread.join(timeout=5)
    assert disk_usage.get() == 3


def test_disk_usage_is_kept_for_the_ttl(data_dir, fake_datetime, monkeypatch):
    monkeypatch.setattr(info_api.threading, "Thread", _ImmediateThread)
    disk_usage = info_api._DiskUsage()
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
    disk_usage = info_api._DiskUsage()
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

    monkeypatch.setattr(info_api.threading, "Thread", _FailingOnceThread)
    disk_usage = info_api._DiskUsage()
    with monkeypatch.context() as patched:
        patched.setattr(
            info_api.os, "walk", lambda _path: (_ for _ in ()).throw(OSError())
        )
        assert disk_usage.get() is None
    # the failure did not leave the "measuring" flag set
    assert disk_usage.get() == 3


def test_info_fits_its_response_model(
    client,
    config_injector,
    tmpdir,
    post_factory,
    user_factory,
    tag_category_factory,
    monkeypatch,
):
    from lithica.api import resources
    from lithica.func import posts

    monkeypatch.setattr(
        info_api._DiskUsage, "_start_measuring", lambda self: self._measure()
    )
    monkeypatch.setattr(info_api, "_disk_usage", info_api._DiskUsage())
    config_injector(
        {
            "name": "test installation",
            "contact_email": None,
            "enable_safety": True,
            "data_dir": str(tmpdir),
            "data_url": "http://example.com/data/",
            "secret": "test",
            "user_name_regex": "1",
            "password_regex": "2",
            "tag_name_regex": "3",
            "tag_category_name_regex": "4",
            "default_rank": "regular",
            "thumbnails": {"post_width": 300, "post_height": 300, "avatar_width": 30},
            "privileges": {
                "posts:view:featured": "regular",
                "users:edit:any:email": "moderator",
            },
            "smtp": {"host": None},
        }
    )
    user = user_factory(rank=model.User.RANK_REGULAR)
    post = post_factory()
    db.session.add_all([user, post, tag_category_factory(default=True)])
    db.session.flush()

    anonymous = ok(client.get("/info"))
    assert "featuredPost" not in anonymous
    assert_fits(resources.Info, anonymous, complete=False)

    nothing_featured = ok(client.get("/info", user=user))
    assert nothing_featured["featuredPost"] is None
    assert_fits(resources.Info, nothing_featured)

    posts.feature_post(post, user)
    db.session.flush()
    featured = ok(client.get("/info", user=user))
    assert featured["featuredPost"]["id"] == post.post_id
    assert featured["featuringUser"]["name"] == user.name
    assert_fits(resources.Info, featured)


def test_info_with_a_trailing_slash(client, config_injector, tmpdir, monkeypatch):
    monkeypatch.setattr(info_api, "_disk_usage", info_api._DiskUsage())
    config_injector(
        {
            "name": "n",
            "contact_email": None,
            "enable_safety": True,
            "data_dir": str(tmpdir),
            "user_name_regex": "1",
            "password_regex": "2",
            "tag_name_regex": "3",
            "tag_category_name_regex": "4",
            "default_rank": "regular",
            "privileges": {"posts:view:featured": "regular"},
            "smtp": {"host": None},
        }
    )
    assert ok(client.get("/info/"))["postCount"] == 0


def test_info_says_the_upload_limit_the_server_checks(
    client, config_injector, user_factory, monkeypatch
):
    monkeypatch.setattr(info_api, "_disk_usage", info_api._DiskUsage())
    monkeypatch.setattr(info_api._DiskUsage, "_start_measuring", lambda self: None)
    config_injector(
        {
            "name": "x",
            "contact_email": None,
            "enable_safety": True,
            "user_name_regex": "1",
            "password_regex": "2",
            "tag_name_regex": "3",
            "tag_category_name_regex": "4",
            "default_rank": "regular",
            "privileges": {
                "posts:view:featured": "regular",
                "uploads:create": "regular",
            },
            "smtp": {"host": None},
            "max_upload_size": 2048,
        }
    )
    user = user_factory(rank=model.User.RANK_REGULAR)
    reported = ok(client.get("/info", user=user))["maxUploadSize"]
    assert reported == 2048 == dependencies.max_upload_size()
    # what is said is what is checked: one byte more is refused
    response = client.post(
        "/uploads", user=user, files={"content": b"x" * (reported + 1)}
    )
    assert response.status_code == 413
    assert response.json()["name"] == "RequestTooLargeError"
