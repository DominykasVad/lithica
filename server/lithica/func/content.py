"""
Content of files: an upload, a download, a stored post.

A video can be far larger than the memory a server process should use, so
content that came over the network or from the data directory is not read
into a `bytes` object. It stays in a file and is passed around as a
`Content`, which knows where the file is and can hash it, show its first
bytes or copy it, a block at a time.

Small content the server produced itself (a thumbnail, a converted image)
is still plain `bytes`. The functions of this module take either, so the
rest of the code does not have to care which one it holds.
"""

import contextlib
import hashlib
import os
import shutil
import tempfile
import weakref
from collections.abc import Iterator
from typing import BinaryIO

# how much of a file is in memory at a time
BLOCK_SIZE = 1024 * 1024


def _remove(path: str) -> None:
    with contextlib.suppress(FileNotFoundError):
        os.remove(path)


class Content:
    """
    Content that lives in a file.

    A *temporary* content owns its file: `delete()` removes it, and so does
    the garbage collector if nobody called `delete()`. Other content only
    points at a file that belongs to someone else (the data directory).

    It compares equal to the `bytes` it holds and is false when empty, which
    is what code written for `bytes` asks of it most often.
    """

    def __init__(self, path: str, temporary: bool = False) -> None:
        self.path = path
        self._finalizer = weakref.finalize(self, _remove, path) if temporary else None

    @classmethod
    def create_temporary(cls, suffix: str = "") -> "Content":
        """A new, empty temporary content; fill it through `open_for_writing()`."""
        descriptor, path = tempfile.mkstemp(prefix="lithica-", suffix=suffix)
        os.close(descriptor)
        return cls(path, temporary=True)

    def delete(self) -> None:
        """Remove the file, if this content owns it."""
        if self._finalizer is not None:
            self._finalizer()

    @property
    def size(self) -> int:
        return os.path.getsize(self.path)

    def open(self) -> BinaryIO:
        return open(self.path, "rb")  # noqa: SIM115  (the caller closes it)

    def open_for_writing(self) -> BinaryIO:
        return open(self.path, "wb")  # noqa: SIM115  (the caller closes it)

    def blocks(self) -> Iterator[bytes]:
        with self.open() as handle:
            while block := handle.read(BLOCK_SIZE):
                yield block

    def head(self, length: int) -> bytes:
        with self.open() as handle:
            return handle.read(length)

    def read(self) -> bytes:
        """The whole content in memory. Only for content known to be small."""
        with self.open() as handle:
            return handle.read()

    def __len__(self) -> int:
        return self.size

    def __bool__(self) -> bool:
        return self.size > 0

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Content):
            return self.path == other.path or self.read() == other.read()
        if isinstance(other, bytes):
            return self.size == len(other) and self.read() == other
        return NotImplemented

    def __repr__(self) -> str:
        return "Content(%r)" % self.path


ContentLike = bytes | Content


def size(content: ContentLike) -> int:
    return len(content)


def head(content: ContentLike, length: int) -> bytes:
    if isinstance(content, Content):
        return content.head(length)
    return content[:length]


def blocks(content: ContentLike) -> Iterator[bytes]:
    if isinstance(content, Content):
        yield from content.blocks()
    else:
        yield content


def read(content: ContentLike) -> bytes:
    """The whole content in memory. Only for content known to be small."""
    if isinstance(content, Content):
        return content.read()
    return content


def _digest(content: ContentLike, algorithm: str) -> str:
    digest = hashlib.new(algorithm)
    for block in blocks(content):
        digest.update(block)
    return digest.hexdigest()


def sha1(content: ContentLike) -> str:
    return _digest(content, "sha1")


def md5(content: ContentLike) -> str:
    return _digest(content, "md5")


def save(content: ContentLike, path: str) -> None:
    """Write the content to `path`, replacing what is there."""
    if isinstance(content, Content):
        if os.path.abspath(content.path) != os.path.abspath(path):
            shutil.copyfile(content.path, path)
    else:
        with open(path, "wb") as handle:
            handle.write(content)


def temporary_copy(content: ContentLike, suffix: str = "") -> Content:
    """A temporary content with the same bytes, safe from changes to the original."""
    copy = Content.create_temporary(suffix=suffix)
    save(content, copy.path)
    return copy


@contextlib.contextmanager
def as_file(content: ContentLike, suffix: str = "") -> Iterator[str]:
    """
    A path, ending in `suffix`, at which the content can be read for the
    duration of the block. For the programs that are given a file name
    (ffmpeg, ffprobe) and look at its extension.
    """
    descriptor, path = tempfile.mkstemp(prefix="lithica-", suffix=suffix)
    os.close(descriptor)
    try:
        if isinstance(content, Content):
            os.remove(path)
            try:
                # a second name for the same file: no copy
                os.link(content.path, path)
            except OSError:
                # across file systems, or where links are not supported
                shutil.copyfile(content.path, path)
        else:
            with open(path, "wb") as handle:
                handle.write(content)
        yield path
    finally:
        _remove(path)
