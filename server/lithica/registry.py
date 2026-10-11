"""
The modules of this installation.

A module is an optional feature layered on the engine: a package
`lithica.modules.<name>` that describes what it adds in a `Module` object
called `module`. The `modules` setting lists the ones to switch on. The
engine never imports a module by name; it asks this registry what the
loaded modules contribute.

The registry is filled once, when a process starts (the server, the admin
CLI), from the configuration, and does not change afterwards: it is
configuration, not state. Every server process loads the same modules.
"""

from __future__ import annotations

import argparse
import importlib
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, BinaryIO

from fastapi import APIRouter

from lithica import config, errors

if TYPE_CHECKING:
    from lithica import model
    from lithica.search.configs.base_search_config import Filter

# where modules live; the tests load theirs from another package
MODULE_PACKAGE = "lithica.modules"

# a module's name is part of URLs and of Python package names
NAME_PATTERN = re.compile(r"[a-z][a-z0-9_]*")

# a content kind is stored with every extracted row
KIND_PATTERN = re.compile(r"[a-z][a-z0-9_]*")
KIND_MAX_LENGTH = 64

# the admin CLI's own commands, which a module may not take
ENGINE_ADMIN_COMMANDS = frozenset({"backfill"})

# what is stored for one piece of extracted content: a JSON object
Payload = dict[str, Any]


@dataclass(frozen=True)
class ExtractedContent:
    """One thing an extractor found in a file."""

    kind: str
    payload: Payload


@dataclass(frozen=True)
class Extractor:
    """
    Reads content embedded in the files of some MIME types.

    `extract` is given the MIME type and the file, open for reading in
    binary mode, and returns what it found: nothing, or any number of
    results, each of a kind the module declares in `Module.content_kinds`.
    The file is somebody's upload: it is untrusted, and so is everything
    read from it. An extractor that raises is logged and skipped; it never
    fails the upload.
    """

    mime_types: frozenset[str]
    extract: Callable[[str, BinaryIO], Iterable[ExtractedContent]]


@dataclass(frozen=True)
class ContentKind:
    """
    A kind of extracted content, e.g. `dummy_v1`, and how it is shown.

    `schema_version` is stored with every row, so that a module that
    changes the shape of its payload can tell old rows from new ones.
    `private_fields` are keys of the payload that only users with the
    `posts:view:content:private` privilege are given. `serialize` turns the
    payload (already without the private fields, for users who may not see
    them) into what the API returns; without it the payload is returned as
    it is stored.
    """

    name: str
    schema_version: int = 1
    private_fields: frozenset[str] = frozenset()
    serialize: Callable[[Payload], Any] | None = None


@dataclass(frozen=True)
class AdminCommand:
    """
    A subcommand of `lithica-admin`. `configure` adds its arguments to the
    parser; `run` is given the parsed arguments, inside a database session
    scope, and returns the exit status.
    """

    name: str
    help: str
    run: Callable[[argparse.Namespace], int]
    configure: Callable[[argparse.ArgumentParser], None] | None = None


# extracted content of one post -> tag names to add, by tag category
AutoTag = Callable[[Sequence[ExtractedContent]], Mapping[str, Sequence[str]]]

# a field of the post resource: (post, requesting user) -> JSON value
PostField = Callable[["model.Post", "model.User"], Any]


@dataclass(frozen=True)
class Module:
    """
    What a module adds to the engine. Every part is optional.

    router          routes, served under `/modules/<name>/`
    content_kinds   the kinds of extracted content the module owns
    extractors      readers of content embedded in uploaded files
    auto_tag        tags to add to a post, from what was extracted
    search_filters  named tokens of the post search, e.g. `dummy-text:...`
    post_fields     extra fields of the post resource
    admin_commands  subcommands of `lithica-admin`
    """

    name: str
    router: APIRouter | None = None
    content_kinds: Sequence[ContentKind] = ()
    extractors: Sequence[Extractor] = ()
    auto_tag: AutoTag | None = None
    search_filters: Mapping[str, Filter] = field(default_factory=dict[str, "Filter"])
    post_fields: Mapping[str, PostField] = field(default_factory=dict[str, PostField])
    admin_commands: Sequence[AdminCommand] = ()


_modules: tuple[Module, ...] = ()


def _refuse(module: Module, problem: str) -> errors.ConfigError:
    return errors.ConfigError("Module %r %s" % (module.name, problem))


def _engine_search_filters() -> set[str]:
    # imported here: the search configuration asks this registry in turn
    from lithica.search.configs.post_search_config import PostSearchConfig

    return set(PostSearchConfig().engine_named_filters)


def _engine_post_fields() -> set[str]:
    # imported here: the post serializer asks this registry in turn
    from lithica.func import posts

    return posts.get_engine_post_field_names()


def _verify(modules: Sequence[Module]) -> None:
    """
    Refuse modules that could not work together or with the engine: two
    that claim the same name, and one that would replace something the
    engine has.
    """
    names: set[str] = set()
    kinds: set[str] = set()
    search_filters = _engine_search_filters()
    post_fields = _engine_post_fields()
    admin_commands = set(ENGINE_ADMIN_COMMANDS)
    for module in modules:
        if not NAME_PATTERN.fullmatch(module.name):
            raise _refuse(
                module, "has an invalid name: use lower case letters, digits and '_'."
            )
        if module.name in names:
            raise _refuse(module, "is listed twice.")
        names.add(module.name)

        for kind in module.content_kinds:
            if (
                not KIND_PATTERN.fullmatch(kind.name)
                or len(kind.name) > KIND_MAX_LENGTH
            ):
                raise _refuse(module, "has an invalid content kind %r." % kind.name)
            if kind.name in kinds:
                raise _refuse(
                    module, "declares the content kind %r a second time." % kind.name
                )
            kinds.add(kind.name)
        if module.extractors and not module.content_kinds:
            raise _refuse(module, "has extractors but declares no content kind.")

        for token in module.search_filters:
            if token in search_filters:
                raise _refuse(module, "adds the search token %r twice." % token)
            search_filters.add(token)
        for name in module.post_fields:
            if name in post_fields:
                raise _refuse(module, "adds the post field %r twice." % name)
            post_fields.add(name)
        for command in module.admin_commands:
            if command.name in admin_commands:
                raise _refuse(module, "adds the command %r twice." % command.name)
            admin_commands.add(command.name)


def _import(name: str, package: str) -> Module:
    if not isinstance(name, str) or not NAME_PATTERN.fullmatch(name):  # pyright: ignore[reportUnnecessaryIsInstance]  (it comes from a YAML file)
        raise errors.ConfigError(
            "%r is not a module name. Check the 'modules' setting." % (name,)
        )
    path = "%s.%s" % (package, name)
    try:
        imported = importlib.import_module(path)
    except ModuleNotFoundError as ex:
        if ex.name != path:
            # the module is there; something it imports is not
            raise
        raise errors.ConfigError(
            "Unknown module %r. Check the 'modules' setting." % name
        ) from ex
    module = getattr(imported, "module", None)
    if not isinstance(module, Module):
        raise errors.ConfigError(
            "%s does not describe itself: it has no 'module' object." % path
        )
    if module.name != name:
        raise errors.ConfigError("%s calls itself %r." % (path, module.name))
    return module


def use(modules: Sequence[Module]) -> None:
    """Make these the loaded modules. Raises ConfigError if they clash."""
    global _modules
    _verify(modules)
    _modules = tuple(modules)


def load(names: Sequence[str], package: str | None = None) -> None:
    """
    Import the named modules and make them the loaded ones. An unknown name
    is a configuration error: the process must not start without a feature
    the configuration asks for.
    """
    use([_import(name, package or MODULE_PACKAGE) for name in names])


def load_configured() -> None:
    """Load the modules the `modules` setting lists."""
    names = config.config.get("modules") or []
    if not isinstance(names, list):
        raise errors.ConfigError("'modules' must be a list of module names.")
    load(names)  # pyright: ignore[reportUnknownArgumentType]  (checked name by name)


def modules() -> tuple[Module, ...]:
    return _modules


def post_search_filters() -> dict[str, Filter]:
    return {
        token: search_filter
        for module in _modules
        for token, search_filter in module.search_filters.items()
    }


def post_fields() -> dict[str, PostField]:
    return {
        name: serialize
        for module in _modules
        for name, serialize in module.post_fields.items()
    }


def admin_commands() -> list[AdminCommand]:
    return [command for module in _modules for command in module.admin_commands]


def extractors_for(mime_type: str) -> list[tuple[Module, Extractor]]:
    """The extractors that read files of this MIME type, with their modules."""
    return [
        (module, extractor)
        for module in _modules
        for extractor in module.extractors
        if mime_type in extractor.mime_types
    ]


def content_kinds() -> dict[str, ContentKind]:
    """The content kinds the loaded modules own, by name."""
    return {kind.name: kind for module in _modules for kind in module.content_kinds}


def auto_taggers() -> list[tuple[Module, AutoTag]]:
    return [
        (module, module.auto_tag) for module in _modules if module.auto_tag is not None
    ]
