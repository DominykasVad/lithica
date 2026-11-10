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
