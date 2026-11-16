"""Uploaded PNG metadata cannot consume Pillow's text decoding budget."""

from collections.abc import Callable
from pathlib import Path

import pytest
from PIL import Image

from lithica import db, errors, model
from lithica.func import files, posts
from lithica.tests.api.http import ok
from lithica.tests.conftest import ApiClient
from lithica.tests.modules import cards


@pytest.mark.parametrize("chunk", ["card", "asset"])
def test_large_compressed_png_text_uploads_unchanged(
    site: Callable[[list[str]], ApiClient], user: model.User, chunk: str
) -> None:
    client = site(["cards"])
    if chunk == "card":
        content = cards.png_with(
            cards.compressed_text_chunk(
                b"chara", cards.encoded(cards.v2_card(description="x" * (1024 * 1024)))
            )
        )
    else:
        content = cards.png_with(
            cards.text_chunk(b"chara", cards.encoded(cards.v2_card())),
            cards.compressed_text_chunk(
                b"chara-ext-asset_:sprite", b"A" * (2 * 1024 * 1024)
            ),
        )
    answer = ok(
        client.post(
            "/posts", user=user, body={"safety": "safe"}, files={"content": content}
        )
    )
    post = posts.get_post_by_id(answer["id"])
    assert files.get(posts.get_post_content_path(post)) == content
    assert post.canvas_width == post.canvas_height == 64
    assert db.session.get(model.PostSignature, post.post_id) is not None
    thumbnail = files.get(posts.get_post_thumbnail_path(post))
    assert thumbnail is not None
    with Image.open(thumbnail.path) as decoded:
        assert decoded.format == "JPEG" and decoded.size == (300, 300)


def test_png_pixel_bomb_is_still_refused(
    site: Callable[[list[str]], ApiClient],
    user: model.User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = site(["cards"])
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 100)
    content = cards.png_card(cards.v2_card())
    with pytest.raises(Image.DecompressionBombError):
        client.post(
            "/posts", user=user, body={"safety": "safe"}, files={"content": content}
        )


def test_decoding_view_preserves_nontext_chunks_and_cleans_up(tmp_path: Path) -> None:
    import os
    import struct

    from lithica.func import png
    from lithica.func.content import Content

    def chunk(kind: bytes, data: bytes) -> bytes:
        # The view copies CRC bytes without interpreting them.
        return struct.pack(">I", len(data)) + kind + data + b"crc!"

    retained = chunk(b"acTL", b"animation") + chunk(b"IDAT", b"pixels")
    end = chunk(b"IEND", b"")
    original = (
        png.SIGNATURE
        + chunk(b"tEXt", b"plain")
        + retained
        + chunk(b"zTXt", b"not even valid compressed text")
        + chunk(b"iTXt", b"international")
        + end
        + b"trailer"
    )
    path = tmp_path / "original.png"
    path.write_bytes(original)
    content = Content(str(path))
    with pytest.raises(RuntimeError), png.for_decoding(content) as view:
        assert isinstance(view, Content)
        view_path = view.path
        assert view.read() == png.SIGNATURE + retained + end + b"trailer"
        assert view.size <= content.size
        raise RuntimeError("consumer failed")
    assert not os.path.exists(view_path)
    assert path.read_bytes() == original


def test_decoding_view_rejects_chunk_claiming_bytes_outside_input() -> None:
    import struct

    from lithica.func import png

    truncated = png.SIGNATURE + struct.pack(">I4s", 0xFFFFFFFF, b"zTXt") + b"crc!"
    with pytest.raises(errors.ProcessingError, match="Truncated PNG chunk"):
        with png.for_decoding(truncated):
            pytest.fail("An out-of-bounds chunk must never be decoded")


def test_decoding_view_leaves_other_formats_unchanged() -> None:
    from lithica.func import png

    original = b"GIF89a"
    with png.for_decoding(original) as view:
        assert view is original
