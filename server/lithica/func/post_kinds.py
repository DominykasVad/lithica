"""Post kinds, distinct from the kinds of extracted content that support them."""

from lithica import errors, model, registry


class InvalidPostKindError(errors.ValidationError):
    """The requested post kind is unknown or unsupported by this post."""


def supported_kinds(post: model.Post) -> list[str]:
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
    supported = supported_kinds(post)
    return next(
        (kind.name for kind in registry.post_kinds() if kind.name in supported),
        model.Post.KIND_MEDIA,
    )


def derive_existing(post: model.Post) -> None:
    """Keep disabled modules' stored post kinds; derive all others."""
    if post.kind == model.Post.KIND_MEDIA or post.kind in {
        kind.name for kind in registry.post_kinds()
    }:
        post.kind = derived_kind(post)


def set_kind(post: model.Post, kind: str) -> bool:
    supported = supported_kinds(post)
    if kind not in supported:
        raise InvalidPostKindError(
            "Unsupported post kind %r. Supported kinds: %s."
            % (kind, ", ".join(supported) or "none")
        )
    if post.kind == kind:
        return False
    post.kind = kind
    return True
