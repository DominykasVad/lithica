"""A bounded pixel-decoding view of PNGs, without decoding their text."""

import struct
from collections.abc import Generator
from contextlib import contextmanager
from io import BytesIO
from typing import BinaryIO

from lithica import errors
from lithica.func.content import BLOCK_SIZE, Content, ContentLike

SIGNATURE = b"\x89PNG\r\n\x1a\n"
_TEXT = (b"tEXt", b"zTXt", b"iTXt")


def _copy(source: BinaryIO, target: BinaryIO, length: int) -> None:
    while length:
        block = source.read(min(length, BLOCK_SIZE))
        if not block:
            raise errors.ProcessingError("Truncated PNG chunk.")
        target.write(block)
        length -= len(block)


@contextmanager
def for_decoding(content: ContentLike) -> Generator[ContentLike]:
    """Keep the stored bytes; decode pixels from a private text-free view.

    Never inflate text or allocate a chunk-sized buffer. Every seek/copy stays
    inside the input's measured size, and the view cannot exceed that size.
    Non-PNG inputs retain their existing decoding path.
    """
    source = content.open() if isinstance(content, Content) else BytesIO(content)
    with source:
        size = source.seek(0, 2)
        source.seek(0)
        signature = source.read(8)
        if signature != SIGNATURE:
            yield content
            return
        view = Content.create_temporary(suffix=".png")
        try:
            with view.open_for_writing() as target:
                target.write(signature)
                position = 8
                while position + 12 <= size:
                    header = source.read(8)
                    if len(header) != 8:
                        raise errors.ProcessingError("Truncated PNG header.")
                    length, kind = struct.unpack(">I4s", header)
                    end = position + length + 12
                    if end > size:
                        raise errors.ProcessingError("Truncated PNG chunk.")
                    if kind in _TEXT:
                        source.seek(length + 4, 1)
                    else:
                        target.write(header)
                        _copy(source, target, length + 4)
                    position = end
                    if kind == b"IEND":
                        if length != 0:
                            raise errors.ProcessingError("Invalid PNG end chunk.")
                        _copy(source, target, size - position)
                        break
                else:
                    raise errors.ProcessingError("Missing PNG end chunk.")
            yield view
        finally:
            view.delete()
