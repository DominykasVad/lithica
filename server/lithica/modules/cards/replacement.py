"""Replace a card file without passing failures through best-effort hooks."""

import sqlalchemy as sa

from lithica import db, errors, model
from lithica.func import (
    documents,
    files,
    posts,
    snapshots,
    util,
    versions,
    visibility,
)
from lithica.func.content import ContentLike
from lithica.modules.cards import file_images, media, pictures, uploads


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
    old_id, allowed = media.existing(old) if old is not None else (None, False)
    old_media = posts.try_get_post_by_id(old_id) if old_id is not None else None

    # The document and image map are validated before any deferred file is saved.
    posts.update_post_content(post, content, allow_document=True, defer_file=True)
    auto_tags = posts.update_post_auto_tags(post)
    data = uploads.build_version_data(post, user)
    images = file_images.start(
        post, user, content, preferred_avatar=old_media if same else None
    )
    data["avatar"] = (
        document.data.get("avatar")
        if original_checksum is None and document.data.get("avatar") is not None
        else images.avatar
    )
    documents.write(post, data, document.version, user, "File replaced.")

    kept_id: int | None = None
    if old is not None and not same and keep_old_picture and allowed:
        if old_media is None:
            old_media, created = media.obtain(old, post, user, from_file=True)
            if created and old_media is not None:
                images.created.append(old_media)
        if old_media is not None:
            kept_id = old_media.post_id
            for role in ("avatar-of", "gallery-of"):
                media.relate(old_media, post, role, None, user)
    elif (
        not same
        and not keep_old_picture
        and old_media is not None
        and old_media.post_id != images.avatar
    ):
        db.session.execute(
            sa.delete(model.PostTypedRelation).where(
                model.PostTypedRelation.from_post_id == old_media.post_id,
                model.PostTypedRelation.to_post_id == post.post_id,
                model.PostTypedRelation.type == "avatar-of",
            )
        )
        db.session.execute(
            sa.select(model.Post.post_id)
            .where(model.Post.post_id == old_media.post_id)
            .with_for_update()
        )
        remaining = db.session.scalar(
            sa.select(model.PostTypedRelation.typed_relation_id)
            .where(
                sa.or_(
                    model.PostTypedRelation.from_post_id == old_media.post_id,
                    model.PostTypedRelation.to_post_id == old_media.post_id,
                )
            )
            .limit(1)
            .execution_options(**{visibility.ALL_POSTS: True})
        )
        if remaining is None:
            snapshots.delete(old_media, user)
            posts.delete(old_media, defer_files=True)
    if original_checksum is not None:
        posts.retire_checksum(post, original_checksum, "replaced")
    file_images.finish(post, images)
    versions.bump_version(post)
    post.last_edit_time = util.utcnow()
    db.session.flush()
    for tag in auto_tags:
        snapshots.create(tag, user)
    snapshots.modify(post, user)
    db.session.flush()
    posts.release_post_content(post)
    return kept_id, same
