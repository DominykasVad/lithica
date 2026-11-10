import threading
from unittest.mock import patch

import pytest

from lithica import config, errors
from lithica.func import jobs


def test_worker_drains_and_stops(monkeypatch):
    monkeypatch.setitem(
        config.config, "jobs", {"poll_interval": 1, "keep_done_days": 7}
    )
    stop = threading.Event()
    calls = []

    def work():
        calls.append(1)
        if len(calls) == 3:
            stop.set()
        return True

    with patch.object(jobs, "work_once", work), patch.object(jobs, "retain") as retain:
        jobs.worker_loop(stop)
    assert len(calls) == 3
    retain.assert_called_once_with(7)


@pytest.mark.parametrize(
    "values",
    [
        None,
        {},
        {"worker": 1, "poll_interval": 5, "keep_done_days": 7},
        {"worker": True, "poll_interval": 0, "keep_done_days": 7},
        {"worker": True, "poll_interval": 5, "keep_done_days": -1},
    ],
)
def test_invalid_job_config(monkeypatch, values):
    monkeypatch.setitem(config.config, "secret", "test-secret")
    monkeypatch.setitem(config.config, "data_dir", "/tmp")
    monkeypatch.setitem(config.config, "data_url", "data/")
    monkeypatch.setitem(config.config, "jobs", values)
    with pytest.raises(errors.ConfigError, match="jobs requires"):
        config.validate()
