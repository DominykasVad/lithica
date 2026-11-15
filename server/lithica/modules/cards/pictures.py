"""Pictures carried by card files, compared independently of their metadata."""

import warnings
from io import BytesIO
from typing import TypedDict

from PIL import Image

from lithica import errors
from lithica.func import image_hash, images, mime
from lithica.func.content import Content, ContentLike
from lithica.modules.cards import assets, charx, png


class Comparison(TypedDict):
    samePixels: bool
    similarity: float | None
    oldPicture: bool
    newPicture: bool


def picture(content: ContentLike) -> bytes | None:
    """Return a PNG's stripped picture or a CHARX's main icon, never a URL."""
    source = content.open() if isinstance(content, Content) else BytesIO(content)
    with source:
        if mime.get_mime_type(content) == "image/png":
            return png.stripped(source, limit=assets.MAX_IMAGE_SIZE)
        try:
            with charx.opened(source) as archive:
                uri = charx.icon_uri(archive.card)
                icon = (
                    charx.data_uri_bytes(uri, assets.MAX_IMAGE_SIZE)
                    if uri is not None and uri.startswith("data:")
                    else charx.asset_bytes(archive, uri, assets.MAX_IMAGE_SIZE)
                    if uri is not None
                    else None
                )
        except (charx.NotCharx, charx.Rejected):
            return None
    if icon is None:
        return None
    detected = mime.get_mime_type(icon)
    if not (mime.is_image(detected) or mime.is_video(detected)):
        return None
    return icon


def same_pixels(old: bytes | None, new: bytes | None) -> bool:
    """Compare header sizes before decoding RGBA pixels, keeping Pillow limits."""
    if old is None or new is None:
        return False
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with images.pillow_image(old) as first, images.pillow_image(new) as second:
                if first.size != second.size:
                    return False
                with first.convert("RGBA") as first_rgba:
                    with second.convert("RGBA") as second_rgba:
                        return first_rgba.tobytes() == second_rgba.tobytes()
    except (
        errors.ProcessingError,
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
