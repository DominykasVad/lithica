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


# ---------------------------------------------------------------------------
# where temporary files live, how they become stored files, and their cleanup


@pytest.fixture
def data_dir(config_injector, tmpdir):
    path = str(tmpdir.mkdir("data"))
    config_injector({"data_dir": path})
    return path


def _temporary_dir_of(data_dir: str) -> str:
    return os.path.join(data_dir, "temporary-uploads", ".tmp")


def test_temporary_dir_is_in_the_data_directory_and_made_on_demand(data_dir):
    expected = _temporary_dir_of(data_dir)
    assert not os.path.exists(expected)
    assert content_module.temporary_dir() == expected
    assert os.path.isdir(expected)
    # again, now that it exists
    assert content_module.temporary_dir() == expected


@pytest.mark.parametrize("settings", [{}, {"data_dir": None}, {"data_dir": ""}])
def test_temporary_dir_without_a_data_directory(config_injector, settings):
    import tempfile

    config_injector(settings)
    assert content_module.temporary_dir() == tempfile.gettempdir()


def test_every_temporary_file_is_made_in_the_data_directory(data_dir):
    from lithica.func import util

    folder = _temporary_dir_of(data_dir)
    created = Content.create_temporary(suffix=".dat")
    copied = content_module.temporary_copy(b"data")
    assert os.path.dirname(created.path) == folder
    assert os.path.dirname(copied.path) == folder
    with content_module.as_file(b"data", suffix=".png") as path:
        assert os.path.dirname(path) == folder
    with content_module.as_file(copied, suffix=".png") as path:
        assert os.path.dirname(path) == folder
    with util.create_temp_file(suffix=".log") as handle:
        assert os.path.dirname(handle.name) == folder
    with util.create_temp_file_path(suffix=".dat") as path:
        assert os.path.dirname(path) == folder
    created.delete()
    copied.delete()
    assert os.listdir(folder) == []


def _ordinary_file_mode(directory: str) -> int:
    path = os.path.join(directory, "ordinary")
    with open(path, "wb"):
        pass
    mode = os.stat(path).st_mode & 0o777
    os.remove(path)
    return mode


def test_saving_a_temporary_content_renames_it(data_dir, monkeypatch):
    copies = []
    monkeypatch.setattr(
        content_module.shutil, "copyfile", lambda *args: copies.append(args)
    )
    content = _temporary(DATA)
    old_path = content.path
    inode = os.stat(old_path).st_ino
    # a temporary file is private; a stored file must not stay that way
    assert os.stat(old_path).st_mode & 0o777 == 0o600
    target = os.path.join(data_dir, "stored.dat")

    content_module.save(content, target)

    assert copies == []
    assert not os.path.exists(old_path)
    assert os.stat(target).st_ino == inode
    assert os.stat(target).st_mode & 0o777 == _ordinary_file_mode(data_dir)
    # the content follows its file and can still be read
    assert content.path == target
    assert content == DATA
    assert os.listdir(_temporary_dir_of(data_dir)) == []


def test_stored_file_outlives_the_content_that_was_renamed_into_it(data_dir):
    content = _temporary(DATA)
    target = os.path.join(data_dir, "stored.dat")
    content_module.save(content, target)
    content.delete()
    assert os.path.exists(target)
    del content
    gc.collect()
    assert os.path.exists(target)
    # and saving it once more somewhere else copies: it is stored content now
    second = os.path.join(data_dir, "second.dat")
    content_module.save(Content(target), second)
    assert os.path.exists(target) and os.path.exists(second)


def test_renaming_replaces_an_existing_file(data_dir):
    target = os.path.join(data_dir, "stored.dat")
    with open(target, "wb") as handle:
        handle.write(b"older")
    content_module.save(_temporary(DATA), target)
    with open(target, "rb") as handle:
        assert handle.read() == DATA


def test_saving_content_that_must_stay_copies_it(data_dir):
    source = os.path.join(data_dir, "source.dat")
    with open(source, "wb") as handle:
        handle.write(DATA)
    target = os.path.join(data_dir, "target.dat")
    content = Content(source)
    content_module.save(content, target)
    assert content.path == source
    assert os.path.exists(source)
    assert os.stat(source).st_ino != os.stat(target).st_ino
    with open(target, "rb") as handle:
        assert handle.read() == DATA


def test_saving_copies_where_it_cannot_rename(data_dir, monkeypatch):
    # the temporary folder and the target on different file systems
    def cross_device(_source, _target):
        raise OSError(18, "Invalid cross-device link")

    monkeypatch.setattr(content_module.os, "replace", cross_device)
    content = _temporary(DATA)
    old_path = content.path
    target = os.path.join(data_dir, "stored.dat")
    content_module.save(content, target)
    with open(target, "rb") as handle:
        assert handle.read() == DATA
    assert os.stat(target).st_mode & 0o777 == _ordinary_file_mode(data_dir)
    # the temporary file is still the content's, and goes when it is deleted
    assert content.path == old_path and os.path.exists(old_path)
    content.delete()
    assert not os.path.exists(old_path)
    assert os.path.exists(target)


def test_a_stored_file_is_given_to_programs_by_link_not_by_copy(data_dir, monkeypatch):
    stored = os.path.join(data_dir, "posts")
    os.makedirs(stored)
    path = os.path.join(stored, "1.mp4")
    with open(path, "wb") as handle:
        handle.write(DATA)
    copies = []
    monkeypatch.setattr(
        content_module.shutil, "copyfile", lambda *args: copies.append(args)
    )
    with content_module.as_file(Content(path), suffix=".mp4") as named:
        assert os.path.samefile(named, path)
    assert copies == []
    assert os.path.exists(path)


def _age(path: str, seconds: int) -> None:
    import time

    then = time.time() - seconds
    os.utime(path, (then, then), follow_symlinks=False)


def _leftovers(data_dir: str) -> dict[str, str]:
    """An old file, an old upload directory, and fresh ones of both."""
    folder = content_module.temporary_dir()
    paths = {}
    for name, age in [("old", 2 * 3600), ("fresh", 60)]:
        file_path = os.path.join(folder, "content-" + name)
        with open(file_path, "wb") as handle:
            handle.write(b"x")
        directory = os.path.join(folder, "upload-" + name)
        os.makedirs(directory)
        inner = os.path.join(directory, "part")
        with open(inner, "wb") as handle:
            handle.write(b"x")
        for path in [file_path, inner, directory]:
            _age(path, age)
        paths["file " + name] = file_path
        paths["directory " + name] = directory
    return paths


def test_stale_temporary_files_are_removed(data_dir):
    paths = _leftovers(data_dir)
    assert content_module.remove_stale_temporary_files() == 2
    assert not os.path.exists(paths["file old"])
    assert not os.path.exists(paths["directory old"])
    assert os.path.exists(paths["file fresh"])
    assert os.path.exists(os.path.join(paths["directory fresh"], "part"))
    # nothing more to do the second time
    assert content_module.remove_stale_temporary_files() == 0


def test_files_just_under_an_hour_old_are_kept(data_dir):
    folder = content_module.temporary_dir()
    path = os.path.join(folder, "content-almost")
    with open(path, "wb"):
        pass
    _age(path, 3600 - 60)
    assert content_module.remove_stale_temporary_files() == 0
    _age(path, 3600 + 60)
    assert content_module.remove_stale_temporary_files() == 1


def test_upload_still_being_written_is_kept_although_its_directory_is_old(data_dir):
    # a long upload: the directory was made over an hour ago, the file in
    # it is being written to now
    folder = content_module.temporary_dir()
    directory = os.path.join(folder, "upload-long")
    os.makedirs(directory)
    with open(os.path.join(directory, "part"), "wb") as handle:
        handle.write(b"x")
    _age(directory, 2 * 3600)
    assert content_module.remove_stale_temporary_files() == 0
    assert os.path.exists(os.path.join(directory, "part"))


def test_cleanup_only_looks_at_its_own_folder(data_dir):
    stored = os.path.join(data_dir, "temporary-uploads", "0" * 40 + ".dat")
    content_module.temporary_dir()
    with open(stored, "wb") as handle:
        handle.write(b"x")
    post = os.path.join(data_dir, "old-post.png")
    with open(post, "wb") as handle:
        handle.write(b"x")
    for path in [stored, post]:
        _age(path, 10 * 3600)
    assert content_module.remove_stale_temporary_files() == 0
    assert os.path.exists(stored) and os.path.exists(post)


def test_cleanup_never_sweeps_the_system_temporary_directory(config_injector, tmpdir):
    import tempfile

    config_injector({})
    path = os.path.join(tempfile.gettempdir(), "lithica-test-not-ours")
    with open(path, "wb"):
        pass
    try:
        _age(path, 10 * 3600)
        assert content_module.remove_stale_temporary_files() == 0
        assert os.path.exists(path)
    finally:
        os.remove(path)


def test_cleanup_by_several_processes_at_once(data_dir):
    import threading

    folder = content_module.temporary_dir()
    for number in range(200):
        path = os.path.join(folder, "content-%d" % number)
        with open(path, "wb"):
            pass
        _age(path, 2 * 3600)
    fresh = os.path.join(folder, "content-fresh")
    with open(fresh, "wb"):
        pass
    start = threading.Barrier(8)
    removed, errors = [], []

    def clean() -> None:
        try:
            start.wait(timeout=10)
            removed.append(content_module.remove_stale_temporary_files())
        except Exception as ex:
            errors.append(ex)

    threads = [threading.Thread(target=clean) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    assert len(removed) == 8
    # Every stale file is gone and the fresh one is not. (How many each
    # counted is not checked: on macOS two processes can both be told they
    # removed the same file.)
    assert sum(removed) >= 200
    assert os.listdir(folder) == ["content-fresh"]


def test_cleanup_survives_a_file_removed_by_someone_else(data_dir, monkeypatch):
    paths = _leftovers(data_dir)
    real_remove = os.remove

    def remove_twice(path):
        real_remove(path)
        raise FileNotFoundError(path)

    monkeypatch.setattr(content_module.os, "remove", remove_twice)
    # the old file "vanished" under it; the old directory is still removed
    assert content_module.remove_stale_temporary_files() == 1
    assert not os.path.exists(paths["directory old"])
    assert os.path.exists(paths["file fresh"])
