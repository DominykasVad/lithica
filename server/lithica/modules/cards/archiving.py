"""Fetch and relate the current card's external images in bounded batches."""

import logging
from collections import Counter
from contextlib import ExitStack
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import lazyload

from lithica import db, model, registry
from lithica.func import (
    documents,
    jobs,
    mime,
    net,
    post_metadata,
    posts,
    site_settings,
    util,
    visibility,
)
from lithica.func.content import Content
from lithica.modules.cards import archived_links, card, image_links, media
from lithica.modules.cards.model import ArchivedLink, ArchiveReason, Card

logger = logging.getLogger(__name__)

JOB = "cards-archive"
BATCH_SIZE = 10
MAX_SIZE = 32 * 1024 * 1024
LEASE_SECONDS = BATCH_SIZE * net.DOWNLOAD_TOTAL_TIMEOUT + 600
_MAX_LOG_REASONS: tuple[ArchiveReason, ...] = (
    "failed",
    "too-large",
    "not-media",
    "unavailable",
)


class ArchiveJobError(RuntimeError):
    """A sanitized failure for the engine's job log and admin job history."""


def _locked_card(post_id: int) -> Card | None:
    # Use the same post-then-projection lock order as the document write hook
    # and the file image worker. A card can disappear while a job is queued.
    locked = db.session.scalar(
        sa.select(model.Post.post_id)
        .where(model.Post.post_id == post_id)
        .with_for_update()
        .execution_options(**{visibility.ALL_POSTS: True})
    )
    if locked is None:
        return None
    return db.session.scalar(
        sa.select(Card)
        .where(Card.post_id == post_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def _active(post_id: int) -> bool:
    return (
        db.session.scalar(
            sa.select(model.Job.id)
            .where(
                model.Job.type == JOB,
                model.Job.status.in_(("queued", "running")),
                model.Job.payload["postId"].as_integer() == post_id,
            )
            .limit(1)
        )
        is not None
    )


def _enqueue(
    post: model.Post,
    row: Card,
    retry_failed: bool,
    actor: model.User | None = None,
) -> None:
    row.archive_queued = True
    jobs.enqueue(
        JOB,
        {
            "postId": post.post_id,
            "checksum": post.checksum,
            "retryBefore": util.utcnow().isoformat() if retry_failed else None,
        },
        actor,
    )


def queue(post: model.Post, retry_failed: bool, actor: model.User) -> bool:
    document = documents.get(post, lock=True)
    row = _locked_card(post.post_id)
    db.session.refresh(post, ["kind", "checksum"])
    if post.kind != "card" or document.kind != "card" or row is None:
        raise documents.DocumentNotFoundError("Card document not found.")
    # Recover from an exhausted engine job retry when the user asks again.
    if row.archive_queued and _active(post.post_id):
        return False
    _enqueue(post, row, retry_failed, actor)
    return True


def _matches(post: model.Post, data: registry.Payload) -> bool:
    creator = card.as_text(card.fields_of(data["spec"], data["card"]).get("creator"))
    names = site_settings.get("cards.archive_creators")
    tags = {name.strip().casefold() for name in site_settings.get("cards.archive_tags")}
    creators = {name.strip().casefold() for name in names if name.strip()}
    return creator.strip().casefold() in creators or any(
        name.name.casefold() in tags for tag in post.tags for name in tag.names
    )


def queue_automatic(post_id: int, data: registry.Payload) -> None:
    if site_settings.get("cards.archive_mode") != "automatic":
        return
    post = posts.try_get_post_by_id(post_id)
    if post is None or post.kind != "card" or not _matches(post, data):
        return
    row = _locked_card(post_id)
    if row is not None and not row.archive_queued:
        _enqueue(post, row, False)


def _existing(url: str) -> model.Post | None:
    return db.session.scalar(
        sa.select(model.Post)
        .join(ArchivedLink, ArchivedLink.post_id == model.Post.post_id)
        .where(
            ArchivedLink.url_hash == archived_links.url_hash(url),
            ArchivedLink.url == url,
            ArchivedLink.status == "archived",
            model.Post.kind == "media",
            model.Post.checksum.is_not(None),
        )
        .order_by(model.Post.post_id)
        .options(lazyload("*"))
        .limit(1)
    )


def _download(url: str, cleanup: ExitStack) -> Content | ArchiveReason:
    try:
        content = net.download(url, max_size=MAX_SIZE, log_failures=False)
    except net.DownloadTooLargeError:
        return "too-large"
    except (net.DownloadError, net.InvalidDownloadUrlError, ValueError):
        return "failed"
    cleanup.callback(content.delete)
    mime_type = mime.get_mime_type(content)
    return (
        content if mime.is_image(mime_type) or mime.is_video(mime_type) else "not-media"
    )


def _archive_one(
    post: model.Post, url: str, download: Content | ArchiveReason | None
) -> tuple[int | None, ArchiveReason | None, bool] | None:
    picture = _existing(url)
    if picture is not None:
        media.relate(picture, post, "archived-from", None, post.user)
        return picture.post_id, None, True

    if not isinstance(download, Content):
        # If the reusable post disappeared, leave the URL due for another batch.
        return (None, download, False) if download is not None else None
    picture, created = media.obtain(download, post, post.user, from_file=True)
    if picture is None:
        return None, "unavailable", False
    if created and not util.value_exceeds_column_size(url, model.Post.source):
        posts.update_post_source(picture, url)
    media.relate(picture, post, "archived-from", None, post.user, created=created)
    if created:
        media.release([picture])
        db.session.flush()
    return picture.post_id, None, not created


def _record(
    card_post_id: int,
    url: str,
    previous: ArchivedLink | None,
    post_id: int | None,
    reason: ArchiveReason | None,
) -> None:
    row = previous
    if row is None:
        row = ArchivedLink(
            card_post_id=card_post_id, url_hash=archived_links.url_hash(url), url=url
        )
        db.session.add(row)
    row.post_id = post_id
    row.status = "archived" if post_id is not None else "failed"
    row.reason = reason
    row.attempts = previous.attempts + 1 if previous is not None else 1
    row.last_attempt_time = util.utcnow()
    db.session.flush()


def _attempt(
    post: model.Post,
    url: str,
    download: Content | ArchiveReason | None,
    previous: ArchivedLink | None,
) -> tuple[ArchiveReason | None, bool] | None:
    try:
        with db.session.begin_nested():
            result = _archive_one(post, url, download)
            if result is None:
                return None
            post_id, reason, reused = result
            _record(post.post_id, url, previous, post_id, reason)
        return reason, reused
    except posts.InvalidPostContentError:
        failure: ArchiveReason = "not-media"
    except (
        posts.PostAlreadyUploadedError,
        posts.PostNotFoundError,
        post_metadata.InvalidTypedRelationError,
    ):
        failure = "unavailable"
    except IntegrityError:
        if previous is None and url in archived_links.current(post.post_id, [url]):
            return None  # Another writer already recorded the URL.
        failure = "unavailable"
    # The failed attempt's savepoint has rolled back any media or relation.
    with db.session.begin_nested():
        _record(post.post_id, url, previous, None, failure)
    return failure, False


def _due(
    urls: list[str], rows: dict[str, ArchivedLink], cutoff: datetime | None
) -> list[str]:
    return [
        url
        for url in urls
        if (existing := rows.get(url)) is None
        or (
            cutoff is not None
            and existing.status == "failed"
            and existing.last_attempt_time < cutoff
        )
    ]


def _finish_batch(
    payload: registry.Payload,
    post_id: int,
    cutoff: datetime | None,
    prepared: dict[str, Content | ArchiveReason | None],
) -> None:
    row = _locked_card(post_id)
    if row is None or not row.archive_queued:
        return
    # The unlocked read may have loaded any of these rows before an edit.
    db.session.expire_all()
    post = posts.try_get_post_by_id(post_id)
    document = db.session.get(model.PostDocument, post_id)
    if (
        post is None
        or post.kind != "card"
        or document is None
        or document.kind != "card"
    ):
        row.archive_queued = False
        return
    if post.checksum != payload.get("checksum"):
        row.archive_queued = False
        # Replacement could have occurred while the old job was queued.
        if site_settings.get("cards.archive_mode") == "automatic" and _matches(
            post, document.data
        ):
            _enqueue(post, row, False)
        return

    with visibility.as_viewer(post.user):
        if visibility.hides_nsfw():
            visibility.hiding_tag_ids(refresh=True)
        urls, _, extra = image_links.collect(document.data)
        rows = archived_links.current(post_id, urls)
        reused = 0
        archived = 0
        failures: Counter[ArchiveReason] = Counter()
        for url in _due(urls, rows, cutoff):
            if url not in prepared:
                continue
            result = _attempt(post, url, prepared[url], rows.get(url))
            if result is None:
                continue
            reason, used_existing = result
            if reason is None:
                archived += 1
                reused += int(used_existing)
            else:
                failures[reason] += 1
        if _due(urls, archived_links.current(post_id, urls), cutoff):
            jobs.enqueue(JOB, payload)
        else:
            row.archive_queued = False
        logger.info(
            "Card image archive: found=%d archived=%d reused=%d "
            "failed=%d too-large=%d not-media=%d unavailable=%d",
            len(urls) + extra,
            archived,
            reused,
            *(failures[reason] for reason in _MAX_LOG_REASONS),
        )


def _run(payload: registry.Payload) -> None:
    post_id = int(payload["postId"])
    row = db.session.get(Card, post_id)
    if row is None or not row.archive_queued:
        return
    post = posts.try_get_post_by_id(post_id)
    document = db.session.get(model.PostDocument, post_id)
    retry_before = payload.get("retryBefore")
    cutoff = datetime.fromisoformat(retry_before) if retry_before else None
    with ExitStack() as cleanup:
        prepared: dict[str, Content | ArchiveReason | None] = {}
        if (
            post is not None
            and post.kind == "card"
            and post.checksum == payload.get("checksum")
            and document is not None
            and document.kind == "card"
        ):
            urls, _, _ = image_links.collect(document.data)
            due = _due(urls, archived_links.current(post_id, urls), cutoff)
            with visibility.as_viewer(post.user):
                for url in due[:BATCH_SIZE]:
                    prepared[url] = None if _existing(url) else _download(url, cleanup)
        _finish_batch(payload, post_id, cutoff, prepared)


def run(payload: registry.Payload) -> None:
    try:
        _run(payload)
    except Exception:
        # The engine persists the job error message. SQL and HTTP exceptions
        # may contain URLs, so let the engine retry with a fixed message.
        raise ArchiveJobError("Card image archive could not complete.") from None
