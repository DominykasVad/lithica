"""Alembic preserves loggers already used by its calling process."""

import logging

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config

from lithica.tests.test_migration_token_hashes import migration_db  # noqa: F401 (pytest fixture)


def test_existing_logger_survives_migration(
    migration_db: tuple[sa.Engine, Config],  # noqa: F811 (pytest fixture)
    caplog: pytest.LogCaptureFixture,
) -> None:
    logger = logging.getLogger("lithica.func.post_content")
    assert not logger.disabled
    _, settings = migration_db

    command.upgrade(settings, "head")

    assert not logger.disabled
    # Alembic replaces the root handlers, so capture on the logger directly.
    logger.addHandler(caplog.handler)
    try:
        with caplog.at_level(logging.WARNING, logger=logger.name):
            logger.warning("Logging still works after migration")
    finally:
        logger.removeHandler(caplog.handler)
    assert (
        logger.name,
        logging.WARNING,
        "Logging still works after migration",
    ) in caplog.record_tuples
