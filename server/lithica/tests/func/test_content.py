import gc
import hashlib
import os

import pytest

from lithica.func import content as content_module
from lithica.func.content import Content


def _temporary(data: bytes) -> Content:
    content = Content.create_temporary()
    with content.open_for_writing() as handle:
        handle.write(data)
    return content


@pytest.fixture(params=["bytes", "file"])
def make(request):
    """Build content either way; every function must treat both the same."""
    created = []

    def factory(data: bytes):
        if request.param == "bytes":
            return data
        content = _temporary(data)
        created.append(content)
        return content

    yield factory
    for content in created:
        content.delete()


DATA = bytes(range(256)) * 5000  # 1.28 MB: more than one block


def test_size_head_read(make):
    content = make(DATA)
    assert content_module.size(content) == len(DATA)
    assert content_module.head(content, 4) == DATA[:4]
    assert content_module.head(content, 10**9) == DATA
    assert content_module.read(content) == DATA
    assert b"".join(content_module.blocks(content)) == DATA


def test_hashes(make):
    content = make(DATA)
    assert content_module.sha1(content) == hashlib.sha1(DATA).hexdigest()
    assert content_module.md5(content) == hashlib.md5(DATA).hexdigest()


def test_empty(make):
    content = make(b"")
    assert not content
    assert content_module.size(content) == 0
    assert content_module.head(content, 4) == b""
    assert content_module.sha1(content) == hashlib.sha1(b"").hexdigest()


def test_save(make, tmpdir):
    target = str(tmpdir.join("saved.dat"))
    with open(target, "wb") as handle:
        handle.write(b"something older and longer" * 100000)
    content_module.save(make(DATA), target)
    with open(target, "rb") as handle:
        assert handle.read() == DATA


def test_saving_content_over_itself_keeps_it():
    content = _temporary(DATA)
    content_module.save(content, content.path)
    assert content.read() == DATA
    content.delete()


def test_as_file(make):
    content = make(DATA)
    with content_module.as_file(content, suffix=".mp4") as path:
        assert path.endswith(".mp4")
        with open(path, "rb") as handle:
            assert handle.read() == DATA
    assert not os.path.exists(path)
    # the original is untouched
    assert content_module.read(content) == DATA


def test_as_file_does_not_copy_a_file(monkeypatch):
    content = _temporary(DATA)
    copies = []
    monkeypatch.setattr(
        content_module.shutil, "copyfile", lambda *args: copies.append(args)
    )
    with content_module.as_file(content, suffix=".png") as path:
        assert os.path.samefile(path, content.path)
    assert copies == []
    assert content.read() == DATA
    content.delete()


def test_as_file_copies_where_it_cannot_link(monkeypatch):
    content = _temporary(DATA)

    def no_links(_source, _target):
        raise OSError("cross-device link")

    monkeypatch.setattr(content_module.os, "link", no_links)
    with content_module.as_file(content, suffix=".png") as path:
        assert not os.path.samefile(path, content.path)
        with open(path, "rb") as handle:
            assert handle.read() == DATA
    assert not os.path.exists(path)
    content.delete()


def test_temporary_copy_survives_the_original(make):
    original = make(DATA)
    copy = content_module.temporary_copy(original, suffix=".dat")
    if isinstance(original, Content):
        original.delete()
    assert copy.read() == DATA
    copy.delete()
    assert not os.path.exists(copy.path)


def test_file_content_equals_its_bytes():
    content = _temporary(b"content")
    assert content == b"content"
    assert b"content" == content
    assert content != b"contenu"
    assert content != b"longer content"
    assert content == _temporary(b"content")
    assert content != "content"
    assert len(content) == 7
    assert content


def test_temporary_content_is_deleted_explicitly():
    content = _temporary(DATA)
    path = content.path
    assert os.path.exists(path)
    content.delete()
    assert not os.path.exists(path)
    content.delete()  # again is harmless


def test_temporary_content_is_deleted_when_forgotten():
    content = _temporary(DATA)
    path = content.path
    del content
    gc.collect()
    assert not os.path.exists(path)


def test_content_of_someone_elses_file_is_never_deleted(tmpdir):
    path = str(tmpdir.join("stored.dat"))
    with open(path, "wb") as handle:
        handle.write(DATA)
    content = Content(path)
    assert content == DATA
    content.delete()
    del content
    gc.collect()
    assert os.path.exists(path)


def test_file_is_read_a_block_at_a_time(monkeypatch):
    content = _temporary(DATA)
    monkeypatch.setattr(content_module, "BLOCK_SIZE", 100000)
    sizes = [len(block) for block in content.blocks()]
    assert max(sizes) == 100000
    assert sum(sizes) == len(DATA)
    content.delete()
