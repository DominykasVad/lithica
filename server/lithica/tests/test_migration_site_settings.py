import sqlalchemy as sa
from alembic import command
from alembic.config import Config

from lithica.tests.test_migration_token_hashes import migration_db  # noqa: F401 (pytest fixture)


def test_settings_migration(migration_db: tuple[sa.Engine, Config]) -> None:  # noqa: F811 (pytest fixture)
    engine, settings = migration_db
    command.upgrade(settings, "head")
    inspector = sa.inspect(engine)
    assert {"site_setting", "site_settings_version"} <= set(inspector.get_table_names())
    assert (
        inspector.get_foreign_keys("site_setting")[0].get("options", {}).get("ondelete")
        == "SET NULL"
    )
    metadata = sa.MetaData()
    versions = sa.Table("site_settings_version", metadata, autoload_with=engine)
    with engine.connect() as connection:
        assert connection.execute(
            sa.select(versions.c.id, versions.c.version)
        ).all() == [(1, 1)]
    command.downgrade(settings, "d9e5f6a7b8c0")
    assert "site_setting" not in sa.inspect(engine).get_table_names()
    assert "site_settings_version" not in sa.inspect(engine).get_table_names()
    command.upgrade(settings, "head")
