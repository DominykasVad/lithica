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

Temporary files live in a folder of the data directory, not in the system's
temporary directory: in a container that one is the image's writable layer,
which is no place for gigabytes, and a file that is already on the data
volume becomes stored content by being renamed instead of copied.
"""

import contextlib
import hashlib
import logging
import os
import shutil
import tempfile
import time
import weakref
from collections.abc import Iterator
from typing import BinaryIO

from lithica import config

logger = logging.getLogger(__name__)

# how much of a file is in memory at a time
BLOCK_SIZE = 1024 * 1024

# where temporary files are kept, inside the data directory
TEMPORARY_DIR = os.path.join("temporary-uploads", ".tmp")

# a temporary file this old belongs to a process that is gone
STALE_AFTER = 60 * 60

# The permissions a file gets when it is created the ordinary way. Temporary
# files are created private; one that becomes stored content must end up
# readable like every other stored file (the web server reads them as
# another user). Asked once, here: asking means changing the mask for a
# moment, which is only safe while nothing else runs.
_umask = os.umask(0)
os.umask(_umask)
STORED_FILE_MODE = 0o666 & ~_umask


def temporary_dir() -> str:
    """
    The folder for temporary files, created if it is missing. Without a
    configured data directory (some tests, a bare script) it is the
    system's temporary directory.
    """
    data_dir = config.config.get("data_dir")
    if not data_dir:
        return tempfile.gettempdir()
    path = os.path.join(data_dir, TEMPORARY_DIR)
    os.makedirs(path, exist_ok=True)
    return path


def _newest_change(path: str) -> float:
    """When the file, or anything in the directory, was last written."""
    newest = os.lstat(path).st_mtime
    if os.path.isdir(path) and not os.path.islink(path):
        for entry in os.scandir(path):
            newest = max(newest, entry.stat(follow_symlinks=False).st_mtime)
    return newest


def remove_stale_temporary_files() -> int:
    """
    Remove what crashed or killed processes left in the temporary folder:
    everything not written to for STALE_AFTER seconds. Returns how many
    entries this call removed, for the log.

    Every server process runs this when it starts, possibly at the same
    moment as another, while yet others are serving uploads. It only
    touches entries that have been idle for an hour, which no live request
    has, and an entry another process removed first is simply gone.
    """
    data_dir = config.config.get("data_dir")
    if not data_dir:
        # never sweep the system's temporary directory
        return 0
    folder = temporary_dir()
    removed = 0
    now = time.time()
    for name in os.listdir(folder):
        path = os.path.join(folder, name)
        try:
            if now - _newest_change(path) < STALE_AFTER:
                continue
            if os.path.isdir(path) and not os.path.islink(path):
                shutil.rmtree(path)
            else:
                os.remove(path)
            removed += 1
        except FileNotFoundError:
            # another process got to it first
            continue
        except OSError as ex:
            logger.warning("Could not remove stale temporary file %s: %s", path, ex)
    if removed:
        logger.info("Removed %d stale temporary file(s) from %s", removed, folder)
    return removed


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

    def __init__(
        self, path: str, temporary: bool = False, movable: bool = False
    ) -> None:
        self.path = path
        # whether save() may take the file away instead of copying it:
        # true for a file that exists only to be stored (an upload, a
        # download), false for one that must stay where it is
        self.movable = movable or temporary
        self._finalizer = weakref.finalize(self, _remove, path) if temporary else None

    @classmethod
    def create_temporary(cls, suffix: str = "") -> "Content":
        """A new, empty temporary content; fill it through `open_for_writing()`."""
        descriptor, path = tempfile.mkstemp(
            prefix="content-", suffix=suffix, dir=temporary_dir()
        )
        os.close(descriptor)
        return cls(path, temporary=True)

    def delete(self) -> None:
        """Remove the file, if this content owns it."""
        if self._finalizer is not None:
            self._finalizer()

    def _moved_to(self, path: str) -> None:
        """The file was renamed: it is stored content now, owned by nobody."""
        if self._finalizer is not None:
            self._finalizer.detach()
            self._finalizer = None
        self.path = path
        self.movable = False

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
    """
    Write the content to `path`, replacing what is there.

    A movable content (see Content) is renamed into place when it is on the
    same file system, which costs nothing however large it is; it then
    points at the new place. Otherwise the content is copied.
    """
    if not isinstance(content, Content):
        with open(path, "wb") as handle:
            handle.write(content)
        return
    if os.path.abspath(content.path) == os.path.abspath(path):
        return
    if content.movable:
        try:
            os.replace(content.path, path)
        except OSError:
            # another file system (or no permission to rename): copy
            pass
        else:
            os.chmod(path, STORED_FILE_MODE)
            content._moved_to(path)
            return
    shutil.copyfile(content.path, path)


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
    descriptor, path = tempfile.mkstemp(
        prefix="named-", suffix=suffix, dir=temporary_dir()
    )
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
