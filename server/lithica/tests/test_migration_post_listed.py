"""The listed migration fills existing posts and downgrades cleanly."""

import sqlalchemy as sa
from alembic import command
from alembic.config import Config

from lithica.func import util
from lithica.tests.test_migration_token_hashes import migration_db  # noqa: F401  (pytest fixture registration)


def test_existing_posts(
    migration_db: tuple[sa.Engine, Config],  # noqa: F811 (pytest fixture injection)
) -> None:
    engine, settings = migration_db
    command.upgrade(settings, "b7c3d4e5f6a8")
    metadata = sa.MetaData()
    post = sa.Table("post", metadata, autoload_with=engine)
    with engine.begin() as connection:
        connection.execute(
            post.insert().values(
                creation_time=util.utcnow(),
                safety="safe",
                type="image",
                **{"mime-type": "image/png"},
                checksum="test",
                version=1,
                kind="media",
            )
        )
    command.upgrade(settings, "head")
    post = sa.Table("post", sa.MetaData(), autoload_with=engine)
    with engine.connect() as connection:
        assert connection.execute(sa.select(post.c.listed)).all() == [(True,)]
    column = next(
        c for c in sa.inspect(engine).get_columns("post") if c["name"] == "listed"
    )
    assert not column["nullable"]
    assert any(
        index["column_names"] == ["listed"]
        for index in sa.inspect(engine).get_indexes("post")
    )
    command.downgrade(settings, "b7c3d4e5f6a8")
    assert "listed" not in {c["name"] for c in sa.inspect(engine).get_columns("post")}
    command.upgrade(settings, "head")
