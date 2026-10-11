import logging
from datetime import UTC, datetime, timedelta

from lithica import db
from lithica.func import files, util
from lithica.func.content import Content, ContentLike

logger = logging.getLogger(__name__)

MAX_MINUTES = 60


def _get_path(checksum: str) -> str:
    return "temporary-uploads/%s.dat" % checksum


def purge_old_uploads() -> None:
    """
    Delete temporary uploads older than MAX_MINUTES. Several server processes
    run this at the same time on the same directory, so a file that vanishes
    half-way is somebody else's finished work, not an error.
    """
    now = util.utcnow()
    for file in files.scan("temporary-uploads"):
        try:
            changed_at = file.stat().st_ctime
        except FileNotFoundError:
            continue
        file_time = datetime.fromtimestamp(changed_at, UTC).replace(tzinfo=None)
        if now - file_time > timedelta(minutes=MAX_MINUTES):
            files.delete("temporary-uploads/%s" % file.name)


def purge_old_uploads_once() -> None:
    """
    One purge run for the background thread: never raises, and runs in a
    session scope of its own, so any database session the run opens is
    closed before returning and nothing is shared with the requests.
    """
    with db.session_scope():
        try:
            purge_old_uploads()
        except Exception as ex:
            logger.exception(ex)


def get(checksum: str) -> Content | None:
    return files.get("temporary-uploads/%s.dat" % checksum)


def save(content: ContentLike) -> str:
    checksum = util.get_sha1(content)
    path = _get_path(checksum)
    if not files.has(path):
        files.save(path, content)
    return checksum
