"""Share storage upgrades and downgrades without changing existing tables."""

import sqlalchemy as sa
from alembic import command
from alembic.config import Config

from lithica.tests.test_migration_token_hashes import migration_db  # noqa: F401 (pytest fixture)


def test_share_link_table(migration_db: tuple[sa.Engine, Config]) -> None:  # noqa: F811 (pytest fixture)
    engine, settings = migration_db
    command.upgrade(settings, "head")
    inspector = sa.inspect(engine)
    assert "share_link" in inspector.get_table_names()
    assert all(
        key.get("options", {}).get("ondelete") == "CASCADE"
        for key in inspector.get_foreign_keys("share_link")
    )
    assert {
        tuple(index["column_names"]) for index in inspector.get_indexes("share_link")
    } == {("post_id",), ("user_id",), ("token_hash",)}
    command.downgrade(settings, "c8d4e5f6a7b9")
    assert "share_link" not in sa.inspect(engine).get_table_names()
    command.upgrade(settings, "head")
