"""Deferred, unlisted media shared by file replacement and data imports."""

import sqlalchemy as sa

from lithica import db, model
from lithica.func import auth, files, post_metadata, posts, snapshots, util, visibility
from lithica.func.content import ContentLike


def existing(content: ContentLike) -> tuple[int | None, bool]:
    checksum = util.get_sha1(content)
    if (
        db.session.scalar(
            sa.select(model.PostRetiredChecksum.post_id)
            .where(model.PostRetiredChecksum.checksum == checksum)
            .execution_options(**{visibility.ALL_POSTS: True})
        )
        is not None
    ):
        return None, False
    row = db.session.execute(
        sa.select(model.Post.post_id, model.Post.kind)
        .where(model.Post.checksum == checksum)
        .execution_options(**{visibility.ALL_POSTS: True})
    ).first()
    if row is None:
        return None, True
    visible = posts.try_get_post_by_id(row.post_id)
    if visible is None or row.kind != "media":
        return None, False
    return row.post_id, True


def obtain(
    content: ContentLike, parent: model.Post, user: model.User
) -> tuple[model.Post | None, bool]:
    """Reuse visible media unchanged, or prepare a new media post without files."""
    post_id, allowed = existing(content)
    if not allowed:
        return None, False
    auth.verify_privilege(user, "posts:edit:typed_relations")
    if post_id is not None:
        return posts.try_get_post_by_id(post_id), False
    names = [visibility.nsfw_tag()] if visibility.is_nsfw(parent) else []
    post, _new_tags = posts.create_post(
        content, names, user, defer_file=True, as_media=True
    )
    posts.update_post_flags(post, posts.get_default_flags(content))
    post.listed = False
    post.safety = parent.safety
    db.session.flush()
    snapshots.create(post, user)
    return post, True


def relate(
    post: model.Post, parent: model.Post, role: str, label: str | None, user: model.User
) -> None:
    found = db.session.scalar(
        sa.select(model.PostTypedRelation.typed_relation_id).where(
            model.PostTypedRelation.from_post_id == post.post_id,
            model.PostTypedRelation.to_post_id == parent.post_id,
            model.PostTypedRelation.type == role,
        )
    )
    if found is None:
        post_metadata.create_typed_relation(
            post.post_id, parent.post_id, role, label, user
        )


def release(created: list[model.Post]) -> list[str]:
    """Return only new paths so a failed transaction can remove partial files."""
    paths = [
        path
        for post in created
        for path in (
            posts.get_post_content_path(post),
            posts.get_post_thumbnail_path(post),
        )
    ]
    for post in created:
        posts.release_post_content(post)
    return paths


def discard(paths: list[str]) -> None:
    for path in paths:
        files.delete(path)
