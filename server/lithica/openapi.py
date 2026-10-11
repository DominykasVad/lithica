"""
The OpenAPI document of the API: the contract clients are written against.

    python -m lithica.openapi > ../doc/openapi.json

prints it. The committed doc/openapi.json must be what this prints; CI
checks that. Never edit that file by hand.
"""

import json
import sys
from typing import Any

from lithica import config

DESCRIPTION = """\
The API of Lithica, a self-hosted image board.

How the API works (authentication, file uploads, errors, field selection,
versioning, what the resources mean and the search syntax) is explained in
`doc/API.md` of the source. This document is the reference of the endpoints.

Every request must send `Accept: application/json`. A request may be
anonymous; what it is allowed to do then is set by the privileges in the
server's configuration.
"""

TAGS: list[dict[str, str]] = [
    {"name": "Info", "description": "The site, its settings and its featured post."},
    {"name": "Users", "description": "Accounts."},
    {
        "name": "User tokens",
        "description": "Login tokens: credentials a client keeps instead of the "
        "password.",
    },
    {"name": "Password reset", "description": "Getting a new password by e-mail."},
    {"name": "Tag categories", "description": "Kinds of tags."},
    {"name": "Tags", "description": "The words posts are found by."},
    {"name": "Posts", "description": "Uploaded files and everything about them."},
    {"name": "Pool categories", "description": "Kinds of pools."},
    {"name": "Pools", "description": "Ordered sets of posts."},
    {"name": "Comments", "description": "Comments under posts."},
    {"name": "Snapshots", "description": "The history of changes."},
    {
        "name": "Uploads",
        "description": "Files uploaded ahead of the request that uses them.",
    },
]

# The server is wherever the document is: the API's URLs are relative to a
# base path that depends on the deployment (/api/ behind the client image).
SERVERS = [{"url": "./", "description": "This server."}]


def build() -> dict[str, Any]:
    """The OpenAPI document, as the application describes itself."""
    # lithica.db builds an engine from the database setting when it is
    # imported. Describing the API connects to nothing, so a placeholder
    # will do where no database is configured (CI, a fresh checkout).
    if not config.config.get("database"):
        config.config["database"] = "postgresql://unused@localhost/unused"

    from lithica.app import app

    return app.openapi()


def allow_anonymous(document: dict[str, Any]) -> None:
    """
    Say that credentials are optional. FastAPI lists the ways to
    authenticate as alternatives, one of which would be required; `{}` adds
    "or none". Which requests an anonymous user may make is a matter of the
    server's privileges, not of the API.
    """
    for path in document["paths"].values():
        for operation in path.values():
            if "security" in operation:
                operation["security"] = [*operation["security"], {}]


def dump() -> str:
    """The document as it is committed: stable order, one trailing newline."""
    return json.dumps(build(), indent=2, ensure_ascii=False) + "\n"


if __name__ == "__main__":
    sys.stdout.write(dump())
