from typing import Protocol

import sqlalchemy.orm as sa_orm

from lithica import errors


class Versioned(Protocol):
    """Any model with a version column."""

    version: sa_orm.Mapped[int]


def verify_version(entity: Versioned, version: int) -> None:
    """
    Refuse an edit that was made from an older version of the resource than
    the current one: `version` is the version the client edited.
    """
    if version != entity.version:
        raise errors.IntegrityError(
            "Someone else modified this in the meantime. " + "Please try again."
        )


def bump_version(entity: Versioned) -> None:
    entity.version = entity.version + 1
