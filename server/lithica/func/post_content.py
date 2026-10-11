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
from collections.abc import Collection
from dataclasses import dataclass, field
from typing import BinaryIO, cast

from lithica import registry
from lithica.func import content as content_module
from lithica.func.content import ContentLike

logger = logging.getLogger(__name__)

# What one extractor may return for one file. Embedded data is as large as
# the uploader made it; this is what the database is asked to keep of it.
MAX_RESULTS = 64
MAX_PAYLOAD_SIZE = 1024 * 1024


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
