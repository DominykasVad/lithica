"""Versioned JSON documents: modules validate meaning, the engine keeps history."""

import hashlib
import json
import zlib
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import joinedload

from lithica import db, errors, model, registry
from lithica.func import site_settings, users, util, versions


class DocumentNotFoundError(errors.NotFoundError):
    pass


def _kind(name: str) -> registry.DocumentKind:
    kind = registry.document_kinds().get(name)
    if kind is None:
        raise DocumentNotFoundError("Document not found.")
    return kind


def get(post: model.Post, *, lock: bool = False) -> model.PostDocument:
    query = sa.select(model.PostDocument).where(
        model.PostDocument.post_id == post.post_id
    )
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    document = db.session.execute(query).scalar_one_or_none()
    if document is None:
        raise DocumentNotFoundError("Document not found.")
    _kind(document.kind)
    return document


def _json(data: object, kind: registry.DocumentKind) -> bytes:
    if not isinstance(data, dict):
        raise errors.ValidationError("A document must be a JSON object.")
    try:
        encoded = json.dumps(
            data,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError) as error:
        raise errors.ValidationError("Invalid JSON document.") from error
    if len(encoded) > kind.max_size:
        raise errors.ValidationError("Document exceeds its size limit.")

    # Check the strings themselves, including keys, not their JSON escaping.
    def check(value: object) -> None:
        if isinstance(value, str):
            if "\x00" in value or any(0xD800 <= ord(c) <= 0xDFFF for c in value):
                raise errors.ValidationError(
                    "Documents cannot contain NUL or lone surrogates."
                )
        elif isinstance(value, dict):
            for key, item in value.items():
                check(key)
                check(item)
        elif isinstance(value, list):
            for item in value:
                check(item)

    try:
        check(data)
    except RecursionError as error:
        raise errors.ValidationError("Invalid JSON document.") from error
    return encoded


def _validated(data: object, kind: registry.DocumentKind) -> bytes:
    encoded = _json(data, kind)
    try:
        result = kind.validate(json.loads(encoded))
    except registry.DocumentRejected as error:
        raise errors.ValidationError(str(error)) from error
    return _json(result, kind)


def _store(
    document: model.PostDocument,
    encoded: bytes,
    user: model.User | None,
    note: str | None,
) -> None:
    if note is not None and len(note) > 256:
        raise errors.ValidationError("A document note may have at most 256 characters.")
    kind = _kind(document.kind)
    document.schema_version = kind.schema_version
    document.hash = hashlib.sha256(encoded).hexdigest()
    document.size = len(encoded)
    document.data = json.loads(encoded)
    document.update_time = util.utcnow()
    db.session.add(
        model.PostDocumentVersion(
            post_id=document.post_id,
            number=document.version,
            schema_version=document.schema_version,
            hash=document.hash,
            size=document.size,
            data=zlib.compress(encoded),
            creation_time=document.update_time,
            user=user,
            note=note,
        )
    )
    db.session.flush()
    if kind.after_write:
        kind.after_write(document.post_id, json.loads(encoded))
        db.session.flush()
    _prune(document)


def _prune(document: model.PostDocument) -> None:
    kept = site_settings.get("document_versions_kept")
    if kept:
        db.session.execute(
            sa.delete(model.PostDocumentVersion).where(
                model.PostDocumentVersion.post_id == document.post_id,
                model.PostDocumentVersion.number > 0,
                model.PostDocumentVersion.number <= document.version - kept,
            )
        )


def create(
    post: model.Post,
    kind: str,
    data: object,
    user: model.User | None,
    note: str | None = None,
) -> model.PostDocument:
    registered = _kind(kind)
    if post.kind != kind:
        raise errors.ValidationError("The document kind must match the post kind.")
    encoded = _validated(data, registered)
    db.session.flush()
    # Serialize creation for the same post; the primary key is the final guard.
    db.session.execute(
        sa.select(model.Post.post_id)
        .where(model.Post.post_id == post.post_id)
        .with_for_update()
    )
    if db.session.get(model.PostDocument, post.post_id) is not None:
        raise errors.ValidationError("This post already has a document.")
    document = model.PostDocument(post_id=post.post_id, kind=kind, version=0)
    db.session.add(document)
    _store(document, encoded, user, note)
    return document


def write(
    post: model.Post,
    data: object,
    based_on: int,
    user: model.User | None,
    note: str | None = None,
) -> model.PostDocument:
    document = get(post, lock=True)
    versions.verify_version(document, based_on)
    encoded = _validated(data, _kind(document.kind))
    if hashlib.sha256(encoded).hexdigest() == document.hash:
        _prune(document)
        return document
    document.version += 1
    _store(document, encoded, user, note)
    return document


def get_version(post: model.Post, number: int) -> model.PostDocumentVersion:
    get(post)
    version = db.session.execute(
        sa.select(model.PostDocumentVersion).where(
            model.PostDocumentVersion.post_id == post.post_id,
            model.PostDocumentVersion.number == number,
        )
    ).scalar_one_or_none()
    if version is None:
        raise DocumentNotFoundError("Document version not found.")
    return version


def restore(
    post: model.Post, number: int, based_on: int, user: model.User | None
) -> model.PostDocument:
    document = get(post, lock=True)
    versions.verify_version(document, based_on)
    version = get_version(post, number)
    return write(
        post,
        json.loads(zlib.decompress(version.data)),
        based_on,
        user,
        f"Restored from version {number}.",
    )


def serialize(document: model.PostDocument) -> dict[str, Any]:
    # Any: heterogeneous API resource, described by resources.PostDocument.
    return dict(
        kind=document.kind,
        version=document.version,
        schemaVersion=document.schema_version,
        hash=document.hash,
        size=document.size,
        updateTime=document.update_time,
        data=document.data,
    )


def serialize_version(
    version: model.PostDocumentVersion, viewer: model.User, *, data: bool = False
) -> dict[str, Any]:
    # Any: heterogeneous API resource, with optional JSON data.
    result = dict(
        number=version.number,
        schemaVersion=version.schema_version,
        hash=version.hash,
        size=version.size,
        creationTime=version.creation_time,
        user=users.serialize_micro_user(version.user, viewer),
        note=version.note,
    )
    if data:
        result["data"] = json.loads(zlib.decompress(version.data))
    return result


def list_versions(
    post: model.Post, offset: int, limit: int, viewer: model.User
) -> dict[str, Any]:
    # Any: paged API response, described by resources.Paged.
    get(post)
    if offset < 0 or not 1 <= limit <= 100:
        raise errors.ValidationError("Invalid document version paging.")
    query = db.session.query(model.PostDocumentVersion).filter_by(post_id=post.post_id)
    total = query.count()
    rows = (
        query.options(joinedload(model.PostDocumentVersion.user))
        .order_by(model.PostDocumentVersion.number.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return dict(
        query="",
        offset=offset,
        limit=limit,
        total=total,
        results=[serialize_version(row, viewer) for row in rows],
    )
