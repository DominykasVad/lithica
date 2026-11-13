"""Nullable card data projections expand and roll back without rewriting data."""

import sqlalchemy as sa
from alembic import command
from alembic.config import Config

from lithica.tests.test_migration_token_hashes import migration_db  # noqa: F401


def test_card_data_hash(migration_db: tuple[sa.Engine, Config]) -> None:  # noqa: F811
    engine, settings = migration_db
    command.upgrade(settings, "d72a01c42e90")
    columns = {c["name"]: c for c in sa.inspect(engine).get_columns("cards_card")}
    assert columns["data_hash"]["nullable"]
    command.downgrade(settings, "c8d14a2f590e")
    assert "data_hash" not in {
        c["name"] for c in sa.inspect(engine).get_columns("cards_card")
    }
    command.upgrade(settings, "head")
    command.check(settings)
