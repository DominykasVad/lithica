"""
File types of modules: files the engine does not know, which a module
does (see lithica.registry.FileType).

The engine looks at a file first. Only one it would refuse as
`application/octet-stream` is shown to the modules' detectors, so a module
can never take a picture or a video away from the engine. A file no
detector accepts is refused as before.

Everything here deals with somebody's upload. A detector or a thumbnail
hook is code of a module and may be wrong about a hostile file: one that
fails is logged and counts as "no", or as "no thumbnail". The one thing a
detector may do to an upload is refuse it on purpose, with a reason for
the uploader (registry.FileRejected).
"""

import io
import logging
from typing import BinaryIO, cast

from lithica import errors, registry
from lithica.func import content as content_module
from lithica.func import mime
from lithica.func.content import ContentLike

logger = logging.getLogger(__name__)

# how much of the start of a file a detector is handed along with the file
HEAD_LENGTH = 512

# The largest picture a thumbnail hook may return. It is held in memory, and
# it comes out of an uploaded file.
MAX_THUMBNAIL_SIZE = 32 * 1024 * 1024


class FileRejectedError(errors.ValidationError):
    """A module knows the file as one of its own and refuses it."""


def _open(content: ContentLike) -> BinaryIO:
    if isinstance(content, content_module.Content):
        return content.open()
    return io.BytesIO(content)


def detect(content: ContentLike) -> registry.FileType | None:
    """
    The file type of the first module whose detector accepts the content, in
    the order of the configuration, or None. Call it only for content the
    engine does not know.

    Raises FileRejectedError when a detector refuses the file; the message
    is the module's, for the uploader.
    """
    file_types = registry.file_types()
    if not file_types:
        return None
    head = content_module.head(content, HEAD_LENGTH)
    for module, file_type in file_types:
        try:
            # every detector gets the file from its start
            with _open(content) as handle:
                accepted = file_type.detect(head, handle)
        except registry.FileRejected as ex:
            raise FileRejectedError(str(ex)) from ex
        except Exception:
            logger.exception(
                "The detector of module %r for %r files failed.",
                module.name,
                file_type.post_type,
            )
            continue
        if accepted is True:
            return file_type
    return None


def get_mime_type(content: ContentLike) -> str:
    """
    The MIME type of the content: what the engine says, and for a file it
    does not know, what a module says. `application/octet-stream` when
    nobody knows it.
    """
    mime_type = mime.get_mime_type(content)
    if mime_type != "application/octet-stream":
        return mime_type
    file_type = detect(content)
    return file_type.mime_type if file_type else mime_type


def get_extension(mime_type: str) -> str | None:
    """The extension files of this MIME type are stored with, if anyone knows."""
    extension = mime.get_extension(mime_type)
    if extension is not None:
        return extension
    file_type = registry.file_type_for(mime_type)
    return file_type.extension if file_type else None


def get_thumbnail(file_type: registry.FileType, content: ContentLike) -> bytes | None:
    """
    The picture the module offers as the thumbnail of this file, or None
    when there is none: no hook, the hook found nothing, the hook failed, or
    what it returned is not a picture the engine reads. Never raises.
    """
    if file_type.thumbnail is None:
        return None
    try:
        with _open(content) as handle:
            # declared as bytes; a module may have returned anything
            picture = cast(object, file_type.thumbnail(handle))
    except Exception:
        logger.exception("The thumbnail hook for %r files failed.", file_type.post_type)
        return None
    if picture is None:
        return None
    if not isinstance(picture, bytes):
        logger.error(
            "The thumbnail hook for %r files returned %s.",
            file_type.post_type,
            type(picture).__name__,
        )
        return None
    if len(picture) > MAX_THUMBNAIL_SIZE:
        logger.error(
            "The thumbnail hook for %r files returned %d bytes (the limit is %d).",
            file_type.post_type,
            len(picture),
            MAX_THUMBNAIL_SIZE,
        )
        return None
    if not mime.is_image(mime.get_mime_type(picture)):
        # also what keeps a video, or anything else, away from the decoder
        return None
    return picture
