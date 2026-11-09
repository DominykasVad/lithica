"""The post-kind migration fills existing posts and downgrades cleanly."""

import sqlalchemy as sa
from alembic import command

from lithica.func import util
from lithica.tests.test_migration_token_hashes import migration_db  # noqa: F401  (pytest fixture registration)


def test_existing_posts(migration_db):  # noqa: F811  (pytest fixture injection)
    engine, settings = migration_db
    command.upgrade(settings, "f3a9c1d27b64")
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
            )
        )
    command.upgrade(settings, "head")
    post = sa.Table("post", sa.MetaData(), autoload_with=engine)
    with engine.connect() as connection:
        assert connection.execute(sa.select(post.c.kind)).all() == [("media",)]
    column = next(
        c for c in sa.inspect(engine).get_columns("post") if c["name"] == "kind"
    )
    assert not column["nullable"]
    assert column["type"].length == 32
    assert any(
        index["column_names"] == ["kind"]
        for index in sa.inspect(engine).get_indexes("post")
    )
    command.downgrade(settings, "f3a9c1d27b64")
    assert "kind" not in {c["name"] for c in sa.inspect(engine).get_columns("post")}
    command.upgrade(settings, "head")
