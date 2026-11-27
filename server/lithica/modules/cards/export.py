"""Assemble character card exports (PNG, CHARX, JSON) from the current document."""

import base64
import json
import re
import tempfile
from collections.abc import Generator
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, BinaryIO, Literal, cast

import sqlalchemy as sa
from sqlalchemy.orm import lazyload

from lithica import db, errors, model
from lithica.func import documents, file_types, files, images, mime, posts
from lithica.func.content import Content
from lithica.modules.cards import (
    archived_links,
    assets,
    charx,
    export_data,
    image_links,
    png,
    reading,
    replacement,
)
from lithica.modules.cards import card as card_format
from lithica.modules.cards.model import CardImage

ExportFormat = Literal["png", "charx", "json"]
ExportSpec = Literal["v3+v2", "v3", "v2"]
ImageMode = Literal["links", "embedded"]

ALLOWED_SPECS: dict[ExportFormat, tuple[ExportSpec, ...]] = {
    "png": ("v3+v2", "v3", "v2"),
    "json": ("v3", "v2"),
    "charx": ("v3",),
}

DEFAULT_SPECS: dict[ExportFormat, ExportSpec] = {
    "png": "v3+v2",
    "json": "v3",
    "charx": "v3",
}

MEDIA_TYPES: dict[ExportFormat, str] = {
    "png": "image/png",
    "charx": charx.MIME_TYPE,
    "json": "application/json",
}

_REFERENCE = re.compile(r"lithica:post/([0-9]+)\Z")
_SAFE_SEGMENT = re.compile(r"[^a-z0-9_-]+")
_SPOOL_MAX_SIZE = 4 * 1024 * 1024


@dataclass
class ExportResult:
    file: tempfile.SpooledTemporaryFile[bytes]
    size: int
    media_type: str
    extension: str
    name: str
    skipped: int


@dataclass(frozen=True)
class _KeepAsset:
    entry: dict[str, Any]


@dataclass(frozen=True)
class _DefaultIcon:
    pass


@dataclass(frozen=True)
class _PostAsset:
    asset_type: str
    name: str
    post: model.Post
    is_main: bool = False


_PlannedAsset = _KeepAsset | _DefaultIcon | _PostAsset


def _ext_for(post: model.Post) -> str:
    return file_types.get_extension(post.mime_type or "") or "dat"


def _charx_kind(mime_type: str | None) -> str:
    if not mime_type:
        return "other"
    if mime.is_image(mime_type):
        return "images"
    if mime.is_video(mime_type):
        return "videos"
    return "other"


def _safe_type(asset_type: str) -> str:
    cleaned = _SAFE_SEGMENT.sub("_", asset_type.strip().lower()).strip("_")
    return cleaned or "other"


def _data_uri(post: model.Post, cache: dict[int, str]) -> str:
    cached = cache.get(post.post_id)
    if cached is not None:
        return cached
    stored = _stored_content(post)
    with stored.open() as handle:
        encoded = base64.b64encode(handle.read()).decode("ascii")
    uri = f"data:{post.mime_type or 'application/octet-stream'};base64,{encoded}"
    cache[post.post_id] = uri
    return uri


def _stored_content(post: model.Post) -> Content:
    stored = files.get(posts.get_post_content_path(post))
    if stored is None:
        raise errors.ValidationError(f"The file of post {post.post_id} is missing.")
    return stored


def _main_icon_index(raw_assets: list[object]) -> int | None:
    icons = [
        (idx, cast(dict[str, object], item))
        for idx, item in enumerate(raw_assets)
        if isinstance(item, dict)
        and cast(dict[str, object], item).get("type") == "icon"
    ]
    if not icons:
        return None
    return next((idx for idx, item in icons if item.get("name") == "main"), icons[0][0])


def _visible_card_images(card_id: int) -> dict[int, model.Post]:
    rows = db.session.execute(
        sa.select(CardImage.position, model.Post)
        .join(model.Post, model.Post.post_id == CardImage.post_id)
        .where(
            CardImage.card_post_id == card_id,
            model.Post.kind == "media",
            model.Post.mime_type.is_not(None),
        )
        .order_by(CardImage.position, CardImage.uri)
        .options(lazyload("*"))
    )
    found: dict[int, model.Post] = {}
    for position, media_post in rows:
        found.setdefault(position, media_post)
    return found


def _visible_related_assets(
    card_id: int,
) -> list[tuple[model.PostTypedRelation, model.Post]]:
    rows = db.session.execute(
        sa.select(model.PostTypedRelation, model.Post)
        .join(model.Post, model.Post.post_id == model.PostTypedRelation.from_post_id)
        .where(
            model.PostTypedRelation.to_post_id == card_id,
            model.PostTypedRelation.type.in_(("avatar-of", "expression-of")),
            model.Post.kind == "media",
            model.Post.mime_type.is_not(None),
        )
        .order_by(
            model.PostTypedRelation.type,
            model.PostTypedRelation.creation_time,
            model.PostTypedRelation.typed_relation_id,
        )
        .options(lazyload("*"))
    )
    return [(rel, media_post) for rel, media_post in rows]


@contextmanager
def _png_carrier(avatar: model.Post) -> Generator[BinaryIO]:
    stored = _stored_content(avatar)
    if avatar.mime_type == "image/png":
        with stored.open() as handle:
            if png.stripped(handle) is not None:
                handle.seek(0)
                yield handle
                return
    source: Content
    if mime.is_image(avatar.mime_type or ""):
        source = stored
    elif mime.is_video(avatar.mime_type or "") or mime.is_flash(avatar.mime_type or ""):
        thumb = files.get(posts.get_post_thumbnail_path(avatar))
        if thumb is None:
            raise errors.ValidationError(
                "The card's avatar has no thumbnail to export as a PNG."
            )
        source = thumb
    else:
        raise errors.ValidationError("The card's avatar cannot be encoded as a PNG.")
    with tempfile.SpooledTemporaryFile(max_size=_SPOOL_MAX_SIZE) as buffer:
        try:
            with images.pillow_image(source) as img:
                img.seek(0)
                img.save(buffer, format="PNG")
        except Exception as ex:
            raise errors.ValidationError(
                "The card's avatar could not be encoded as a PNG."
            ) from ex
        buffer.seek(0)
        yield cast(BinaryIO, buffer)


def _plan_assets(
    card_id: int,
    fields: dict[str, Any],
    fmt: ExportFormat,
    avatar: model.Post | None,
    archived_rows: dict[str, Any],
    visible_media: dict[int, model.Post],
) -> tuple[list[_PlannedAsset], int]:
    planned: list[_PlannedAsset] = []
    skipped = 0
    included_post_ids: set[int] = set()
    included_emotions: set[tuple[int, str]] = set()

    if avatar is not None:
        if fmt == "png":
            planned.append(_DefaultIcon())
        else:
            planned.append(_PostAsset("icon", "main", avatar, is_main=True))
        included_post_ids.add(avatar.post_id)

    raw_assets = fields.get("assets")
    if isinstance(raw_assets, list):
        items = cast(list[object], raw_assets)
        main_idx = _main_icon_index(items)
        by_pos = _visible_card_images(card_id)
        for idx, item in enumerate(items):
            if idx == main_idx or not isinstance(item, dict):
                continue
            entry = cast(dict[str, Any], item)
            uri = entry.get("uri")
            asset_type = (
                cast(str, entry["type"])
                if isinstance(entry.get("type"), str)
                else "x-lithica"
            )
            asset_name = (
                cast(str, entry["name"]) if isinstance(entry.get("name"), str) else ""
            )
            resolved: model.Post | None = None
            if idx in by_pos:
                resolved = by_pos[idx]
            elif isinstance(uri, str) and uri.strip().lower().startswith("https://"):
                clean_uri = uri.strip()
                row = archived_rows.get(clean_uri)
                if row is not None and row.status == "archived" and row.post_id:
                    resolved = visible_media.get(row.post_id)
                    if resolved is None:
                        skipped += 1
                        continue
                else:
                    planned.append(_KeepAsset(deepcopy(entry)))
                    continue
            elif isinstance(uri, str) and (match := _REFERENCE.fullmatch(uri.strip())):
                resolved = visible_media.get(int(match[1]))
                if resolved is None:
                    skipped += 1
                    continue
            else:
                skipped += 1
                continue

            planned.append(_PostAsset(asset_type, asset_name, resolved))
            included_post_ids.add(resolved.post_id)
            if asset_type == "emotion":
                included_emotions.add((resolved.post_id, asset_name))

    alt_index = 1
    for rel, media_post in _visible_related_assets(card_id):
        if rel.type == "avatar-of":
            if media_post.post_id not in included_post_ids:
                planned.append(_PostAsset("icon", f"alt-{alt_index}", media_post))
                alt_index += 1
                included_post_ids.add(media_post.post_id)
        elif rel.type == "expression-of":
            label = rel.label or ""
            if (media_post.post_id, label) not in included_emotions:
                planned.append(_PostAsset("emotion", label, media_post))
                included_emotions.add((media_post.post_id, label))
                included_post_ids.add(media_post.post_id)

    return planned, skipped


def export_card(
    post: model.Post,
    user: model.User,
    *,
    fmt: ExportFormat = "png",
    spec: ExportSpec | None = None,
    image_mode: ImageMode = "embedded",
    max_json_size: int,
) -> ExportResult:
    """Build an exported card file in a spooled temporary file."""
    chosen_spec = DEFAULT_SPECS[fmt] if spec is None else spec
    if chosen_spec not in ALLOWED_SPECS[fmt]:
        allowed = ", ".join(ALLOWED_SPECS[fmt])
        raise errors.ValidationError(
            f"Spec {chosen_spec!r} is not allowed for {fmt} exports "
            f"(allowed: {allowed})."
        )
    if image_mode == "links":
        raise errors.ValidationError("Share-link export is not supported yet.")

    if post.kind != "card":
        raise replacement.CardNotFoundError(
            "Post %d has no character card." % post.post_id
        )
    try:
        document = documents.get(post)
    except documents.DocumentNotFoundError:
        raise replacement.CardNotFoundError("The card hasn't been converted.") from None

    skipped = 0
    avatar_id = document.data.get("avatar")
    avatar: model.Post | None = None
    if isinstance(avatar_id, int):
        found = posts.try_get_post_by_id(avatar_id)
        if found is not None and found.kind == "media" and posts.has_file(found):
            avatar = found
        else:
            skipped += 1
    if fmt == "png" and avatar is None:
        raise errors.ValidationError("The card has no avatar to export as a PNG.")

    books = [book["book"] for _, book in reading.visible_books(post.post_id)]
    tracked_urls, ref_ids, _untracked = image_links.collect(document.data)
    tracked_set = set(tracked_urls)
    archived_rows = archived_links.current(post.post_id, tracked_urls)
    candidate_ids = [
        *ref_ids,
        *(row.post_id for row in archived_rows.values() if row.post_id is not None),
    ]
    visible_media = {
        pid: media_post
        for pid, media_post in archived_links.visible_posts(candidate_ids).items()
        if media_post.kind == "media" and posts.has_file(media_post)
    }

    work_doc = deepcopy(document.data)
    fields = card_format.fields_of(work_doc["spec"], work_doc["card"])
    wants_v3 = chosen_spec in ("v3", "v3+v2")
    wants_v2 = chosen_spec in ("v2", "v3+v2")

    planned_assets: list[_PlannedAsset] = []
    if wants_v3:
        planned_assets, asset_skipped = _plan_assets(
            post.post_id, fields, fmt, avatar, archived_rows, visible_media
        )
        skipped += asset_skipped

    data_uri_cache: dict[int, str] = {}

    def _resolve_text_link(link: image_links.Link) -> str | None:
        nonlocal skipped
        if link.reference is not None:
            target = visible_media.get(link.reference)
            if target is None:
                skipped += 1
                return None
            return _data_uri(target, data_uri_cache)
        if link.url not in tracked_set:
            return None
        row = archived_rows.get(link.url)
        if row is None or row.status != "archived" or row.post_id is None:
            return None
        target = visible_media.get(row.post_id)
        if target is None:
            skipped += 1
            return None
        return _data_uri(target, data_uri_cache)

    image_links.rewrite(work_doc, _resolve_text_link, include_assets=False)

    built_assets: list[dict[str, Any]] = []
    png_assets: list[tuple[str, Content]] = []
    charx_entries: list[tuple[str, Content]] = []
    charx_icon_path: str | None = None
    embedded_uris: dict[int, str] = {}
    next_asset_index = 0

    if wants_v3:
        for item in planned_assets:
            if isinstance(item, _KeepAsset):
                built_assets.append(item.entry)
            elif isinstance(item, _DefaultIcon):
                built_assets.append(
                    {
                        "type": "icon",
                        "uri": "ccdefault:",
                        "name": "main",
                        "ext": "png",
                    }
                )
            else:
                ext = _ext_for(item.post)
                if fmt == "json":
                    uri = _data_uri(item.post, data_uri_cache)
                elif fmt == "png":
                    uri = embedded_uris.get(item.post.post_id)
                    if uri is None:
                        path = f"{next_asset_index}.{ext}"
                        next_asset_index += 1
                        uri = f"__asset:{path}"
                        embedded_uris[item.post.post_id] = uri
                        png_assets.append((path, _stored_content(item.post)))
                else:
                    uri = embedded_uris.get(item.post.post_id)
                    if uri is None:
                        kind = _charx_kind(item.post.mime_type)
                        path = (
                            f"assets/{_safe_type(item.asset_type)}/"
                            f"{kind}/{next_asset_index}.{ext}"
                        )
                        next_asset_index += 1
                        uri = f"embeded://{path}"
                        embedded_uris[item.post.post_id] = uri
                        charx_entries.append((path, _stored_content(item.post)))
                        if item.is_main:
                            charx_icon_path = path
                    elif item.is_main and charx_icon_path is None:
                        charx_icon_path = uri.removeprefix("embeded://")
                built_assets.append(
                    {
                        "type": item.asset_type,
                        "uri": uri,
                        "name": item.name,
                        "ext": ext,
                    }
                )

    v3_card = export_data.build_v3(
        work_doc["spec"],
        work_doc["card"],
        creation_time=post.creation_time,
        modification_time=document.update_time,
        books=books,
        assets=built_assets if wants_v3 else [],
    )
    v2_card = export_data.to_v2(v3_card) if wants_v2 else None
    name = card_format.as_text(v3_card["data"].get("name"))

    spool = tempfile.SpooledTemporaryFile(max_size=_SPOOL_MAX_SIZE)
    try:
        if fmt == "json":
            payload = v3_card if wants_v3 else v2_card
            assert payload is not None
            encoded = json.dumps(
                payload, ensure_ascii=False, separators=(",", ":")
            ).encode("utf-8")
            if len(encoded) > max_json_size:
                limit_mib = max_json_size // (1024 * 1024)
                raise errors.ValidationError(
                    f"The exported JSON exceeds the {limit_mib} MiB limit. "
                    "Export with share links instead."
                )
            spool.write(encoded)
        elif fmt == "charx":
            try:
                charx.write(
                    cast(BinaryIO, spool),
                    v3_card,
                    charx_entries,
                    icon_path=charx_icon_path,
                )
            except charx.Rejected as ex:
                raise errors.ValidationError(str(ex)) from ex
        else:
            assert avatar is not None
            try:
                with _png_carrier(avatar) as carrier:
                    png.write(
                        carrier,
                        cast(BinaryIO, spool),
                        v3=v3_card if wants_v3 else None,
                        v2=v2_card if wants_v2 else None,
                        assets=png_assets,
                        max_assets=assets.MAX_IMAGES,
                        max_asset_size=assets.MAX_IMAGE_SIZE,
                    )
            except png.Oversized as ex:
                raise errors.ValidationError(str(ex)) from ex
        size = spool.tell()
        spool.seek(0)
        return ExportResult(
            file=spool,
            size=size,
            media_type=MEDIA_TYPES[fmt],
            extension=fmt,
            name=name,
            skipped=skipped,
        )
    except Exception:
        spool.close()
        raise
