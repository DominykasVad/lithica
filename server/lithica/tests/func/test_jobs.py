from datetime import timedelta

import pytest

from lithica import db, errors, model, registry
from lithica.func import jobs, util


@pytest.fixture
def queue(committing_session):
    registry.use(
        [
            registry.Module(
                "worker",
                job_types=[registry.JobType("record", lambda p: None, max_attempts=3)],
            )
        ]
    )


def add(payload=None):
    with db.session_scope():
        job = jobs.enqueue("record", payload or {})
        db.session.commit()
        return job.id


def row(id):
    with db.session_scope():
        job = jobs.get(id)
        db.session.expunge(job)
        return job


def test_enqueue_transaction_and_limits(queue):
    with db.session_scope():
        jobs.enqueue("record", {})
        db.session.rollback()
        assert jobs.listing().count() == 0
        with pytest.raises(errors.ValidationError):
            jobs.enqueue("missing", {})
        with pytest.raises(errors.ValidationError):
            jobs.enqueue("record", {"text": "x" * 65536})
    assert not jobs.work_once()
    id = add()
    assert jobs.work_once()
    assert row(id).status == "done"
    assert row(id).attempts == 1


def test_retries_and_atomic_writes(queue):
    calls = []

    def run(payload):
        calls.append(1)
        db.session.add(
            model.SiteSetting(
                name="job-write", value=True, last_edit_time=util.utcnow()
            )
        )
        if len(calls) < 3:
            raise ValueError("try again")

    registry.use(
        [
            registry.Module(
                "worker", job_types=[registry.JobType("record", run, max_attempts=3)]
            )
        ]
    )
    id = add()
    for attempt in (1, 2):
        assert jobs.work_once()
        job = row(id)
        assert job.status == "queued"
        assert job.attempts == attempt
        assert job.run_after > util.utcnow()
        with db.session_scope():
            assert db.session.get(model.SiteSetting, "job-write") is None
        assert not jobs.work_once()
        with db.session_scope():
            jobs.get(id).run_after = util.utcnow() - timedelta(seconds=1)
            db.session.commit()
    assert jobs.work_once()
    assert row(id).status == "done"
    with db.session_scope():
        assert db.session.get(model.SiteSetting, "job-write") is not None


def test_expired_leases_failures_retry_and_retention(queue):
    id = add()
    with db.session_scope():
        job = jobs.get(id)
        job.status = "running"
        job.attempts = 1
        job.lease_until = util.utcnow() - timedelta(seconds=1)
        db.session.commit()
    assert jobs.work_once()
    assert row(id).attempts == 2
    with db.session_scope():
        job = jobs.get(id)
        job.status = "running"
        job.attempts = 3
        job.lease_until = util.utcnow() - timedelta(seconds=1)
        db.session.commit()
    assert jobs.work_once()
    assert row(id).status == "failed"
    assert row(id).last_error == "lease expired"
    with db.session_scope():
        jobs.retry([id])
        db.session.commit()
    assert row(id).attempts == 0
    assert jobs.work_once()
    with db.session_scope():
        jobs.get(id).finish_time = util.utcnow() - timedelta(days=8)
        db.session.commit()
    jobs.retain(7, batch_size=1)
    with db.session_scope():
        assert jobs.listing().count() == 0


def test_disabled_type_waits(queue):
    id = add()
    registry.use([])
    assert not jobs.work_once()
    assert row(id).status == "queued"


def test_registry_job_types():
    for items in (
        [registry.JobType("bad_name", lambda p: None)],
        [registry.JobType("same", lambda p: None)] * 2,
        [registry.JobType("invalid", lambda p: None, lease_seconds=0)],
    ):
        with pytest.raises(errors.ConfigError):
            registry.use([registry.Module("test", job_types=items)])


@pytest.fixture
def dummy_queue(committing_session, monkeypatch, tmp_path):
    from lithica import config
    from lithica.tests.fixtures.modules.dummy import module

    monkeypatch.setitem(config.config, "data_dir", str(tmp_path))
    registry.use([module])
    return tmp_path


def enqueue_dummy(count):
    with db.session_scope():
        for i in range(count):
            jobs.enqueue("dummy-record", {"record": str(i)})
        db.session.commit()


def assert_records(directory, count):
    assert len(list((directory / "dummy-jobs").iterdir())) == count
    for i in range(count):
        assert (directory / "dummy-jobs" / str(i)).read_text() == "run\n"
    with db.session_scope():
        assert jobs.listing(status="done").count() == count
        assert all(job.attempts == 1 for job in jobs.listing())


def test_several_threads_run_each_job_once(dummy_queue):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    barrier = Barrier(4)
    enqueue_dummy(30)

    def worker(_):
        barrier.wait(timeout=10)
        while jobs.work_once():
            pass

    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(worker, range(4)))
    assert_records(dummy_queue, 30)


def test_two_process_worker_loops_before_enqueue(dummy_queue, _pg_database_url):
    import selectors
    import subprocess
    import sys
    import time

    processes = []
    try:
        for _ in range(2):
            processes.append(
                subprocess.Popen(
                    [
                        sys.executable,
                        "-m",
                        "lithica.tests.fixtures.job_worker",
                        _pg_database_url.render_as_string(hide_password=False),
                        str(dummy_queue),
                    ],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
            )
        for process in processes:
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                assert selector.select(timeout=20), "Worker failed to become ready"
                assert process.stdout.readline().strip() == "ready"
        enqueue_dummy(20)
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            with db.session_scope():
                if jobs.listing(status="done").count() == 20:
                    break
            time.sleep(0.05)
        assert_records(dummy_queue, 20)
    finally:
        for process in processes:
            try:
                _, stderr = process.communicate("stop\n", timeout=10)
                assert process.returncode == 0, stderr
            finally:
                if process.poll() is None:
                    process.kill()
                    process.communicate()


def test_dummy_failure_exhaustion_and_restart(dummy_queue):
    from lithica.tests.fixtures.modules.dummy import module

    with db.session_scope():
        job = jobs.enqueue("dummy-record", {"record": "retry", "failures": 5})
        db.session.commit()
        id = job.id
    for attempt in range(1, 6):
        # New registrations and sessions model a fresh worker after a restart.
        registry.use([])
        registry.use([module])
        assert jobs.work_once()
        job = row(id)
        assert job.attempts == attempt
        assert job.last_error == "ValueError: Dummy job failure"
        assert job.status == ("failed" if attempt == 5 else "queued")
        with db.session_scope():
            jobs.get(id).run_after = util.utcnow() - timedelta(seconds=1)
            db.session.commit()
    with db.session_scope():
        jobs.retry([id])
        db.session.commit()
    assert jobs.work_once()
    assert row(id).status == "done"
    assert row(id).last_error is None
    assert (dummy_queue / "dummy-jobs" / "retry").read_text().splitlines() == [
        "run"
    ] * 6


def test_retention_keeps_recent_and_failed(queue):
    ids = [add() for _ in range(3)]
    with db.session_scope():
        for id, status, days in zip(
            ids, ["done", "done", "failed"], [8, 1, 8], strict=True
        ):
            job = jobs.get(id)
            job.status = status
            job.finish_time = util.utcnow() - timedelta(days=days)
        db.session.commit()
    jobs.retain(7, batch_size=1)
    with db.session_scope():
        assert {j.id for j in jobs.listing()} == set(ids[1:])


def test_claim_order_and_scheduled_jobs(queue):
    seen = []
    registry.use(
        [
            registry.Module(
                "worker",
                job_types=[registry.JobType("record", lambda p: seen.append(p["n"]))],
            )
        ]
    )
    with db.session_scope():
        now = util.utcnow()
        jobs.enqueue("record", {"n": 0}, run_after=now + timedelta(days=1))
        jobs.enqueue("record", {"n": 1}, run_after=now - timedelta(seconds=1))
        jobs.enqueue("record", {"n": 2}, run_after=now - timedelta(seconds=2))
        jobs.enqueue("record", {"n": 3}, run_after=now - timedelta(seconds=1))
        db.session.commit()
    while jobs.work_once():
        pass
    assert seen == [2, 1, 3]


def test_error_limit_and_backoff_cap(queue):
    def fail(payload):
        raise ValueError("x" * 3000)

    registry.use(
        [
            registry.Module(
                "worker", job_types=[registry.JobType("record", fail, max_attempts=20)]
            )
        ]
    )
    id = add()
    with db.session_scope():
        jobs.get(id).attempts = 10
        db.session.commit()
    assert jobs.work_once()
    job = row(id)
    error = job.last_error
    assert error is not None
    assert len(error) == 2000
    assert error.startswith("ValueError: ")
    assert 3595 < (job.run_after - util.utcnow()).total_seconds() <= 3600


def test_new_process_works_queued_and_reclaims_dead_worker(
    dummy_queue, _pg_database_url
):
    import selectors
    import subprocess
    import sys
    import time

    enqueue_dummy(2)
    with db.session_scope():
        job = jobs.listing().first()
        assert job is not None
        job.status = "running"
        job.attempts = 1
        job.claimed_by = "dead-host:123"
        job.lease_until = util.utcnow() - timedelta(seconds=1)
        db.session.commit()
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "lithica.tests.fixtures.job_worker",
            _pg_database_url.render_as_string(hide_password=False),
            str(dummy_queue),
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert process.stdout is not None
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            assert selector.select(timeout=20)
            assert process.stdout.readline().strip() == "ready"
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            with db.session_scope():
                if jobs.listing(status="done").count() == 2:
                    break
            time.sleep(0.05)
        with db.session_scope():
            assert jobs.listing(status="done").count() == 2
            assert sorted(j.attempts for j in jobs.listing()) == [1, 2]
        for i in range(2):
            assert (dummy_queue / "dummy-jobs" / str(i)).read_text() == "run\n"
    finally:
        try:
            _, stderr = process.communicate("stop\n", timeout=10)
            assert process.returncode == 0, stderr
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()


@pytest.mark.parametrize("fail", [False, True])
def test_stale_handler_cannot_finish_or_fail_new_claim(queue, fail):
    def handler(payload):
        # Another worker reclaims while this handler is still executing.
        with db.session_scope():
            job = jobs.get(payload["id"])
            job.lease_until = util.utcnow() - timedelta(seconds=1)
            db.session.commit()
        assert jobs._claim() is not None
        db.session.add(
            model.SiteSetting(
                name="stale-write", value=True, last_edit_time=util.utcnow()
            )
        )
        if fail:
            raise ValueError("old worker")

    registry.use(
        [registry.Module("worker", job_types=[registry.JobType("record", handler)])]
    )
    id = add()
    with db.session_scope():
        jobs.get(id).payload = {"id": id}
        db.session.commit()
    assert jobs.work_once()
    assert row(id).status == "running"
    assert row(id).attempts == 2
    assert row(id).last_error is None
    with db.session_scope():
        assert db.session.get(model.SiteSetting, "stale-write") is None
