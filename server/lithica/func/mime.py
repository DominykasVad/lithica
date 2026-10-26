import re

from lithica.func import content as content_module
from lithica.func.content import ContentLike

# the longest file signature looked at below ends at byte 12
SIGNATURE_LENGTH = 16

# two graphic control extensions mean two frames: an animation
_GIF_FRAME = re.compile(b"\x21\xf9\x04[\x00-\xff]{4}\x00[\x2c\x21]")
_GIF_FRAME_LENGTH = 10


def get_mime_type(content: ContentLike) -> str:
    content = content_module.head(content, SIGNATURE_LENGTH)
    if not content:
        return "application/octet-stream"

    if content[0:3] in (b"CWS", b"FWS", b"ZWS"):
        return "application/x-shockwave-flash"

    if content[0:3] == b"\xff\xd8\xff":
        return "image/jpeg"

    if content[0:6] == b"\x89PNG\x0d\x0a":
        return "image/png"

    if content[0:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"

    if content[8:12] == b"WEBP":
        return "image/webp"

    if content[0:2] == b"BM":
        return "image/bmp"

    if content[4:12] in (b"ftypavif", b"ftypavis"):
        return "image/avif"

    if content[4:12] == b"ftypmif1":
        return "image/heif"

    if content[4:12] in (b"ftypheic", b"ftypheix"):
        return "image/heic"

    if content[0:4] == b"\x1a\x45\xdf\xa3":
        return "video/webm"

    if content[4:12] in (
        b"ftypisom",
        b"ftypiso5",
        b"ftypiso6",
        b"ftypmp42",
        b"ftypM4V ",
    ):
        return "video/mp4"

    if content[4:12] == b"ftypqt  ":
        return "video/quicktime"

    return "application/octet-stream"


# The files the engine takes, by MIME type (what get_mime_type tells), with
# their usual extensions, the one a stored file gets first. GET /info lists
# them, with the file types of the modules that are switched on, as a hint
# for clients: the server still decides by the file's content.
ACCEPTED_TYPES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("image/jpeg", ("jpg", "jpeg", "jpe")),
    ("image/png", ("png",)),
    ("image/gif", ("gif",)),
    ("image/webp", ("webp",)),
    ("image/bmp", ("bmp",)),
    ("image/avif", ("avif",)),
    ("image/heif", ("heif",)),
    ("image/heic", ("heic",)),
    ("video/mp4", ("mp4", "m4v")),
    ("video/quicktime", ("mov",)),
    ("video/webm", ("webm",)),
    ("application/x-shockwave-flash", ("swf",)),
)


def get_extension(mime_type: str) -> str | None:
    extension_map = {
        "application/x-shockwave-flash": "swf",
        "image/gif": "gif",
        "image/jpeg": "jpg",
        "image/png": "png",
        "image/webp": "webp",
        "image/bmp": "bmp",
        "image/avif": "avif",
        "image/heif": "heif",
        "image/heic": "heic",
        "video/mp4": "mp4",
        "video/quicktime": "mov",
        "video/webm": "webm",
        "application/octet-stream": "dat",
    }
    return extension_map.get((mime_type or "").strip().lower(), None)


def is_flash(mime_type: str) -> bool:
    return mime_type.lower() == "application/x-shockwave-flash"


def is_video(mime_type: str) -> bool:
    return mime_type.lower() in (
        "application/ogg",
        "video/mp4",
        "video/quicktime",
        "video/webm",
    )


def is_image(mime_type: str) -> bool:
    return mime_type.lower() in (
        "image/jpeg",
        "image/png",
        "image/gif",
        "image/webp",
        "image/bmp",
        "image/avif",
        "image/heif",
        "image/heic",
    )


def is_animated_gif(content: ContentLike) -> bool:
    if get_mime_type(content) != "image/gif":
        return False
    # The content is searched a block at a time. A frame header may straddle
    # two blocks, so the end of each block is searched again with the next
    # one: as much of it as could start a header, and nothing of a header
    # that was already counted.
    frames = 0
    carry = b""
    for block in content_module.blocks(content):
        data = carry + block
        counted_up_to = 0
        for match in _GIF_FRAME.finditer(data):
            frames += 1
            counted_up_to = match.end()
        if frames > 1:
            return True
        carry = data[max(counted_up_to, len(data) - (_GIF_FRAME_LENGTH - 1)) :]
    return False


def is_heif(mime_type: str) -> bool:
    return mime_type.lower() in (
        "image/heif",
        "image/heic",
        "image/avif",
    )
