"""Former checksums have a unique key and cascade with their post."""

import sqlalchemy as sa
from alembic import command
from alembic.config import Config

from lithica.tests.test_migration_token_hashes import migration_db  # noqa: F401


def test_retired_schema(migration_db: tuple[sa.Engine, Config]) -> None:  # noqa: F811
    engine, settings = migration_db
    command.upgrade(settings, "head")
    inspector = sa.inspect(engine)
    assert inspector.get_pk_constraint("post_retired_checksum")[
        "constrained_columns"
    ] == ["checksum"]
    foreign = inspector.get_foreign_keys("post_retired_checksum")
    assert foreign[0]["referred_table"] == "post"
    assert foreign[0].get("options", {})["ondelete"] == "CASCADE"
    command.check(settings)
    command.downgrade(settings, "aa29ed2f410b")
    assert "post_retired_checksum" not in sa.inspect(engine).get_table_names()
    command.upgrade(settings, "head")
    command.check(settings)
