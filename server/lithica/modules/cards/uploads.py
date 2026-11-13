"""Convert extracted card content once, preserving the uploaded bytes."""

import hashlib

import sqlalchemy as sa
from sqlalchemy.orm import undefer

from lithica import db, errors, model, registry
from lithica.func import documents, posts, visibility
from lithica.modules.cards import card as card_format
from lithica.modules.cards.documents import after_card, split_card, validate_lorebook
from lithica.modules.cards.model import Card


def convert(post: model.Post, user: model.User | None) -> None:
    if post.kind != "card":
        return
    db.session.execute(
        sa.select(model.Post.post_id)
        .where(model.Post.post_id == post.post_id)
        .with_for_update()
        .execution_options(**{visibility.ALL_POSTS: True})
    )
    # The batch may have loaded this post before a concurrent edit committed.
    # Read metadata under the lock before classifying or inheriting it.
    db.session.refresh(post, ["kind", "safety", "user_id", "user", "tags"])
    if post.kind != "card":
        return
    document = db.session.get(model.PostDocument, post.post_id)
    if document is not None:
        row = db.session.get(Card, post.post_id)
        if row is None or row.data_hash is None:
            after_card(post.post_id, document.data)
        return
    if (
        db.session.scalar(
            sa.select(model.PostContent.post_content_id)
            .where(
                model.PostContent.post_id == post.post_id,
                model.PostContent.kind.in_(card_format.KINDS),
            )
            .limit(1)
        )
        is None
    ):
        return
    data = build_version_data(post, user)
    documents.create(post, "card", data, user, "Read from the file.")


def build_version_data(post: model.Post, user: model.User | None) -> registry.Payload:
    """Build the file's card data and find or create its linked lorebook.

    The caller holds the post lock and owns the surrounding transaction.
    Missing extracted card content refuses replacement instead of preserving
    the previous document with unrelated file data.
    """
    row = db.session.scalar(
        sa.select(model.PostContent)
        .where(
            model.PostContent.post_id == post.post_id,
            model.PostContent.kind.in_(card_format.KINDS),
        )
        .order_by(model.PostContent.post_content_id)
        .options(undefer(model.PostContent.payload))
        .limit(1)
    )
    if row is None:
        raise errors.ValidationError("The file has no character card.")
    data, book = split_card(row.kind, row.payload["card"])
    if book is not None:
        book = validate_lorebook(book)
        digest = hashlib.sha256(documents.encode_content(book)).hexdigest()
        # Tags may have been created in this upload after request visibility
        # was first computed. Use the canonical tag walk on the flushed state.
        hiding = visibility.hiding_tag_ids(refresh=True)
        nsfw = any(tag.tag_id in hiding for tag in post.tags)
        tagged = (
            sa.exists()
            .where(model.PostTag.post_id == model.Post.post_id)
            .where(model.PostTag.tag_id.in_(hiding))
        )
        match = db.session.execute(
            sa.select(model.Post.post_id, model.Post.safety)
            .join(model.PostDocument, model.PostDocument.post_id == model.Post.post_id)
            .where(
                model.Post.kind == "lorebook",
                model.PostDocument.kind == "lorebook",
                model.PostDocument.hash == digest,
                tagged if nsfw else ~tagged,
            )
            .order_by(model.Post.post_id)
            .limit(1)
            .execution_options(**{visibility.ALL_POSTS: True})
        ).first()
        if match is None:
            new = posts.create_fileless_post(
                "lorebook",
                post.user,
                post.safety,
                [visibility.nsfw_tag()] if nsfw else [],
            )
            db.session.flush()
            documents.create(new, "lorebook", book, user, f"From card {post.post_id}.")
            book_id = new.post_id
        else:
            book_id, safety = match
            order = [
                model.Post.SAFETY_SAFE,
                model.Post.SAFETY_SKETCHY,
                model.Post.SAFETY_UNSAFE,
            ]
            if order.index(post.safety) > order.index(safety):
                # Never cache a hidden entity across the visibility boundary.
                db.session.execute(
                    sa.update(model.Post)
                    .where(
                        model.Post.post_id == book_id,
                        model.Post.safety.in_(order[: order.index(post.safety)]),
                    )
                    .values(safety=post.safety)
                )
        data["lorebooks"] = [book_id]
    return data
