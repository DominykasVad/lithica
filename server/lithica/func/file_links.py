"""
Signed addresses of post files and thumbnails (`file_link_secret`).

The web server in front checks them with nginx's secure_link module, its
`secure_link_md5` form:

    ?e=<expiry>&s=<signature>
    signature = base64url, unpadded, of md5("<expiry><path> <secret>")

`path` is the file's path under the data directory, from its first slash
(`/posts/5_abc.png`), not the address's whole path: the data directory may
be served under any prefix or from another host, and the path under it is
the same for the server that signs and the nginx that checks.

An address is valid until the start of the day after tomorrow (UTC): the
same address for a whole day, so that browsers keep their copy, and valid
for 24 to 48 hours.
"""

import base64
import calendar
import datetime
import hashlib

from lithica import config
from lithica.func import util


def secret() -> str | None:
    return config.config.get("file_link_secret") or None


def expiry(now: datetime.datetime | None = None) -> int:
    """The start of the day after tomorrow, UTC, in seconds since the epoch."""
    now = now or util.utcnow()
    day = datetime.datetime(now.year, now.month, now.day) + datetime.timedelta(days=2)
    return calendar.timegm(day.timetuple())


def signature(path: str, expires: int, key: str) -> str:
    digest = hashlib.md5(f"{expires}{path} {key}".encode()).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def link(url: str, path: str) -> str:
    """
    The address of a file, signed when the site signs its file links: `url`
    as given otherwise. `path` is the file's path under the data directory.
    """
    key = secret()
    if key is None:
        return url
    expires = expiry()
    return "%s?e=%d&s=%s" % (
        url,
        expires,
        signature("/" + path.lstrip("/"), expires, key),
    )
