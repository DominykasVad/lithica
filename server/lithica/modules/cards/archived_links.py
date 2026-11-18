"""The persistent URL map and viewer-filtered image resources."""

from collections.abc import Iterable
from copy import deepcopy
from hashlib import sha256
from itertools import batched

import sqlalchemy as sa
from sqlalchemy.orm import lazyload

from lithica import db, model, registry
from lithica.func import documents, posts, versions
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


def replace_in_document(post: model.Post, version: int, user: model.User) -> int:
    document = documents.get(post, lock=True)
    db.session.refresh(post, ["kind"])
    if post.kind != "card" or document.kind != "card":
        raise documents.DocumentNotFoundError("Card document not found.")
    versions.verify_version(document, version)

    archived = db.session.execute(
        sa.select(ArchivedLink.url, ArchivedLink.post_id).where(
            ArchivedLink.card_post_id == post.post_id,
            ArchivedLink.status == "archived",
            ArchivedLink.post_id.is_not(None),
        )
    ).all()
    visible = visible_posts(row.post_id for row in archived)
    targets = {row.url: row.post_id for row in archived if row.post_id in visible}
    if not targets:
        return 0
    data = deepcopy(document.data)
    replaced = image_links.replace(data, targets)
    if replaced:
        documents.write(
            post,
            data,
            version,
            user if user.rank != model.User.RANK_ANONYMOUS else None,
            "Archived links replaced with Lithica references.",
        )
    return replaced
