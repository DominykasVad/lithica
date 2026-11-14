"""Post kinds, distinct from the kinds of extracted content that support them."""

from lithica import db, errors, model, registry


class InvalidPostKindError(errors.ValidationError):
    """The requested post kind is unknown or unsupported by this post."""


def supported_kinds(post: model.Post) -> list[str]:
    """List the choices this post supports, independently of its stored kind.

    Engine file types support media. Matching content rows owned by loaded
    modules support their post kinds, in configuration/declaration order.
    Rows belonging to switched-off modules do not contribute.
    """
    result = []
    if post.type in {
        model.Post.TYPE_IMAGE,
        model.Post.TYPE_ANIMATION,
        model.Post.TYPE_VIDEO,
        model.Post.TYPE_FLASH,
    }:
        result.append(model.Post.KIND_MEDIA)
    contents = {row.kind for row in post.contents} & registry.content_kinds().keys()
    result.extend(
        kind.name for kind in registry.post_kinds() if contents & kind.content_kinds
    )
    return result


def derived_kind(post: model.Post) -> str:
    """Choose the first supported loaded post kind, falling back to media.

    This computes the upload/backfill default without changing the post;
    a manually selected kind may differ from the derived kind.
    """
    supported = supported_kinds(post)
    return next(
        (kind.name for kind in registry.post_kinds() if kind.name in supported),
        model.Post.KIND_MEDIA,
    )


def _assign_kind(post: model.Post, kind: str) -> None:
    from lithica.func import post_content

    previous = post.kind
    with db.session.no_autoflush:
        post.kind = kind
        try:
            post_content.check_duplicates(
                post,
                [
                    registry.ExtractedContent(row.kind, row.payload)
                    for row in post.contents
                ],
            )
        except Exception:
            post.kind = previous
            raise


def derive_existing(post: model.Post) -> None:
    """Set an existing post's derived kind, retaining disabled-module kinds.

    Backfill calls this explicitly for every post. Reextract calls it only
    after successful extraction changes the loaded content-kind set or
    leaves the stored kind unsupported, preserving other manual choices.
    """
    from lithica.func import documents, posts

    if documents.have_documents([post], lock=True):
        return
    before = post.kind
    if post.kind == model.Post.KIND_MEDIA or post.kind in {
        kind.name for kind in registry.post_kinds()
    }:
        derived = derived_kind(post)
        if derived != post.kind:
            try:
                _assign_kind(post, derived)
            except posts.PostAlreadyUploadedError:
                # Reextract/backfill keeps media rather than making a second card.
                return
    if post.kind != before:
        from lithica.func import post_content

        post_content.after_file_or_kind(post, None)


def set_kind(post: model.Post, kind: str) -> bool:
    """Select a supported post kind and return whether it changed.

    Unknown, disabled or unsupported kinds raise InvalidPostKindError with
    the supported choices. Selecting the current kind is a no-op. Version
    bumps and snapshots are the caller's responsibility.
    """
    from lithica.func import posts

    posts.require_file(post)
    from lithica.func import documents

    if documents.have_documents([post], lock=True):
        raise InvalidPostKindError("A post with a document cannot change kind.")
    supported = supported_kinds(post)
    if kind not in supported:
        raise InvalidPostKindError(
            "Unsupported post kind %r. Supported kinds: %s."
            % (kind, ", ".join(supported) or "none")
        )
    if post.kind == kind:
        return False
    _assign_kind(post, kind)
    return True
