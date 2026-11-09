"""Derived tokens let owners and exports reuse a URL without storing it.

Only salts and lookup hashes are stored. Changing secret ends every link.
"""

import base64
import datetime
import hmac
import secrets
from typing import Any

import sqlalchemy as sa

from lithica import config, db, errors, model
from lithica.func import auth, posts, users, util, visibility


def derive_token(salt: bytes) -> str:
    digest = hmac.digest(
        config.config["secret"].encode(), b"lithica-share-link:" + salt, "sha256"
    )
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def create(
    post: model.Post, user: model.User, note: str | None, expires_at: str | None
) -> model.ShareLink:
    if visibility.is_nsfw(post) and not config.config.get("share_links_nsfw", False):
        raise errors.ValidationError("Share links for NSFW posts are disabled.")
    if note is not None and len(note) > 128:
        raise errors.ValidationError(
            "A share link note may have at most 128 characters."
        )
    expiry = None
    if expires_at is not None:
        try:
            expiry = datetime.datetime.fromisoformat(expires_at)
            if expiry.tzinfo is not None:
                expiry = expiry.astimezone(datetime.UTC).replace(tzinfo=None)
        except ValueError:
            raise errors.ValidationError("Invalid share link expiry.") from None
        if expiry <= util.utcnow():
            raise errors.ValidationError("Share link expiry must be in the future.")
    # Lock the post so concurrent processes cannot exceed the cap.
    db.session.execute(
        sa.select(model.Post.post_id)
        .where(model.Post.post_id == post.post_id)
        .with_for_update()
    )
    if db.session.query(model.ShareLink).filter_by(post_id=post.post_id).count() >= 100:
        raise errors.ValidationError("A post may have at most 100 share links.")
    salt = secrets.token_bytes(32)
    link = model.ShareLink(
        post_id=post.post_id,
        user_id=user.user_id,
        salt=salt,
        token_hash=auth.hash_token(derive_token(salt)),
        note=note,
        creation_time=util.utcnow(),
        expires_at=expiry,
    )
    db.session.add(link)
    db.session.flush()
    return link


def expired(link: model.ShareLink) -> bool:
    return link.expires_at is not None and link.expires_at <= util.utcnow()


# Any: heterogeneous resource values described by the API response model.
def serialize(link: model.ShareLink) -> dict[str, Any]:
    return {
        "id": link.id,
        "postId": link.post_id,
        "user": users.serialize_micro_user(link.user, link.user),
        "note": link.note,
        "creationTime": link.creation_time,
        "expiresAt": link.expires_at,
        "expired": expired(link),
        "url": (config.config.get("domain") or "").rstrip("/")
        + "/share/"
        + derive_token(link.salt),
    }


def delivery(token: str) -> tuple[str, str]:
    def missing() -> errors.NotFoundError:
        return errors.NotFoundError("Share link not found.")

    link = (
        db.session.query(model.ShareLink)
        .filter_by(token_hash=auth.hash_token(token))
        .one_or_none()
    )
    if link is None or expired(link):
        raise missing()
    if not hmac.compare_digest(
        auth.hash_token(derive_token(link.salt)), link.token_hash
    ):
        raise missing()
    # Columns only past visibility: no hidden entity stays in the session.
    row = db.session.execute(
        sa.select(model.Post.post_id, model.Post.mime_type).where(
            model.Post.post_id == link.post_id
        ),
        execution_options={visibility.ALL_POSTS: True},
    ).one_or_none()
    if row is None:
        raise missing()
    nsfw = (
        db.session.execute(
            sa.select(model.PostTag.post_id).where(
                model.PostTag.post_id == link.post_id,
                model.PostTag.tag_id.in_(sorted(visibility.hiding_tag_ids())),
            ),
            execution_options={visibility.ALL_POSTS: True},
        ).first()
        is not None
    )
    if nsfw and not config.config.get("share_links_nsfw", False):
        raise missing()
    # Transient object computes the canonical path without loading an entity.
    post = model.Post(post_id=row.post_id, mime_type=row.mime_type)
    return posts.get_post_content_path(post).removeprefix("posts/"), row.mime_type
