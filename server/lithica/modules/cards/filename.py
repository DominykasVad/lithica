"""
The name a card is downloaded under: the character's name and the
extension of the stored file.

The name comes out of an uploaded file and ends up as a file on somebody's
disk, by way of an HTTP header. So it is made harmless for all three: no
path, nothing a file system refuses or treats specially, nothing that
breaks out of the header.
"""

import unicodedata
from urllib.parse import quote

MAX_NAME_LENGTH = 100

# what a path or a Windows file name may not contain
_FORBIDDEN = '/\\<>:"|?*'

# names Windows keeps for devices, with any extension
_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *("COM%d" % number for number in range(1, 10)),
    *("LPT%d" % number for number in range(1, 10)),
}


def _is_usable(name: str) -> bool:
    return any(character.isalnum() for character in name)


def sanitised(name: str) -> str:
    """
    The name without what a file name must not have. Empty when nothing
    usable is left.
    """
    name = unicodedata.normalize("NFC", name)
    kept: list[str] = []
    for character in name:
        if character in _FORBIDDEN:
            kept.append("_")
        elif character.isspace():
            kept.append(" ")
        elif unicodedata.category(character).startswith("C"):
            # control and format characters (the ones that reorder text
            # among them), lone surrogates, unassigned code points
            continue
        else:
            kept.append(character)
    name = " ".join("".join(kept).split())
    # a file name does not start or end with a dot or a space
    name = name[:MAX_NAME_LENGTH].strip(" .")
    if not _is_usable(name):
        return ""
    if name.split(".")[0].strip().upper() in _RESERVED:
        name = "_" + name
    return name


def download_name(card_name: str, post_id: int, extension: str) -> tuple[str, str]:
    """
    The file name of a card's download: as it is, and in ASCII for programs
    that read nothing else. Without a usable name it is `card-<post id>`.
    """
    fallback = "card-%d" % post_id
    name = sanitised(card_name) or fallback
    ascii_name = name.encode("ascii", "replace").decode("ascii").replace("?", "_")
    if not _is_usable(ascii_name):
        ascii_name = fallback
    return "%s.%s" % (name, extension), "%s.%s" % (ascii_name, extension)


def content_disposition(card_name: str, post_id: int, extension: str) -> str:
    """
    The `Content-Disposition` header of a card's download (RFC 6266): the
    ASCII name for every client, and the real name, encoded, for those that
    read `filename*`.
    """
    name, ascii_name = download_name(card_name, post_id, extension)
    header = 'attachment; filename="%s"' % ascii_name
    if name != ascii_name:
        header += "; filename*=UTF-8''%s" % quote(name, safe="")
    return header
