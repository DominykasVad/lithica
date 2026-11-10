"""Durable jobs. Handlers run without a request and see all posts.

A handler uses this scope's session, never commits it, and must be idempotent:
leases allow another process to repeat work if the original worker dies or stalls.
"""

import json
import logging
import os
import socket
import threading
import time
from datetime import datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.orm import Query

from lithica import config, db, errors, model, registry
from lithica.func import users, util

logger = logging.getLogger(__name__)
CLAIM_BATCH_SIZE = 20
STATUSES = ("queued", "running", "done", "failed")


def types() -> dict[str, registry.JobType]:
    return {
        item.name: item
        for item in [
            *registry.ENGINE_JOB_TYPES,
            *(item for module in registry.modules() for item in module.job_types),
        ]
    }


def enqueue(
    type: str,
    payload: registry.Payload,
    user: model.User | None = None,
    run_after: datetime | None = None,
) -> model.Job:
    """Add to the caller's transaction; rollback also discards the job."""
    declaration = types().get(type)
    if declaration is None:
        raise errors.ValidationError("Unknown job type: %s" % type)
    try:
        encoded = json.dumps(payload, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as ex:
        raise errors.ValidationError("Job payload must be JSON.") from ex
    if len(encoded) > 64 * 1024:
        raise errors.ValidationError("Job payload exceeds 64 KiB.")
    now = util.utcnow()
    job = model.Job(
        type=type,
        payload=json.loads(encoded),
        status="queued",
        attempts=0,
        max_attempts=declaration.max_attempts,
        creation_time=now,
        run_after=run_after or now,
        user_id=user.user_id if user else None,
    )
    db.session.add(job)
    return job


def _eligible(now: datetime) -> sa.ColumnElement[bool]:
    return sa.or_(
        sa.and_(model.Job.status == "queued", model.Job.run_after <= now),
        sa.and_(model.Job.status == "running", model.Job.lease_until < now),
    )


def _claim() -> tuple[int, str, int, datetime] | None:
    known = types()
    if not known:
        return None
    with db.session_scope():
        now = util.utcnow()
        candidates = (
            db.session.query(model.Job.id, model.Job.type)
            .filter(_eligible(now), model.Job.type.in_(known))
            .order_by(model.Job.run_after, model.Job.id)
            .limit(CLAIM_BATCH_SIZE)
            .all()
        )
        for job_id, name in candidates:
            # Some databases store timestamps only to whole-second precision.
            lease_until = now.replace(microsecond=0) + timedelta(
                seconds=known[name].lease_seconds
            )
            # The predicate is repeated after any lock wait: only one worker wins.
            changed = (
                db.session.query(model.Job)
                .filter(model.Job.id == job_id, _eligible(now))
                .update(
                    {
                        "status": "running",
                        "claimed_by": f"{socket.gethostname()}:{os.getpid()}",
                        "lease_until": lease_until,
                        "attempts": model.Job.attempts + 1,
                        "start_time": now,
                    },
                    synchronize_session=False,
                )
            )
            if changed == 1:
                attempt = (
                    db.session.query(model.Job.attempts).filter_by(id=job_id).scalar()
                )
                db.session.commit()
                return (
                    job_id,
                    name,
                    attempt,
                    lease_until,
                )
            db.session.rollback()
    return None


class _LostLease(Exception):
    pass


def _owned(job_id: int, attempt: int, lease: datetime) -> Query[model.Job]:
    return db.session.query(model.Job).filter_by(
        id=job_id, status="running", attempts=attempt, lease_until=lease
    )


def work_once() -> bool:
    """Claim and handle one job using independent sessions; True if one was claimed."""
    claim = _claim()
    if claim is None:
        return False
    job_id, name, attempt, lease = claim
    try:
        with db.session_scope():
            job = db.session.get(model.Job, job_id)
            if attempt > job.max_attempts:
                logger.warning(
                    "Job %s (%s) attempt %s failed: lease expired",
                    job_id,
                    name,
                    job.max_attempts,
                )
                _owned(job_id, attempt, lease).update(
                    {
                        "status": "failed",
                        "last_error": "lease expired",
                        "attempts": attempt - 1,
                        "finish_time": util.utcnow(),
                        "lease_until": None,
                    }
                )
                db.session.commit()
                return True
            logger.info("Job %s (%s) started", job_id, name)
            types()[name].run(job.payload)
            db.session.flush()
            if (
                _owned(job_id, attempt, lease).update(
                    {
                        "status": "done",
                        "finish_time": util.utcnow(),
                        "lease_until": None,
                        "last_error": None,
                    }
                )
                != 1
            ):
                raise _LostLease()
            db.session.commit()
            logger.info("Job %s (%s) finished", job_id, name)
    except _LostLease:
        pass  # Closing the handler scope rolls its writes back.
    except Exception as ex:
        # Deliberately no exception text or traceback in logs: it may contain payload.
        logger.warning(
            "Job %s (%s) attempt %s failed: %s",
            job_id,
            name,
            attempt,
            type(ex).__name__,
        )
        with db.session_scope():
            job = _owned(job_id, attempt, lease).one_or_none()
            if job is not None:
                now = util.utcnow()
                failed = attempt >= job.max_attempts
                _owned(job_id, attempt, lease).update(
                    {
                        "last_error": (type(ex).__name__ + ": " + str(ex))[:2000],
                        "lease_until": None,
                        "status": "failed" if failed else "queued",
                        "finish_time": now if failed else None,
                        "run_after": job.run_after
                        if failed
                        else now
                        + timedelta(seconds=min(3600, 30 * 2 ** min(attempt - 1, 7))),
                    },
                    synchronize_session=False,
                )
                db.session.commit()
    return True


def retain(keep_days: int, batch_size: int = 500) -> None:
    """Delete old successes in bounded transactions; failures are kept."""
    cutoff = util.utcnow() - timedelta(days=keep_days)
    with db.session_scope():
        while True:
            ids = [
                row[0]
                for row in db.session.query(model.Job.id)
                .filter(model.Job.status == "done", model.Job.finish_time < cutoff)
                .order_by(model.Job.id)
                .limit(batch_size)
            ]
            if not ids:
                return
            db.session.query(model.Job).filter(model.Job.id.in_(ids)).delete(
                synchronize_session=False
            )
            db.session.commit()


def get(job_id: int) -> model.Job:
    job = db.session.get(model.Job, job_id)
    if job is None:
        raise errors.NotFoundError("Job %s not found." % job_id)
    return job


def listing(status: str | None = None, type: str | None = None) -> Query[model.Job]:
    query = db.session.query(model.Job)
    if status is not None:
        if status not in STATUSES:
            raise errors.ValidationError("Invalid job status: %s" % status)
        query = query.filter_by(status=status)
    if type is not None:
        query = query.filter_by(type=type)
    return query.order_by(model.Job.id.desc())


def retry(ids: list[int] | None = None) -> None:
    """Retry failures atomically, retaining their errors until success."""
    rows = [get(id) for id in ids] if ids else listing(status="failed").all()
    for job in rows:
        if job.status != "failed":
            raise errors.ValidationError("Job %s is not failed." % job.id)
    for job in rows:
        changed = (
            db.session.query(model.Job)
            .filter_by(id=job.id, status="failed")
            .update(
                {
                    "status": "queued",
                    "attempts": 0,
                    "run_after": util.utcnow(),
                    "lease_until": None,
                    "claimed_by": None,
                    "start_time": None,
                    "finish_time": None,
                }
            )
        )
        if changed != 1:
            raise errors.ValidationError("Job %s is not failed." % job.id)


def worker_loop(stop: threading.Event) -> None:
    """One loop per process; stop claiming on shutdown, let current work finish."""
    next_retention = 0.0
    while not stop.is_set():
        try:
            if time.monotonic() >= next_retention:
                retain(config.config["jobs"]["keep_done_days"])
                next_retention = time.monotonic() + 3600
            if stop.is_set():
                return
            if work_once():
                continue
        except Exception as ex:
            # Database outages must not permanently stop the worker.
            logger.warning("Job worker error: %s", type(ex).__name__)
        stop.wait(config.config["jobs"]["poll_interval"])


def serialize(
    job: model.Job, viewer: model.User, *, payload: bool = False
) -> dict[str, object]:
    result: dict[str, object] = {
        "id": job.id,
        "type": job.type,
        "status": job.status,
        "attempts": job.attempts,
        "maxAttempts": job.max_attempts,
        "runAfter": job.run_after,
        "claimedBy": job.claimed_by,
        "leaseUntil": job.lease_until,
        "creationTime": job.creation_time,
        "startTime": job.start_time,
        "finishTime": job.finish_time,
        "lastError": job.last_error,
        "user": users.serialize_micro_user(job.user, auth_user=viewer),
    }
    if payload:
        result["payload"] = job.payload
    return result
