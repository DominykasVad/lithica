from typing import Protocol

import sqlalchemy.orm as sa_orm

from lithica import errors, rest


class Versioned(Protocol):
    """Any model with a version column."""

    version: sa_orm.Mapped[int]


def verify_version(
    entity: Versioned, context: rest.Context, field_name: str = "version"
) -> None:
    actual_version = context.get_param_as_int(field_name)
    expected_version = entity.version
    if actual_version != expected_version:
        raise errors.IntegrityError(
            "Someone else modified this in the meantime. " + "Please try again."
        )


def bump_version(entity: Versioned) -> None:
    entity.version = entity.version + 1
