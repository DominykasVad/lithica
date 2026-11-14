"""Replace a card file without passing failures through best-effort hooks."""

from lithica import db, errors, model
from lithica.func import (
    documents,
    files,
    posts,
    snapshots,
    util,
    versions,
)
from lithica.func.content import ContentLike
from lithica.modules.cards import media, pictures, uploads


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
        picture, created = media.obtain(old, post, user)
        if picture is not None:
            kept_id = picture.post_id
            if created:
                kept = picture
            for role in ("avatar-of", "gallery-of"):
                media.relate(picture, post, role, None, user)
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
