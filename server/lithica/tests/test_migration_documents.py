"""Document tables upgrade and downgrade independently of file-less posts."""

import sqlalchemy as sa
from alembic import command
from alembic.config import Config

from lithica.tests.test_migration_token_hashes import migration_db  # noqa: F401


def test_document_tables(migration_db: tuple[sa.Engine, Config]) -> None:  # noqa: F811
    engine, settings = migration_db
    command.upgrade(settings, "head")
    names = {"post_document", "post_document_version"}
    assert names <= set(sa.inspect(engine).get_table_names())
    command.check(settings)
    command.downgrade(settings, "a3b8c9d0e1f2")
    assert not names & set(sa.inspect(engine).get_table_names())
    command.upgrade(settings, "head")
    command.check(settings)
