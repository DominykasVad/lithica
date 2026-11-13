"""Pictures carried by card files, compared independently of their metadata."""

import warnings
from io import BytesIO
from typing import TypedDict

from PIL import Image

from lithica import errors
from lithica.func import content as content_module
from lithica.func import image_hash, mime
from lithica.func.content import Content, ContentLike
from lithica.modules.cards import charx


class Comparison(TypedDict):
    samePixels: bool
    similarity: float | None
    oldPicture: bool
    newPicture: bool


def picture(content: ContentLike) -> bytes | None:
    """Return a PNG's bytes or a CHARX's main icon, never an outside URL."""
    if mime.get_mime_type(content) == "image/png":
        return content_module.read(content)
    source = content.open() if isinstance(content, Content) else BytesIO(content)
    with source:
        try:
            with charx.opened(source) as archive:
                icon = charx.main_icon(archive)
        except (charx.NotCharx, charx.Rejected):
            return None
    if icon is None or not mime.is_image(mime.get_mime_type(icon)):
        return None
    return icon


def same_pixels(old: bytes | None, new: bytes | None) -> bool:
    """Compare header sizes before decoding RGBA pixels, keeping Pillow limits."""
    if old is None or new is None:
        return False
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(old)) as first, Image.open(BytesIO(new)) as second:
                if first.size != second.size:
                    return False
                with first.convert("RGBA") as first_rgba:
                    with second.convert("RGBA") as second_rgba:
                        return first_rgba.tobytes() == second_rgba.tobytes()
    except (
        OSError,
        ValueError,
        SyntaxError,
        EOFError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ):
        return False


def compare(old: bytes | None, new: bytes | None) -> Comparison:
    """Return pixel equality and advisory greyscale signature similarity."""
    similarity: float | None = None
    if old is not None and new is not None:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                first = image_hash.generate_signature(old)
                second = image_hash.generate_signature(new)
                distance = image_hash.normalized_distance([first], second)[0]
                similarity = round(max(0.0, min(1.0, 1.0 - float(distance))), 2)
        except (
            errors.ProcessingError,
            OSError,
            ValueError,
            SyntaxError,
            EOFError,
            Image.DecompressionBombError,
            Image.DecompressionBombWarning,
        ):
            # A picture can have an engine signature yet fail to decode fully.
            similarity = None
    return {
        "samePixels": same_pixels(old, new),
        "similarity": similarity,
        "oldPicture": old is not None,
        "newPicture": new is not None,
    }
