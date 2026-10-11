import pytest

from lithica.func import mime


@pytest.mark.parametrize(
    "input_path,expected_mime_type",
    [
        ("mp4.mp4", "video/mp4"),
        ("mov.mov", "video/quicktime"),
        ("webm.webm", "video/webm"),
        ("flash.swf", "application/x-shockwave-flash"),
        ("png.png", "image/png"),
        ("jpeg.jpg", "image/jpeg"),
        ("gif.gif", "image/gif"),
        ("webp.webp", "image/webp"),
        ("bmp.bmp", "image/bmp"),
        ("avif.avif", "image/avif"),
        ("avif-avis.avif", "image/avif"),
        ("heif.heif", "image/heif"),
        ("heic.heic", "image/heic"),
        ("heic-heix.heic", "image/heic"),
        ("text.txt", "application/octet-stream"),
    ],
)
def test_get_mime_type(read_asset, input_path, expected_mime_type):
    assert mime.get_mime_type(read_asset(input_path)) == expected_mime_type


def test_get_mime_type_for_empty_file():
    assert mime.get_mime_type(b"") == "application/octet-stream"


@pytest.mark.parametrize(
    "mime_type,expected_extension",
    [
        ("video/mp4", "mp4"),
        ("video/webm", "webm"),
        ("video/quicktime", "mov"),
        ("application/x-shockwave-flash", "swf"),
        ("image/png", "png"),
        ("image/jpeg", "jpg"),
        ("image/gif", "gif"),
        ("image/webp", "webp"),
        ("image/bmp", "bmp"),
        ("image/avif", "avif"),
        ("image/heif", "heif"),
        ("image/heic", "heic"),
        ("application/octet-stream", "dat"),
    ],
)
def test_get_extension(mime_type, expected_extension):
    assert mime.get_extension(mime_type) == expected_extension


@pytest.mark.parametrize(
    "input_mime_type,expected_state",
    [
        ("application/x-shockwave-flash", True),
        ("APPLICATION/X-SHOCKWAVE-FLASH", True),
        ("application/x-shockwave", False),
    ],
)
def test_is_flash(input_mime_type, expected_state):
    assert mime.is_flash(input_mime_type) == expected_state


@pytest.mark.parametrize(
    "input_mime_type,expected_state",
    [
        ("video/webm", True),
        ("VIDEO/WEBM", True),
        ("video/mp4", True),
        ("VIDEO/MP4", True),
        ("video/quicktime", True),
        ("VIDEO/QUICKTIME", True),
        ("video/anything_else", False),
        ("application/ogg", True),
        ("not a video", False),
    ],
)
def test_is_video(input_mime_type, expected_state):
    assert mime.is_video(input_mime_type) == expected_state


@pytest.mark.parametrize(
    "input_mime_type,expected_state",
    [
        ("image/gif", True),
        ("image/png", True),
        ("image/jpeg", True),
        ("image/bmp", True),
        ("image/avif", True),
        ("image/heic", True),
        ("image/heif", True),
        ("IMAGE/GIF", True),
        ("IMAGE/PNG", True),
        ("IMAGE/JPEG", True),
        ("IMAGE/BMP", True),
        ("IMAGE/AVIF", True),
        ("IMAGE/HEIC", True),
        ("IMAGE/HEIF", True),
        ("image/anything_else", False),
        ("not an image", False),
    ],
)
def test_is_image(input_mime_type, expected_state):
    assert mime.is_image(input_mime_type) == expected_state


@pytest.mark.parametrize(
    "input_path,expected_state",
    [
        ("gif.gif", False),
        ("gif-animated.gif", True),
    ],
)
def test_is_animated_gif(read_asset, input_path, expected_state):
    assert mime.is_animated_gif(read_asset(input_path)) == expected_state


@pytest.mark.parametrize(
    "input_mime_type,expected_state",
    [
        ("image/gif", False),
        ("image/png", False),
        ("image/jpeg", False),
        ("image/avif", True),
        ("image/heic", True),
        ("image/heif", True),
        ("IMAGE/GIF", False),
        ("IMAGE/PNG", False),
        ("IMAGE/JPEG", False),
        ("IMAGE/AVIF", True),
        ("IMAGE/HEIC", True),
        ("IMAGE/HEIF", True),
        ("image/anything_else", False),
        ("not an image", False),
    ],
)
def test_is_heif(input_mime_type, expected_state):
    assert mime.is_heif(input_mime_type) == expected_state


@pytest.mark.parametrize("block_size", [1, 7, 9, 10, 11, 64, 10**6])
@pytest.mark.parametrize(
    "input_path,expected_state",
    [("gif.gif", False), ("gif-animated.gif", True), ("png.png", False)],
)
def test_is_animated_gif_reads_a_file_in_blocks(
    read_asset, monkeypatch, block_size, input_path, expected_state
):
    # whatever the block size, a frame header split over two blocks is
    # counted, and counted once
    from lithica.func import content as content_module

    monkeypatch.setattr(content_module, "BLOCK_SIZE", block_size)
    content = content_module.temporary_copy(read_asset(input_path))
    assert mime.is_animated_gif(content) == expected_state
    content.delete()


@pytest.mark.parametrize("block_size", [1, 3, 9, 10, 11, 13, 19, 20, 21, 64])
def test_animated_gif_frames_are_counted_as_in_one_piece(monkeypatch, block_size):
    import re

    from lithica.func import content as content_module

    header = b"\x21\xf9\x04abcd\x00\x2c"
    # the last byte of the first header also starts what looks like a second
    # one; searching the whole content does not count that, and neither may
    # the search in blocks
    overlapping = b"GIF89a" + b"\x21\xf9\x04abcd\x00\x21" + b"\xf9\x04efgh\x00\x2c"
    monkeypatch.setattr(content_module, "BLOCK_SIZE", block_size)
    for data in [
        b"GIF89a" + header,
        b"GIF89a" + header + b"x" * 30 + header,
        b"GIF89a" + header + header,
        b"GIF89a" + b"x" * 17 + header + b"y" * 5,
        overlapping,
        b"GIF89a",
    ]:
        whole = len(re.findall(mime._GIF_FRAME, data)) > 1
        content = content_module.temporary_copy(data)
        assert mime.is_animated_gif(content) == whole, (block_size, data)
        assert mime.is_animated_gif(data) == whole
        content.delete()


def test_mime_type_of_a_file(read_asset):
    from lithica.func import content as content_module

    for name, expected in [
        ("png.png", "image/png"),
        ("mp4.mp4", "video/mp4"),
        ("webm.webm", "video/webm"),
        ("text.txt", "application/octet-stream"),
    ]:
        content = content_module.temporary_copy(read_asset(name))
        assert mime.get_mime_type(content) == expected
        content.delete()
    empty = content_module.Content.create_temporary()
    assert mime.get_mime_type(empty) == "application/octet-stream"
    empty.delete()
