"""Validate a complete image list before creating any imported post."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from lithica import errors, model
from lithica.func import auth, file_uploads, mime, post_metadata, posts, util
from lithica.func.content import ContentLike
from lithica.modules.cards import media

Role = Literal["avatar", "alternate-avatar", "gallery", "expression"]


@dataclass(frozen=True)
class Image:
    role: Role
    token: str | None = None
    post_id: int | None = None
    label: str | None = None


@dataclass(frozen=True)
class Prepared:
    index: int
    role: str
    relation: str
    label: str | None
    content: ContentLike | None = None
    post: model.Post | None = None


def _invalid(index: int, message: str) -> errors.ValidationError:
    return errors.ValidationError(f"Image {index}: {message}")


def prepare(images: Sequence[Image], user: model.User) -> list[Prepared]:
    if len(images) > 200:
        raise errors.ValidationError("At most 200 images are allowed.")
    if images:
        auth.verify_privilege(user, "posts:edit:typed_relations")
    if sum(item.role == "avatar" for item in images) > 1:
        raise errors.ValidationError("At most one main avatar is allowed.")
    seen: set[tuple[str, str]] = set()
    prepared: list[Prepared] = []
    for index, image in enumerate(images):
        if (image.token is None) == (image.post_id is None):
            raise _invalid(index, "supply exactly one token or postId.")
        try:
            label = post_metadata.clean_label(image.label)
        except errors.ValidationError as error:
            raise _invalid(index, str(error)) from None
        if image.role == "expression" and label is None:
            raise _invalid(index, "an expression needs a label.")
        relation = {
            "avatar": "avatar-of",
            "alternate-avatar": "avatar-of",
            "gallery": "gallery-of",
            "expression": "expression-of",
        }[image.role]
        content = None
        post = None
        if image.token is not None:
            content = file_uploads.get(image.token)
            if content is None:
                raise _invalid(index, "the temporary upload is missing or expired.")
            mime_type = mime.get_mime_type(content)
            if not (mime.is_image(mime_type) or mime.is_video(mime_type)):
                raise _invalid(
                    index, "the token must contain an image, animation or video."
                )
            identity = util.get_sha1(content)
        else:
            assert image.post_id is not None
            post = posts.try_get_post_by_id(image.post_id)
            if post is None or post.kind != "media":
                raise _invalid(index, "postId must name visible media.")
            identity = post.checksum or f"post:{post.post_id}"
        if (identity, relation) in seen:
            raise _invalid(index, "the same image has the same relation type twice.")
        seen.add((identity, relation))
        prepared.append(Prepared(index, image.role, relation, label, content, post))
    return prepared


def attach(
    parent: model.Post, images: Sequence[Prepared], user: model.User
) -> tuple[int | None, list[int], list[model.Post]]:
    avatar = None
    skipped: list[int] = []
    created: list[model.Post] = []
    for image in images:
        post = image.post
        if image.content is not None:
            post, new = media.obtain(image.content, parent, user)
            if new:
                assert post is not None
                created.append(post)
        if post is None:
            skipped.append(image.index)
            continue
        try:
            media.relate(post, parent, image.relation, image.label, user)
        except posts.PostNotFoundError:
            # Visibility may change after preparation; never echo a token's ID.
            if image.content is None:
                raise errors.ValidationError(
                    f"Image {image.index}: postId must name visible media."
                ) from None
            skipped.append(image.index)
            continue
        if image.role == "avatar":
            avatar = post.post_id
    return avatar, skipped, created
