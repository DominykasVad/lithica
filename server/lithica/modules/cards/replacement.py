"""Replace a card file without passing failures through best-effort hooks."""

import sqlalchemy as sa

from lithica import db, errors, model
from lithica.func import (
    auth,
    documents,
    files,
    post_metadata,
    posts,
    snapshots,
    util,
    versions,
    visibility,
)
from lithica.func.content import ContentLike
from lithica.modules.cards import pictures, uploads


class CardNotFoundError(errors.NotFoundError):
    pass


def card_document(post: model.Post, *, lock: bool = False) -> model.PostDocument:
    if lock:
        documents.have_documents([post], lock=True)
        db.session.refresh(post)
    document = db.session.get(model.PostDocument, post.post_id)
    if post.kind != "card" or document is None or document.kind != "card":
        raise CardNotFoundError("Post %d has no character card." % post.post_id)
    return document


def old_picture(post: model.Post) -> bytes | None:
    if not posts.has_file(post):
        return None
    stored = files.get(posts.get_post_content_path(post))
    return pictures.picture(stored) if stored is not None else None


def _existing_picture(content: bytes) -> tuple[int | None, bool]:
    checksum = util.get_sha1(content)
    # A retired file cannot become a kept post, regardless of its owner.
    if (
        db.session.scalar(
            sa.select(model.PostRetiredChecksum.post_id)
            .where(model.PostRetiredChecksum.checksum == checksum)
            .execution_options(**{visibility.ALL_POSTS: True})
        )
        is not None
    ):
        return None, False
    # Read IDs only across visibility; never cache a hidden entity.
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


def replace(
    post: model.Post,
    content: ContentLike,
    based_on: int,
    keep_old_picture: bool,
    user: model.User,
) -> tuple[int | None, bool]:
    document = card_document(post, lock=True)
    versions.verify_version(post, based_on)
    if util.get_sha1(content) == post.checksum:
        raise posts.InvalidPostContentError("The new file is the post's current file.")
    old = old_picture(post)
    same = pictures.same_pixels(old, pictures.picture(content))
    original_checksum = post.checksum
    original_png = post.mime_type == "image/png"

    # Metadata and signatures may flush. No file reaches storage until all
    # document and relation work below has succeeded.
    posts.update_post_content(post, content, allow_document=True, defer_file=True)
    auto_tags = posts.update_post_auto_tags(post)
    data = uploads.build_version_data(post, user)
    data["avatar"] = document.data.get("avatar")
    documents.write(post, data, document.version, user, "File replaced.")

    kept_id: int | None = None
    kept: model.Post | None = None
    if old is not None and not same and keep_old_picture:
        kept_id, allowed = _existing_picture(old)
        if allowed:
            auth.verify_privilege(user, "posts:edit:typed_relations")
            if kept_id is None:
                names = [visibility.nsfw_tag()] if visibility.is_nsfw(post) else []
                kept, _ = posts.create_post(
                    old, names, user, defer_file=True, as_media=True
                )
                kept.kind = "media"
                kept.listed = False
                kept.safety = post.safety
                db.session.flush()
                kept_id = kept.post_id
                snapshots.create(kept, user)
            for role in ("avatar-of", "gallery-of"):
                existing = db.session.scalar(
                    sa.select(model.PostTypedRelation.typed_relation_id).where(
                        model.PostTypedRelation.from_post_id == kept_id,
                        model.PostTypedRelation.to_post_id == post.post_id,
                        model.PostTypedRelation.type == role,
                    )
                )
                if existing is None:
                    assert kept_id is not None
                    post_metadata.create_typed_relation(
                        kept_id, post.post_id, role, None, user
                    )
    if original_checksum is not None and not (original_png and kept_id is not None):
        posts.retire_checksum(post, original_checksum, "replaced")
    versions.bump_version(post)
    post.last_edit_time = util.utcnow()
    db.session.flush()
    for tag in auto_tags:
        snapshots.create(tag, user)
    snapshots.modify(post, user)
    db.session.flush()
    posts.release_post_content(post)
    if kept is not None:
        posts.release_post_content(kept)
    return kept_id, same
