"""Bounded, repeat-safe conversion of cards predating documents."""

import argparse
import logging
import sys

import sqlalchemy as sa
from sqlalchemy.orm import Query

from lithica import db, model, registry
from lithica.func import jobs, posts, visibility
from lithica.modules.cards import file_images
from lithica.modules.cards.model import Card
from lithica.modules.cards.uploads import convert

logger = logging.getLogger(__name__)


def pending(after: int = 0) -> Query[model.Post]:
    return db.session.query(model.Post).filter(
        model.Post.kind == "card",
        model.Post.post_id > after,
        sa.or_(
            ~sa.exists().where(model.PostDocument.post_id == model.Post.post_id),
            sa.exists().where(
                Card.post_id == model.Post.post_id, Card.data_hash.is_(None)
            ),
            sa.and_(
                model.Post.mime_type.is_not(None),
                sa.exists().where(
                    Card.post_id == model.Post.post_id, Card.images_read.is_(False)
                ),
            ),
        ),
    )


def run(payload: registry.Payload) -> None:
    batch = pending(int(payload["after"])).order_by(model.Post.post_id).limit(100).all()
    for post in batch:
        post_id = post.post_id
        db.session.flush()
        try:
            with db.session.begin_nested():
                # Resolve the uploader under the card lock: account deletion
                # must not leave a stale authenticated viewer from the batch.
                db.session.execute(
                    sa.select(model.Post.post_id)
                    .where(model.Post.post_id == post_id)
                    .with_for_update()
                    .execution_options(**{visibility.ALL_POSTS: True})
                )
                db.session.refresh(post, ["user_id", "user"])
                with visibility.as_viewer(post.user):
                    convert(post, post.user)
                db.session.flush()
        except Exception as error:
            logger.warning(
                "Card %d conversion failed: %s", post_id, type(error).__name__
            )
    if len(batch) == 100:
        jobs.enqueue("cards-convert", {"after": batch[-1].post_id})
    # The queue worker commits this batch, its successor and job completion
    # atomically; a successor cannot be claimed until this transaction commits.


def configure(parser: argparse.ArgumentParser) -> None:
    commands = parser.add_subparsers(dest="cards_command", required=True)
    convert_parser = commands.add_parser(
        "convert", help="convert existing cards to documents"
    )
    convert_parser.add_argument(
        "--count",
        action="store_true",
        help="only count cards needing conversion, a data hash or file images",
    )


def _active() -> bool:
    return (
        db.session.query(model.Job.id)
        .filter(
            model.Job.type == "cards-convert",
            model.Job.status.in_(["queued", "running"]),
        )
        .first()
        is not None
    )


def _busy() -> int:
    print("A cards-convert job is queued or running.", file=sys.stderr)  # noqa: T201
    return 1


def command(arguments: argparse.Namespace) -> int:
    if not arguments.count:
        if _active():
            return _busy()
        # Serialize concurrent starts on the first pending card. With no
        # pending cards there is no job to enqueue. Select only the ID so
        # eager relationships do not join nullable sides into the row lock.
        pending().with_entities(model.Post.post_id).order_by(
            model.Post.post_id
        ).with_for_update().first()
        if _active():
            return _busy()
    count = pending().count()
    if not arguments.count and count:
        jobs.enqueue("cards-convert", {"after": 0})
        db.session.commit()
    print(  # noqa: T201
        f"cards convert: {count} cards needing conversion or a data hash "
        "(including file images)"
    )
    return 0


def run_images(payload: registry.Payload) -> None:
    post_id = int(payload["postId"])
    # Use the same post-then-projection lock order as conversion/replacement.
    locked_id = db.session.scalar(
        sa.select(model.Post.post_id)
        .where(model.Post.post_id == post_id)
        .with_for_update()
        .execution_options(**{visibility.ALL_POSTS: True})
    )
    if locked_id is None:
        return
    post = posts.try_get_post_by_id(post_id)
    if post is None:
        return
    db.session.refresh(post)
    if (
        post.kind != "card"
        or post.checksum != payload.get("checksum")
        or not post.mime_type
    ):
        return
    db.session.execute(
        sa.select(Card.post_id).where(Card.post_id == post_id).with_for_update()
    )
    row = db.session.get(Card, post_id)
    if row is None:
        return
    db.session.refresh(row)
    document = db.session.get(model.PostDocument, post_id)
    if row.images_read or document is None or document.kind != "card":
        return
    with visibility.as_viewer(post.user):
        file_images.backfill(post, None)
