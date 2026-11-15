"""Bounded, lazy images explicitly named by a card file; no network access."""

from collections.abc import Callable, Generator
from contextlib import contextmanager
from dataclasses import dataclass
from io import BytesIO
from itertools import chain
from typing import BinaryIO, cast

from lithica import errors
from lithica.func import mime, post_metadata
from lithica.func.content import Content, ContentLike
from lithica.modules.cards import card as card_format
from lithica.modules.cards import charx, png

MAX_IMAGES = 200
MAX_IMAGE_SIZE = 32 * 1024 * 1024


@dataclass(frozen=True)
class Image:
    uri: str
    asset_type: str | None
    relation: str
    label: str | None
    main: bool = False
    position: int = 0


@dataclass
class Source:
    images: list[Image]
    read: Callable[[str], bytes | None]

    def picture(self, image: Image) -> bytes | None:
        data = self.read(image.uri)
        if data is None or len(data) > MAX_IMAGE_SIZE:
            return None
        detected = mime.get_mime_type(data)
        return data if mime.is_image(detected) or mime.is_video(detected) else None


def images(card: dict[str, object], is_png: bool) -> list[Image]:
    kind = card_format.kind_of(card)
    if kind is None:
        return []
    fields = card_format.fields_of(kind, card)
    raw = fields.get("assets")
    if not isinstance(raw, list):
        return [Image("ccdefault:", None, "avatar-of", None, True)] if is_png else []
    main = card_format.main_icon_asset(fields)
    positions: dict[str, int] = {}
    for position, value in enumerate(cast(list[object], raw)):
        if isinstance(value, dict):
            uri = cast(dict[str, object], value).get("uri")
            if isinstance(uri, str):
                positions.setdefault(uri, position)
    candidates: list[Image] = []
    seen: set[str] = set()
    for value in chain([main] if main is not None else [], cast(list[object], raw)):
        if not isinstance(value, dict):
            continue
        asset = cast(dict[str, object], value)
        uri, type_ = asset.get("uri"), asset.get("type")
        if (
            not isinstance(uri, str)
            or len(uri) > 1024
            or "\x00" in uri
            or any(0xD800 <= ord(c) <= 0xDFFF for c in uri)
            or uri in seen
            or not isinstance(type_, str)
            or len(type_) > 64
            or "\x00" in type_
            or any(0xD800 <= ord(c) <= 0xDFFF for c in type_)
        ):
            continue
        seen.add(uri)
        if not uri.startswith(
            ("data:", "__asset:" if is_png else "embeded://", "embedded://")
        ) and not (is_png and uri == "ccdefault:"):
            continue
        name = asset.get("name")
        try:
            label = post_metadata.clean_label(name if isinstance(name, str) else None)
        except errors.ValidationError:
            label = None
        role = (
            "avatar-of"
            if type_ == "icon"
            else "expression-of"
            if type_ == "emotion" and label
            else "embedded-in"
        )
        candidates.append(Image(uri, type_, role, label, value is main, positions[uri]))
        if len(candidates) == MAX_IMAGES:
            break
    return candidates


@contextmanager
def opened(content: ContentLike) -> Generator[Source]:
    handle: BinaryIO = (
        content.open() if isinstance(content, Content) else BytesIO(content)
    )
    with handle:
        handle.seek(0)
        is_png = handle.read(8) == png.SIGNATURE
        if is_png:
            card = png.read_card(handle)

            def read(uri: str) -> bytes | None:
                if uri == "ccdefault:":
                    return png.stripped(handle, limit=MAX_IMAGE_SIZE)
                if uri.startswith("__asset:"):
                    return png.read_asset(
                        handle, uri[len("__asset:") :], MAX_IMAGE_SIZE
                    )
                if uri.startswith("data:"):
                    return charx.data_uri_bytes(uri, MAX_IMAGE_SIZE)
                return None

            yield Source(images(card, True) if card else [], read)
        else:
            with charx.opened(handle) as archive:

                def read_charx(uri: str) -> bytes | None:
                    if uri.startswith("data:"):
                        return charx.data_uri_bytes(uri, MAX_IMAGE_SIZE)
                    return charx.asset_bytes(archive, uri, MAX_IMAGE_SIZE)

                yield Source(images(archive.card, False), read_charx)
