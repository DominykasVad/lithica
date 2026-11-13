"""Create and update fileless cards and books within the caller's transaction."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal

import sqlalchemy as sa

from lithica import db, errors, model, registry
from lithica.func import (
    auth,
    documents,
    post_metadata,
    posts,
    snapshots,
    tags,
    visibility,
)
from lithica.modules.cards import card as card_format
from lithica.modules.cards import documents as card_documents
from lithica.modules.cards import related_images, uploads


@dataclass(frozen=True)
class Options:
    safety: str | None = None
    tags: list[str] = field(default_factory=list[str])
    external_ids: list[tuple[str, str]] | None = None
    note: str | None = None
    version: int | None = None


Outcome = Literal["created", "updated", "unchanged"]


def _external_target(pairs: list[tuple[str, str]], kind: str) -> model.Post | None:
    for host, external_id in pairs:
        post_metadata.validate_external_id(host, external_id)
    ids: set[int] = (
        set(
            db.session.scalars(
                sa.select(model.PostExternalId.post_id)
                .where(
                    sa.tuple_(
                        model.PostExternalId.host, model.PostExternalId.external_id
                    ).in_(pairs)
                )
                .execution_options(**{visibility.ALL_POSTS: True})
            )
        )
        if pairs
        else set()
    )
    if not ids:
        return None
    if len(ids) == 1:
        post = posts.try_get_post_by_id(ids.pop())
        if post is not None and post.kind == kind:
            document = db.session.get(model.PostDocument, post.post_id)
            if document is not None and document.kind == kind:
                return post
    raise post_metadata.ExternalIdTakenError("External ID is already taken.")


def _resolve(kind: str, data: registry.Payload, options: Options) -> model.Post | None:
    target = _external_target(options.external_ids or [], kind)
    if target is not None:
        return target
    if kind == "card":
        duplicate = card_documents.find_card(
            card_documents.card_key(data["spec"], data["card"])
        )
    else:
        # A book is shared only on the same side of the NSFW tag line.
        existing = tags.get_tags_by_names(options.tags)
        hiding = visibility.hiding_tag_ids(refresh=True)
        nsfw = visibility.nsfw_tag().lower() in {
            name.lower() for name in options.tags
        } or any(t.tag_id in hiding for t in existing)
        match = uploads.find_book(data, nsfw)
        duplicate = match[0] if match is not None else None
    if duplicate is None:
        return None
    post = posts.try_get_post_by_id(duplicate)
    if options.external_ids:
        if (
            post is None
            or post.kind != kind
            or db.session.get(model.PostDocument, duplicate) is None
        ):
            raise post_metadata.ExternalIdTakenError("External ID is already taken.")
        return post
    raise posts.PostAlreadyUploadedError(post)


def _add_ids(post: model.Post, options: Options, user: model.User) -> None:
    if options.external_ids is not None:
        current = [(row.host, row.external_id) for row in post.external_ids]
        post_metadata.replace_external_ids(post, current + options.external_ids, user)


def _current_document(post: model.Post) -> model.PostDocument:
    try:
        document = documents.get(post, lock=True)
    except documents.DocumentNotFoundError:
        raise post_metadata.ExternalIdTakenError(
            "External ID is already taken."
        ) from None
    # The post lock protects inheritance from concurrent metadata edits.
    db.session.refresh(post, ["kind", "safety", "tags"])
    visibility.hiding_tag_ids(refresh=True)
    return document


def _new_post(
    kind: str,
    user: model.User,
    options: Options,
    spec: str | None = None,
    stored: registry.Payload | None = None,
) -> tuple[model.Post, list[model.Tag]]:
    if options.safety is None:
        raise errors.MissingRequiredParameterError(
            "Required parameter 'safety' is missing."
        )
    post = posts.create_fileless_post(kind, user, options.safety)
    new_tags = posts.update_post_tags(post, options.tags)
    if spec is not None and stored is not None:
        from lithica.modules.cards import auto_tag

        wanted = auto_tag([registry.ExtractedContent(spec, {"card": stored})])
        names = [
            (category, name)
            for category, group in wanted.items()
            for name in group
            if tags.is_valid_name(name)
        ]
        new_tags += posts.update_post_auto_tags(post, wanted=names)
    if new_tags:
        auth.verify_privilege(user, "tags:create")
    db.session.flush()
    return post, new_tags


def _check_options(options: Options, user: model.User) -> None:
    if options.external_ids is not None:
        auth.verify_privilege(user, "posts:edit:external_ids")
    if options.note is not None and (
        "\x00" in options.note or any(0xD800 <= ord(c) <= 0xDFFF for c in options.note)
    ):
        raise errors.ValidationError("Notes cannot contain NUL or lone surrogates.")
    if options.note is not None and len(options.note) > 256:
        raise errors.ValidationError("A document note may have at most 256 characters.")


def create_card(
    raw: registry.Payload,
    user: model.User,
    options: Options,
    lorebooks: list[int],
    images: Sequence[related_images.Prepared] = (),
) -> tuple[model.Post, Outcome, list[int], list[model.Post]]:
    _check_options(options, user)
    spec = card_format.kind_of(raw)
    stored = card_format.stored(raw)
    if spec is None or stored is None:
        raise errors.ValidationError("Invalid character card.")
    if len(documents.encode_content(stored)) > card_format.MAX_CARD_SIZE:
        raise errors.ValidationError("Card exceeds its size limit.")
    data, book = card_documents.split_card(spec, stored)
    target = _resolve("card", data, options)
    new_tags: list[model.Tag] = []
    if target is None:
        target, new_tags = _new_post("card", user, options, spec, stored)
        current = None
    else:
        auth.verify_privilege(user, "posts:edit:document")
        current = _current_document(target)
        data["avatar"] = current.data.get("avatar")
    # Explicit links must name visible lorebooks; validation on document restore
    # is separately viewer-independent and drops deleted links.
    ids = list(dict.fromkeys(lorebooks))
    visible = set(
        db.session.scalars(
            sa.select(model.Post.post_id).where(
                model.Post.post_id.in_(ids), model.Post.kind == "lorebook"
            )
        )
    )
    if set(ids) != visible:
        raise errors.ValidationError("Lorebooks must name visible lorebook posts.")
    uploads.link_embedded_book(data, book, target, user)
    data["lorebooks"] = list(dict.fromkeys(data["lorebooks"] + ids))
    if len(data["lorebooks"]) > 100:
        raise errors.ValidationError("A card may link at most 100 lorebooks.")
    avatar, skipped, created_images = related_images.attach(target, images, user)
    if avatar is not None:
        data["avatar"] = avatar
    if current is None:
        documents.create(
            target,
            "card",
            data,
            user,
            options.note if options.note is not None else "Created from data.",
        )
        outcome: Outcome = "created"
        snapshots.create(target, user)
    else:
        before = current.version
        documents.write(
            target,
            data,
            options.version if options.version is not None else before,
            user,
            options.note if options.note is not None else "Updated from data.",
        )
        outcome = "updated" if current.version != before else "unchanged"
    _add_ids(target, options, user)
    for tag in new_tags:
        snapshots.create(tag, user)
    return target, outcome, skipped, created_images


def create_lorebook(
    book: registry.Payload, spec: str, user: model.User, options: Options
) -> tuple[model.Post, Outcome]:
    _check_options(options, user)
    data = card_documents.validate_lorebook({"spec": "card_" + spec, "book": book})
    target = _resolve("lorebook", data, options)
    new_tags: list[model.Tag] = []
    if target is None:
        target, new_tags = _new_post("lorebook", user, options)
        documents.create(
            target,
            "lorebook",
            data,
            user,
            options.note if options.note is not None else "Created from data.",
        )
        outcome: Outcome = "created"
        snapshots.create(target, user)
    else:
        auth.verify_privilege(user, "posts:edit:document")
        current = _current_document(target)
        before = current.version
        documents.write(
            target,
            data,
            options.version if options.version is not None else before,
            user,
            options.note if options.note is not None else "Updated from data.",
        )
        outcome = "updated" if current.version != before else "unchanged"
    _add_ids(target, options, user)
    for tag in new_tags:
        snapshots.create(tag, user)
    return target, outcome
