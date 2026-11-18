"""The persistent URL map and viewer-filtered image resources."""

from collections.abc import Iterable
from hashlib import sha256
from itertools import batched

import sqlalchemy as sa
from sqlalchemy.orm import lazyload

from lithica import db, model, registry
from lithica.func import posts
from lithica.modules.cards import image_links
from lithica.modules.cards.model import ArchivedLink


def url_hash(url: str) -> str:
    return sha256(url.encode("utf-8")).hexdigest()


def current(post_id: int, urls: Iterable[str]) -> dict[str, ArchivedLink]:
    hashes = [url_hash(url) for url in urls]
    if not hashes:
        return {}
    rows = db.session.scalars(
        sa.select(ArchivedLink).where(
            ArchivedLink.card_post_id == post_id, ArchivedLink.url_hash.in_(hashes)
        )
    )
    return {row.url: row for row in rows}


def visible_posts(ids: Iterable[int]) -> dict[int, model.Post]:
    found: dict[int, model.Post] = {}
    valid = (id_ for id_ in dict.fromkeys(ids) if 0 < id_ <= 2**31 - 1)
    for batch in batched(valid, 500, strict=False):
        rows = db.session.scalars(
            sa.select(model.Post)
            .where(model.Post.post_id.in_(batch))
            .options(lazyload("*"))
        )
        found.update((post.post_id, post) for post in rows)
    return found


def _resource(post: model.Post | None) -> dict[str, object] | None:
    if post is None:
        return None
    return {
        "id": post.post_id,
        "mimeType": post.mime_type,
        "contentUrl": posts.get_post_content_url(post),
        "thumbnailUrl": posts.get_post_thumbnail_url(post),
    }


def describe(post_id: int, data: registry.Payload) -> dict[str, object]:
    urls, references, untracked = image_links.collect(data)
    rows = current(post_id, urls)
    visible = visible_posts(
        [
            *references,
            *(row.post_id for row in rows.values() if row.post_id is not None),
        ]
    )
    links: list[dict[str, object]] = []
    for url in urls:
        row = rows.get(url)
        links.append(
            {
                "url": url,
                "status": row.status if row else "new",
                "reason": row.reason if row else None,
                "attempts": row.attempts if row else 0,
                "lastAttemptTime": row.last_attempt_time if row else None,
                "post": _resource(visible.get(row.post_id))
                if row is not None and row.post_id is not None
                else None,
            }
        )
    return {
        "links": links,
        "references": [
            {"id": id_, "post": _resource(visible.get(id_))} for id_ in references
        ],
        "untrackedLinks": untracked,
    }
