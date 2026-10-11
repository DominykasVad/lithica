from typing import Protocol

import sqlalchemy.orm as sa_orm

from lithica import errors, rest


class Versioned(Protocol):
    """Any model with a version column."""

    version: sa_orm.Mapped[int]


def verify_version(
    entity: Versioned,
    # the version the client edited; the old handlers pass their context and
    # the parameter is read from it (removed with the old framework)
    version: "int | rest.Context",
    field_name: str = "version",
) -> None:
    if isinstance(version, int):
        actual_version = version
    else:
        actual_version = version.get_param_as_int(field_name)
    expected_version = entity.version
    if actual_version != expected_version:
        raise errors.IntegrityError(
            "Someone else modified this in the meantime. " + "Please try again."
        )


def bump_version(entity: Versioned) -> None:
    entity.version = entity.version + 1
