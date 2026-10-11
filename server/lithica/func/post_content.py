"""
The embedded-content pipeline: what modules read out of uploaded files.

Many files carry more than a picture: PNG text chunks, EXIF, the metadata of
a video. The engine does not know what any of it means. Modules do: they
register extractors (see lithica.registry), the engine runs them over a
post's file and stores what they return in `post_content`, one row per
result.

Everything here deals with untrusted data. The file is somebody's upload
and the payloads are whatever was written into it, so a payload is only
ever stored and returned as JSON: never executed, never rendered, never
logged. An extractor is code of a module and may be wrong about a hostile
file, so one that raises, or returns something that is not what the
contract says, is logged and skipped. It never fails the upload.
"""

import io
import json
import logging
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, BinaryIO, cast

from lithica import model, registry
from lithica.func import content as content_module
from lithica.func import tags, util
from lithica.func.content import ContentLike

logger = logging.getLogger(__name__)

# What one extractor may return for one file. Embedded data is as large as
# the uploader made it; this is what the database is asked to keep of it.
MAX_RESULTS = 64
MAX_PAYLOAD_SIZE = 1024 * 1024

# how many tags one module may put on one post
MAX_AUTO_TAGS = 100


class _InvalidResultError(Exception):
    """An extractor returned something the contract does not allow."""


@dataclass
class Extraction:
    """
    What the extractors made of one file.

    `failed_kinds` are the kinds of the modules that had an extractor fail:
    for those the file was not read properly, which is not the same as the
    file holding nothing.
    """

    contents: list[registry.ExtractedContent] = field(
        default_factory=list[registry.ExtractedContent]
    )
    failed_kinds: set[str] = field(default_factory=set[str])


def _open(content: ContentLike) -> BinaryIO:
    if isinstance(content, content_module.Content):
        return content.open()
    return io.BytesIO(content)


def _verified(
    result: object, module: registry.Module, owned_kinds: Collection[str]
) -> registry.ExtractedContent:
    if not isinstance(result, registry.ExtractedContent):
        raise _InvalidResultError("returned %s" % type(result).__name__)
    if result.kind not in owned_kinds:
        raise _InvalidResultError(
            "returned content of kind %r, which module %r does not declare"
            % (result.kind, module.name)
        )
    payload: object = result.payload
    if not isinstance(payload, dict):
        raise _InvalidResultError("returned a payload that is not an object")
    try:
        # What the database driver will do, done here so that a payload
        # that cannot be stored costs one result and not the whole upload.
        # Encoding to UTF-8 refuses lone surrogates, which a database
        # refuses too.
        encoded = json.dumps(payload, allow_nan=False, ensure_ascii=False)
        size = len(encoded.encode("utf-8"))
    except (TypeError, ValueError, RecursionError) as ex:
        raise _InvalidResultError("returned a payload that is not JSON") from ex
    if size > MAX_PAYLOAD_SIZE:
        raise _InvalidResultError(
            "returned a payload of %d bytes (the limit is %d)"
            % (size, MAX_PAYLOAD_SIZE)
        )
    # the payload as JSON has it: a copy nobody else holds, keys as strings
    stored: registry.Payload = json.loads(encoded)
    if _has_nul(stored):
        # PostgreSQL's JSONB cannot hold the character
        raise _InvalidResultError("returned a payload with a NUL character")
    return registry.ExtractedContent(kind=result.kind, payload=stored)


def _has_nul(value: object) -> bool:
    if isinstance(value, str):
        return "\x00" in value
    if isinstance(value, dict):
        items = cast(dict[str, object], value)
        return any(_has_nul(key) or _has_nul(item) for key, item in items.items())
    if isinstance(value, list):
        return any(_has_nul(item) for item in cast(list[object], value))
    return False


def _run(
    module: registry.Module,
    extractor: registry.Extractor,
    mime_type: str,
    content: ContentLike,
) -> list[registry.ExtractedContent]:
    owned_kinds = {kind.name for kind in module.content_kinds}
    results: list[registry.ExtractedContent] = []
    # every extractor gets the file from its start
    with _open(content) as handle:
        for result in extractor.extract(mime_type, handle):
            if len(results) >= MAX_RESULTS:
                raise _InvalidResultError("returned more than %d results" % MAX_RESULTS)
            results.append(_verified(result, module, owned_kinds))
    return results


def extract(
    mime_type: str, content: ContentLike, kinds: Collection[str] | None = None
) -> Extraction:
    """
    Run the extractors registered for the MIME type over the content. With
    `kinds`, only the modules that own one of them are asked, and only
    results of those kinds are kept.

    Never raises for anything an extractor does: what one extractor found
    is kept when another fails, and all results of a failing one are
    dropped, as nobody knows which of them to trust.
    """
    extraction = Extraction()
    for module, extractor in registry.extractors_for(mime_type):
        owned_kinds = {kind.name for kind in module.content_kinds}
        if kinds is not None and not owned_kinds & set(kinds):
            continue
        try:
            results = _run(module, extractor, mime_type, content)
        except _InvalidResultError as ex:
            # only our own description of the problem: no payload
            logger.error("An extractor of module %r %s.", module.name, ex)
            extraction.failed_kinds |= owned_kinds
        except Exception:
            logger.exception(
                "An extractor of module %r failed on a %s file.",
                module.name,
                mime_type,
            )
            extraction.failed_kinds |= owned_kinds
        else:
            extraction.contents += [
                result for result in results if kinds is None or result.kind in kinds
            ]
    if kinds is not None:
        extraction.failed_kinds &= set(kinds)
    return extraction


def _rows(contents: Sequence[registry.ExtractedContent]) -> list[model.PostContent]:
    kinds = registry.content_kinds()
    now = util.utcnow()
    return [
        model.PostContent(
            kind=content.kind,
            schema_version=kinds[content.kind].schema_version,
            payload=content.payload,
            extracted_at=now,
        )
        for content in contents
    ]


def update_post_contents(post: model.Post, content: ContentLike) -> None:
    """
    Make the post's extracted content that of this file: its new content.
    Every row the post had goes, also those of modules that are switched
    off now, because they describe a file the post no longer has.
    """
    post.contents = _rows(extract(post.mime_type, content).contents)


def _verified_auto_tags(result: object) -> dict[str, list[str]]:
    if not isinstance(result, Mapping):
        raise _InvalidResultError("returned %s" % type(result).__name__)
    auto_tags: dict[str, list[str]] = {}
    count = 0
    for category, names in cast(Mapping[object, object], result).items():
        if not isinstance(category, str):
            raise _InvalidResultError("returned a category that is not a string")
        if isinstance(names, str) or not isinstance(names, Sequence):
            raise _InvalidResultError("returned tags that are not a list")
        for name in cast(Sequence[object], names):
            if not isinstance(name, str):
                raise _InvalidResultError("returned a tag that is not a string")
            count += 1
            if count > MAX_AUTO_TAGS:
                raise _InvalidResultError("returned more than %d tags" % MAX_AUTO_TAGS)
            # A name the site does not accept is left out and the rest is
            # kept: names come from the file, and a module cannot know the
            # site's rule for them.
            if tags.is_valid_name(name):
                auto_tags.setdefault(category, []).append(name)
    return auto_tags


def get_auto_tags(post: model.Post) -> list[tuple[str, str]]:
    """
    The tags the modules want on the post for what was extracted from its
    file, as (category name, tag name), each name once. A module is shown
    the content of its own kinds only, and is not asked when there is none.
    Like extract(), this never raises for what a module does.
    """
    auto_tags: list[tuple[str, str]] = []
    seen: set[str] = set()
    for module, auto_tag in registry.auto_taggers():
        owned_kinds = {kind.name for kind in module.content_kinds}
        contents = [
            registry.ExtractedContent(row.kind, row.payload)
            for row in post.contents
            if row.kind in owned_kinds
        ]
        if not contents:
            continue
        try:
            wanted = _verified_auto_tags(auto_tag(contents))
        except _InvalidResultError as ex:
            logger.error("The auto-tag hook of module %r %s.", module.name, ex)
            continue
        except Exception:
            logger.exception("The auto-tag hook of module %r failed.", module.name)
            continue
        for category, names in wanted.items():
            for name in names:
                if name.lower() not in seen:
                    seen.add(name.lower())
                    auto_tags.append((category, name))
    return auto_tags


def reextract_post_contents(
    post: model.Post, content: ContentLike, kinds: Collection[str] | None = None
) -> bool:
    """
    Run the extractors over the file the post already has and replace the
    rows of the kinds the loaded modules own (or of `kinds` only) with what
    they find now. Rows of other kinds are left alone: they belong to
    modules that are switched off, and whoever switches one back on will
    want them.

    Where an extractor fails, the rows of its module's kinds are kept as
    they are, since old content is better than none. Returns whether every
    extractor worked.
    """
    targets = set(registry.content_kinds() if kinds is None else kinds)
    extraction = extract(post.mime_type, content, kinds)
    replaced = targets - extraction.failed_kinds
    kept = [row for row in post.contents if row.kind not in replaced]
    found = [content for content in extraction.contents if content.kind in replaced]
    post.contents = kept + _rows(found)
    return not extraction.failed_kinds


def get_extracted_mime_types(kinds: Collection[str] | None = None) -> set[str]:
    """The MIME types the extractors behind these kinds (or all) read."""
    mime_types: set[str] = set()
    for module in registry.modules():
        owned_kinds = {kind.name for kind in module.content_kinds}
        if kinds is None or owned_kinds & set(kinds):
            for extractor in module.extractors:
                mime_types |= extractor.mime_types
    return mime_types


def get_content_kinds(post: model.Post) -> list[str]:
    """
    The kinds of extracted content the post has, for the post resource.
    Only kinds a loaded module owns are named: what a switched-off module
    left behind is nobody's to show.
    """
    owned_kinds = registry.content_kinds()
    if not owned_kinds:
        # no module, no content: do not ask the database for every post
        return []
    return sorted({row.kind for row in post.contents if row.kind in owned_kinds})


def serialize_post_contents(
    post: model.Post, show_private: bool
) -> list[dict[str, Any]]:
    """
    The extracted content of the post as the API returns it: one entry per
    row of a kind a loaded module owns, in the order the rows were stored.
    The module that owns the kind decides what `content` looks like (see
    lithica.registry.ContentKind); without its say it is the stored payload.

    Unless `show_private`, the fields the module marked as private are
    taken out of the payload first, before the module's own code sees it:
    what a module's `serialize` is not given, it cannot leak.
    """
    owned_kinds = registry.content_kinds()
    if not owned_kinds:
        return []
    serialized: list[dict[str, Any]] = []
    for row in post.contents:
        kind = owned_kinds.get(row.kind)
        if kind is None:
            continue
        payload = dict(cast(registry.Payload, row.payload))
        if not show_private:
            for name in kind.private_fields:
                payload.pop(name, None)
        try:
            shown = kind.serialize(payload) if kind.serialize else payload
        except Exception:
            # a module that cannot show a row must not take the others,
            # or the request, down with it
            logger.exception(
                "The module that owns the content kind %r could not serialize "
                "a row of post %d.",
                row.kind,
                post.post_id,
            )
            continue
        serialized.append(
            {
                "kind": row.kind,
                "schemaVersion": row.schema_version,
                "extractedAt": row.extracted_at,
                "content": shown,
            }
        )
    return serialized
