"""The current file's image map and repeat-safe ingestion into engine media."""

import logging
from dataclasses import dataclass, field

import sqlalchemy as sa
from sqlalchemy.orm import lazyload

from lithica import db, model
from lithica.func import documents, files, jobs, posts
from lithica.func.content import ContentLike
from lithica.modules.cards import assets, charx, media
from lithica.modules.cards.model import Card, CardImage

logger = logging.getLogger(__name__)


@dataclass
class Result:
    avatar: int | None = None
    pending: bool = False
    created: list[model.Post] = field(default_factory=list[model.Post])


def attach(
    post: model.Post,
    source: assets.Source,
    images: list[assets.Image],
    user: model.User | None,
    *,
    preferred_avatar: model.Post | None = None,
) -> Result:
    result = Result()
    skipped = 0
    for image in images:
        existing = db.session.get(CardImage, (post.post_id, image.uri))
        if existing is not None:
            visible = posts.try_get_post_by_id(existing.post_id)
            if visible is None or visible.kind != "media":
                skipped += 1
                continue
            if image.main:
                result.avatar = existing.post_id
            continue
        try:
            with db.session.begin_nested():
                content = source.picture(image)
                if content is None:
                    skipped += 1
                    continue
                if image.main and preferred_avatar is not None:
                    picture, created = preferred_avatar, False
                else:
                    picture, created = media.obtain(content, post, user, from_file=True)
                if picture is None:
                    skipped += 1
                    continue
                media.relate(
                    picture, post, image.relation, image.label, user, created=created
                )
                db.session.add(
                    CardImage(
                        card_post_id=post.post_id,
                        uri=image.uri,
                        post_id=picture.post_id,
                        type=image.relation,
                        asset_type=image.asset_type,
                        label=image.label,
                        position=image.position,
                    )
                )
                db.session.flush()
            if created:
                result.created.append(picture)
            if image.main:
                result.avatar = picture.post_id
        except Exception:
            # One malformed image, an unavailable duplicate or a relation limit
            # cannot lose the card. Never log names, URIs, paths or payloads.
            skipped += 1
    if skipped:
        logger.info("Card file images skipped: %d", skipped)
    return result


def start(
    post: model.Post,
    user: model.User | None,
    content: ContentLike | None = None,
    *,
    preferred_avatar: model.Post | None = None,
) -> Result:
    """Read only the main picture in the request; schedule the remaining work."""
    db.session.execute(
        sa.delete(CardImage).where(CardImage.card_post_id == post.post_id)
    )
    if content is None and posts.has_file(post):
        content = files.get(posts.get_post_content_path(post))
    if content is None:
        return Result()
    try:
        with assets.opened(content) as source:
            result = attach(
                post,
                source,
                [i for i in source.images if i.main],
                user,
                preferred_avatar=preferred_avatar,
            )
            result.pending = any(not i.main for i in source.images)
    except (charx.NotCharx, charx.Rejected):
        return Result()
    if result.pending:
        jobs.enqueue(
            "cards-images", {"postId": post.post_id, "checksum": post.checksum}
        )
    return result


def finish(post: model.Post, result: Result) -> None:
    row = db.session.get(Card, post.post_id)
    assert row is not None
    row.images_read = not result.pending
    media.release(result.created)


def read_all(post: model.Post, user: model.User | None) -> Result:
    content = files.get(posts.get_post_content_path(post))
    if content is None:
        return Result()
    try:
        with assets.opened(content) as source:
            result = Result()
            for image in source.images:
                item = attach(post, source, [image], user)
                if image.main:
                    result.avatar = item.avatar
                # Keep only one image's bytes in memory. The engine tracks the
                # new files through the outer transaction and removes them on
                # rollback, including files from completed image savepoints.
                media.release(item.created)
                db.session.flush()
            return result
    except (charx.NotCharx, charx.Rejected):
        return Result()


def backfill(post: model.Post, user: model.User | None) -> None:
    row = db.session.get(Card, post.post_id)
    if row is None or row.images_read or not posts.has_file(post):
        return
    result = read_all(post, user)
    document = documents.get(post)
    if document.data.get("avatar") is None and result.avatar is not None:
        data = {**document.data, "avatar": result.avatar}
        documents.write(
            post, data, document.version, user, "Images read from the file."
        )
    finish(post, result)


def list_images(post_id: int) -> list[dict[str, object]]:
    rows = db.session.execute(
        sa.select(CardImage, model.Post)
        .join(model.Post, model.Post.post_id == CardImage.post_id)
        .where(CardImage.card_post_id == post_id, model.Post.kind == "media")
        .order_by(CardImage.position, CardImage.uri)
        .options(lazyload("*"))
    )
    return [
        {
            "uri": row.uri,
            "assetType": row.asset_type,
            "relation": row.type,
            "label": row.label,
            "post": {
                "id": picture.post_id,
                "mimeType": picture.mime_type,
                "contentUrl": posts.get_post_content_url(picture),
                "thumbnailUrl": posts.get_post_thumbnail_url(picture),
            },
        }
        for row, picture in rows
    ]
