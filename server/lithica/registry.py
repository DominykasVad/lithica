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
import logging
import pkgutil
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, BinaryIO, cast

from fastapi import APIRouter
from fastapi.routing import APIRoute

from lithica import config, errors

if TYPE_CHECKING:
    from lithica import model
    from lithica.search.configs.base_search_config import Filter

logger = logging.getLogger(__name__)

# where modules live; the tests load theirs from another package
MODULE_PACKAGE = "lithica.modules"

# a module's name is part of URLs and of Python package names
NAME_PATTERN = re.compile(r"[a-z][a-z0-9_]*")

# a content kind is stored with every extracted row
KIND_PATTERN = re.compile(r"[a-z][a-z0-9_]*")
KIND_MAX_LENGTH = 64

# a post type is stored with every post, and is a value of the `type:` token
POST_TYPE_PATTERN = re.compile(r"[a-z][a-z0-9_]*")
POST_TYPE_MAX_LENGTH = 32

# the column `post."mime-type"` holds this many characters
MIME_TYPE_PATTERN = re.compile(r"[a-z0-9][a-z0-9.+-]*/[a-z0-9][a-z0-9.+-]*")
MIME_TYPE_MAX_LENGTH = 32

# a file extension is part of the names of the stored files and of their URLs
EXTENSION_PATTERN = re.compile(r"[a-z0-9]{1,16}")

# the admin CLI's own commands, which a module may not take
ENGINE_ADMIN_COMMANDS = frozenset({"backfill", "reextract"})

# what is stored for one piece of extracted content: a JSON object
Payload = dict[str, Any]

# How large one payload may be, as JSON: what a kind is allowed unless it
# asks for more, and what no kind may ask for more than. Embedded data is
# as large as the uploader made it, and a payload is held in memory whole.
DEFAULT_MAX_PAYLOAD_SIZE = 1024 * 1024
PAYLOAD_SIZE_CAP = 32 * 1024 * 1024


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

    The one exception is on purpose: an extractor that finds content of its
    kind which must not be dropped silently and cannot be stored (larger
    than the kind allows, say) raises `FileRejected`, and the upload is
    refused with its message.
    """

    mime_types: frozenset[str]
    extract: Callable[[str, BinaryIO], Iterable[ExtractedContent]]


class FileRejected(Exception):
    """
    Raised by a detector for a file that is of its type and must not be
    stored: the upload is refused, and the message is shown to the uploader.
    Say what is wrong and name the limit that was exceeded. A file that
    simply is not of the type is not rejected; the detector returns False.

    An extractor may raise it too, for content of its kind that cannot be
    stored and must not be lost without a word.
    """


@dataclass(frozen=True)
class FileType:
    """
    A type of file the engine does not know and a module does.

    `post_type` is the `type` of the posts made from such files, as the API
    shows it and the `type:` search token finds it. `mime_type` and
    `extension` (without the dot) are what the file is stored with.

    `detect` is given the first bytes of an upload and the file, open for
    reading in binary mode, and says whether it is of this type. It is
    asked only about files the engine itself does not know. The file is
    somebody's upload: untrusted. A detector that raises counts as "no";
    to refuse a file of the type, it raises `FileRejected`.

    `thumbnail` is given the stored file and returns a picture of it, in a
    format the engine reads (PNG, JPEG, ...), or None. Without a picture the
    post gets the engine's placeholder thumbnail and takes no part in the
    similar-image search; with one, the search works on the picture.

    The stored file is the upload, byte for byte.
    """

    post_type: str
    mime_type: str
    extension: str
    detect: Callable[[bytes, BinaryIO], bool]
    thumbnail: Callable[[BinaryIO], bytes | None] | None = None


@dataclass(frozen=True)
class ContentKind:
    """
    A kind of extracted content, e.g. `dummy_v1`, and how it is shown.

    `schema_version` is stored with every row, so that a module that
    changes the shape of its payload can tell old rows from new ones.

    `private_fields` are top-level keys of the payload that only users with
    the `posts:view:content:private` privilege are given. The engine takes
    them out before anything else sees the payload, `serialize` included.
    It guards the content endpoint only: a search token or a post field
    that a module builds on a private field is the module's to guard.

    `serialize` turns the payload into what the API returns; without it the
    payload is returned as it is stored.

    `max_payload_size` is how large one payload of the kind may be, in bytes
    of JSON. A kind whose content is larger by nature asks for more, up to
    `PAYLOAD_SIZE_CAP`.
    """

    name: str
    schema_version: int = 1
    max_payload_size: int = DEFAULT_MAX_PAYLOAD_SIZE
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

    router          routes, served under `/modules/<name>/` and tagged with
                    the module's name in the API document; they set no tags
                    of their own
    content_kinds   the kinds of extracted content the module owns
    file_types      types of files the engine does not know
    extractors      readers of content embedded in uploaded files
    auto_tag        tags to add to a post, from what was extracted
    search_filters  named tokens of the post search, e.g. `dummy-text:...`
    post_fields     extra fields of the post resource
    requested_post_fields
                    extra fields of the post resource that are returned only
                    when the request names them in `fields`: for what costs
                    a query, or is of no use to most clients
    admin_commands  subcommands of `lithica-admin`
    """

    name: str
    router: APIRouter | None = None
    content_kinds: Sequence[ContentKind] = ()
    file_types: Sequence[FileType] = ()
    extractors: Sequence[Extractor] = ()
    auto_tag: AutoTag | None = None
    search_filters: Mapping[str, Filter] = field(default_factory=dict[str, "Filter"])
    post_fields: Mapping[str, PostField] = field(default_factory=dict[str, PostField])
    requested_post_fields: Mapping[str, PostField] = field(
        default_factory=dict[str, PostField]
    )
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


def _engine_post_types() -> set[str]:
    # every value the `type:` token knows: the engine's types and their
    # other names. Imported here: the search configuration asks this
    # registry in turn.
    from lithica.search.configs.post_search_config import ENGINE_POST_TYPES

    return set(ENGINE_POST_TYPES)


def _is_engine_mime_type(mime_type: str) -> bool:
    from lithica.func import mime

    return mime.get_extension(mime_type) is not None or mime.is_video(mime_type)


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
    post_types = _engine_post_types()
    mime_types: set[str] = set()
    for module in modules:
        if not NAME_PATTERN.fullmatch(module.name):
            raise _refuse(
                module, "has an invalid name: use lower case letters, digits and '_'."
            )
        if module.name in names:
            raise _refuse(module, "is listed twice.")
        names.add(module.name)

        if module.router is not None:
            for route in module.router.routes:
                if isinstance(route, APIRoute) and route.tags:
                    raise _refuse(
                        module,
                        "tags its route %r: the routes of a module are tagged "
                        "with its name, and with nothing else." % route.path,
                    )

        for file_type in module.file_types:
            post_type = file_type.post_type
            if (
                not POST_TYPE_PATTERN.fullmatch(post_type)
                or len(post_type) > POST_TYPE_MAX_LENGTH
            ):
                raise _refuse(module, "has an invalid post type %r." % post_type)
            if post_type in post_types:
                raise _refuse(
                    module, "registers the post type %r a second time." % post_type
                )
            post_types.add(post_type)
            mime_type = file_type.mime_type
            if (
                not MIME_TYPE_PATTERN.fullmatch(mime_type)
                or len(mime_type) > MIME_TYPE_MAX_LENGTH
            ):
                raise _refuse(
                    module,
                    "has an invalid MIME type %r: lower case, and at most %d "
                    "characters." % (mime_type, MIME_TYPE_MAX_LENGTH),
                )
            if mime_type in mime_types or _is_engine_mime_type(mime_type):
                raise _refuse(
                    module, "registers the MIME type %r a second time." % mime_type
                )
            mime_types.add(mime_type)
            if not EXTENSION_PATTERN.fullmatch(file_type.extension):
                raise _refuse(
                    module,
                    "has an invalid file extension %r: lower case letters and "
                    "digits, without the dot." % file_type.extension,
                )

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
            if not 0 < kind.max_payload_size <= PAYLOAD_SIZE_CAP:
                raise _refuse(
                    module,
                    "asks for payloads of %d bytes for the content kind %r: the "
                    "most a kind may ask for is %d."
                    % (kind.max_payload_size, kind.name, PAYLOAD_SIZE_CAP),
                )
            kinds.add(kind.name)
        if module.extractors and not module.content_kinds:
            raise _refuse(module, "has extractors but declares no content kind.")

        for token in module.search_filters:
            if token in search_filters:
                raise _refuse(module, "adds the search token %r twice." % token)
            search_filters.add(token)
        for name in [*module.post_fields, *module.requested_post_fields]:
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


def available() -> list[Module]:
    """
    Every module there is, switched on or not, in the order of their names.
    It does not change which modules are loaded. For what describes the
    code rather than one installation: the API contract.
    """
    package = importlib.import_module(MODULE_PACKAGE)
    names = sorted(
        info.name for info in pkgutil.iter_modules(package.__path__) if info.ispkg
    )
    found = [_import(name, MODULE_PACKAGE) for name in names]
    _verify(found)
    return found


# MIME type -> extension for the file types of every module there is, and
# the package they were read from. Filled on first use and kept: it is a
# fact about the code, the same in every process, and does not change
# while one runs.
_stored_extensions: tuple[str, dict[str, str]] | None = None


def forget_available() -> None:
    """Forget what was learnt about the modules there are (for the tests)."""
    global _stored_extensions
    _stored_extensions = None


def stored_extension(mime_type: str) -> str | None:
    """
    The extension the files of a module's MIME type are stored with, or None
    if no module there is knows the type. It asks every module in the code
    base, switched on or not: where a stored file is must not depend on the
    settings, or a post of a module that was switched off could not be
    found, served or deleted with its file.
    """
    global _stored_extensions
    if _stored_extensions is None or _stored_extensions[0] != MODULE_PACKAGE:
        extensions: dict[str, str] = {}
        try:
            for module in available():
                for file_type in module.file_types:
                    extensions[file_type.mime_type] = file_type.extension
        except Exception:
            # A module that is switched off and does not even import must
            # not take every request down. What it would have said is
            # missing; the loaded modules are asked below all the same.
            logger.exception(
                "Could not read the file types of the modules in %s.", MODULE_PACKAGE
            )
        _stored_extensions = (MODULE_PACKAGE, extensions)
    extension = _stored_extensions[1].get(mime_type)
    if extension is None:
        # a module that was handed to use() directly, not from the package
        file_type = file_type_for(mime_type)
        extension = file_type.extension if file_type else None
    return extension


def load_configured() -> None:
    """Load the modules the `modules` setting lists."""
    # an object: the setting is whatever the YAML file holds
    names: object = config.config.get("modules") or []
    if not isinstance(names, list):
        raise errors.ConfigError("'modules' must be a list of module names.")
    # each name is checked when it is imported
    load(cast(list[str], names))


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


def requested_post_fields() -> dict[str, PostField]:
    """The post fields of the loaded modules that a request must ask for."""
    return {
        name: serialize
        for module in _modules
        for name, serialize in module.requested_post_fields.items()
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


def file_types() -> list[tuple[Module, FileType]]:
    """The file types of the loaded modules, with their modules."""
    return [
        (module, file_type) for module in _modules for file_type in module.file_types
    ]


def file_type_for(mime_type: str) -> FileType | None:
    """The file type of a loaded module that is stored with this MIME type."""
    for module in _modules:
        for file_type in module.file_types:
            if file_type.mime_type == mime_type:
                return file_type
    return None


def content_kinds() -> dict[str, ContentKind]:
    """The content kinds the loaded modules own, by name."""
    return {kind.name: kind for module in _modules for kind in module.content_kinds}


def auto_taggers() -> list[tuple[Module, AutoTag]]:
    return [
        (module, module.auto_tag) for module in _modules if module.auto_tag is not None
    ]
