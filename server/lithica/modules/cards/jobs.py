"""Bounded, repeat-safe conversion of cards predating documents."""

import argparse
import logging
import sys

import sqlalchemy as sa
from sqlalchemy.orm import Query

from lithica import db, model, registry
from lithica.func import jobs
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
        ),
    )


def run(payload: registry.Payload) -> None:
    batch = pending(int(payload["after"])).order_by(model.Post.post_id).limit(100).all()
    for post in batch:
        post_id = post.post_id
        db.session.flush()
        try:
            with db.session.begin_nested():
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
        help="only count cards needing conversion or a data hash",
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
    print(f"cards convert: {count} cards needing conversion or a data hash")  # noqa: T201
    return 0
