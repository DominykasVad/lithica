"""
The OpenAPI document of the API: the contract clients are written against.

    python -m lithica.openapi > ../doc/openapi.json

prints it. The committed doc/openapi.json must be what this prints; CI
checks that. Never edit that file by hand.
"""

import json
import sys
from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel, TypeAdapter

from lithica import config, registry

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

    from lithica.app import create_app

    # The contract describes the code, not this installation: every module
    # there is, whatever the `modules` setting says, so that the document
    # is the same on every machine.
    return create_app(modules=registry.available()).openapi()


def module_tags(modules: Sequence[registry.Module]) -> list[dict[str, str]]:
    """The tags of the modules that have routes: one each, its name."""
    return [
        {
            "name": module.name,
            "description": "Routes of the optional module `%s`, under "
            "`modules/%s/`. They exist only where the module is switched on: "
            "see `modules` of `GET /info`." % (module.name, module.name),
        }
        for module in modules
        if module.router is not None
    ]


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


def _value_schema(value_type: Any, schemas: dict[str, Any], where: str) -> Any:
    """
    The JSON schema of a module's post field value. A model becomes a
    component of its own, as the engine's are, and is referred to.
    """
    schema = TypeAdapter(value_type).json_schema(
        by_alias=True,
        mode="serialization",
        ref_template="#/components/schemas/{model}",
    )
    found: dict[str, Any] = schema.pop("$defs", {})
    if isinstance(value_type, type) and issubclass(value_type, BaseModel):
        found[value_type.__name__] = schema
        schema = {"$ref": "#/components/schemas/%s" % value_type.__name__}
    for name, component in found.items():
        if schemas.setdefault(name, component) != component:
            raise ValueError("%s: the schema %r is already another one" % (where, name))
    return schema


def add_module_post_fields(
    document: dict[str, Any], modules: Sequence[registry.Module]
) -> None:
    """
    Describe the fields modules add to the post resource, as the routes of
    every module are described: they are part of what a client can be given.
    """
    schemas: dict[str, Any] = document["components"]["schemas"]
    properties: dict[str, Any] = schemas["Post"]["properties"]
    for module in modules:
        requested = list(module.requested_post_fields)
        for name in [*module.post_fields, *requested]:
            when = "only when the module is enabled"
            if name in requested:
                when = "only when asked for in `fields`, and " + when
            description = (
                "Added by the module `%s`; returned %s (see `modules` of "
                "`GET /info`); it may be `null`." % (module.name, when)
            )
            if name in module.post_field_schemas:
                value = _value_schema(
                    module.post_field_schemas[name], schemas, "post field %r" % name
                )
                properties[name] = {
                    "anyOf": [value, {"type": "null"}],
                    "description": description,
                }
            else:
                properties[name] = {"description": description}


def dump() -> str:
    """The document as it is committed: stable order, one trailing newline."""
    return json.dumps(build(), indent=2, ensure_ascii=False) + "\n"


if __name__ == "__main__":
    sys.stdout.write(dump())
