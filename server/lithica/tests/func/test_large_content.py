"""
Content too large to be held in memory: a post is made from it, stored,
merged and thumbnailed without the file ever being read whole.
"""

import hashlib
import os
import shutil
import struct
import tracemalloc

import pytest

from lithica import db, model
from lithica.func import content as content_module
from lithica.func import file_uploads, posts
from lithica.func.content import Content

MEGABYTE = 1024 * 1024

needs_ffmpeg = pytest.mark.skipif(
    shutil.which("ffmpeg") is None, reason="ffmpeg is not installed"
)


def make_large_video(path: str, size: int, small_video: bytes) -> None:
    """
    Write a playable MP4 of about `size` bytes: a tiny real video followed
    by one `free` box of padding, which players skip.
    """
    padding = size - len(small_video) - 16
    block = b"\0" * MEGABYTE
    with open(path, "wb") as handle:
        handle.write(small_video)
        # size 1 means: the real size is the 64-bit number after the type
        handle.write(struct.pack(">I4sQ", 1, b"free", 16 + padding))
        for _ in range(padding // MEGABYTE):
            handle.write(block)
        handle.write(b"\0" * (padding % MEGABYTE))


def _sha1_of_file(path: str) -> str:
    digest = hashlib.sha1()
    with open(path, "rb") as handle:
        while block := handle.read(MEGABYTE):
            digest.update(block)
    return digest.hexdigest()


@pytest.fixture(autouse=True)
def inject_config(config_injector, tmpdir):
    config_injector(
        {
            "data_dir": str(tmpdir.mkdir("data")),
            "data_url": "example.com",
            "delete_source_files": True,
            "allow_broken_uploads": False,
            "secret": "test",
            "thumbnails": {"post_width": 300, "post_height": 300},
            "convert": {"gif": {"to_mp4": False, "to_webm": False}},
        }
    )


@pytest.fixture
def large_video(tmpdir, read_asset):
    path = str(tmpdir.join("large.mp4"))
    make_large_video(path, 96 * MEGABYTE, read_asset("mp4.mp4"))
    return Content(path)


@needs_ffmpeg
def test_post_is_created_from_a_large_video_without_reading_it_whole(
    large_video, tmpdir, tag_category_factory
):
    db.session.add(tag_category_factory(default=True))
    db.session.flush()
    size = large_video.size
    assert size == 96 * MEGABYTE
    expected_sha1 = _sha1_of_file(large_video.path)

    tracemalloc.start()
    try:
        post, _new_tags = posts.create_post(large_video, [], None)
        flags = posts.get_default_flags(large_video)
        db.session.flush()
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    # everything the pipeline needs to know about the file was found out
    assert post.type == model.Post.TYPE_VIDEO
    assert post.mime_type == "video/mp4"
    assert post.file_size == size
    assert post.checksum == expected_sha1
    assert post.checksum_md5 is not None and len(post.checksum_md5) == 32
    assert (post.canvas_width, post.canvas_height) == (8, 8)
    assert model.Post.FLAG_LOOP in flags

    # the content and a thumbnail are stored
    stored = os.path.join(str(tmpdir), "data", posts.get_post_content_path(post))
    assert os.path.getsize(stored) == size
    assert _sha1_of_file(stored) == expected_sha1
    thumbnail = os.path.join(str(tmpdir), "data", posts.get_post_thumbnail_path(post))
    assert os.path.getsize(thumbnail) > 0

    # and at no point was a twelfth of the file in memory
    assert peak < 8 * MEGABYTE, "peak of %.1f MB" % (peak / MEGABYTE)


def test_the_measurement_notices_a_file_read_whole(large_video):
    # the measurements in this file would also pass if they measured
    # nothing; reading the file into memory does show up
    tracemalloc.start()
    try:
        large_video.read()
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak > large_video.size


def test_large_file_is_stored_as_a_temporary_upload_without_reading_it_whole(
    large_video,
):
    tracemalloc.start()
    try:
        token = file_uploads.save(large_video)
        stored = file_uploads.get(token)
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert token == _sha1_of_file(large_video.path)
    assert stored is not None
    assert stored.size == large_video.size
    assert stored.path != large_video.path
    assert peak < 8 * MEGABYTE, "peak of %.1f MB" % (peak / MEGABYTE)


@needs_ffmpeg
def test_merge_takes_over_the_content_although_the_source_file_is_deleted(
    post_factory, read_asset, tmpdir, monkeypatch
):
    copies = []
    real_temporary_copy = content_module.temporary_copy

    def recording_temporary_copy(*args, **kwargs):
        copies.append(real_temporary_copy(*args, **kwargs))
        return copies[-1]

    monkeypatch.setattr(content_module, "temporary_copy", recording_temporary_copy)

    source_post = post_factory(id=1)
    target_post = post_factory(id=2)
    db.session.add_all([source_post, target_post])
    db.session.commit()
    content = read_asset("png.png")
    posts.update_post_content(source_post, content)
    db.session.flush()
    data_dir = os.path.join(str(tmpdir), "data")
    source_path = os.path.join(data_dir, posts.get_post_content_path(source_post))
    assert os.path.exists(source_path)

    posts.merge_posts(source_post, target_post, True)
    db.session.flush()

    # the source's file went with the source post (delete_source_files) ...
    assert not os.path.exists(source_path)
    # ... and the target has its content all the same
    target = posts.get_post_by_id(2)
    target_path = os.path.join(data_dir, posts.get_post_content_path(target))
    with open(target_path, "rb") as handle:
        assert handle.read() == content
    assert target.checksum == hashlib.sha1(content).hexdigest()
    assert target.mime_type == "image/png"

    # the copy that bridged the gap is gone as well
    assert len(copies) == 1
    copy_path = copies[0].path
    del copies[:]
    assert not os.path.exists(copy_path)
