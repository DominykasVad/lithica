"""Typed relation and external-ID tables upgrade and downgrade."""

import pytest
import sqlalchemy as sa
from alembic import command
from sqlalchemy.exc import IntegrityError

from lithica.func import util
from lithica.tests.test_migration_token_hashes import migration_db  # noqa: F401  (pytest fixture registration)


def test_post_metadata_tables(migration_db):  # noqa: F811  (pytest fixture injection)
    engine, settings = migration_db
    command.upgrade(settings, "head")
    inspector = sa.inspect(engine)
    assert "post_typed_relation" in inspector.get_table_names()
    assert "post_external_id" in inspector.get_table_names()
    assert inspector.get_check_constraints("post_typed_relation")
    assert {
        tuple(index["column_names"])
        for index in inspector.get_indexes("post_typed_relation")
        if not index.get("duplicates_constraint")
    } == {("from_post_id", "type"), ("to_post_id", "type")}
    assert inspector.get_pk_constraint("post_external_id")["constrained_columns"] == [
        "host",
        "external_id",
    ]
    for table in ("post_typed_relation", "post_external_id"):
        foreign_keys = inspector.get_foreign_keys(table)
        assert all(
            key["options"]["ondelete"]
            == ("SET NULL" if key["referred_table"] == "user" else "CASCADE")
            for key in foreign_keys
        )
    metadata = sa.MetaData()
    post = sa.Table("post", metadata, autoload_with=engine)
    typed_relation = sa.Table("post_typed_relation", metadata, autoload_with=engine)
    with engine.begin() as connection:
        post_id = connection.execute(
            post.insert()
            .values(
                creation_time=util.utcnow(),
                safety="safe",
                type="image",
                checksum="constraint-test",
                version=1,
                kind="media",
                **{"mime-type": "image/png"},
            )
            .returning(post.c.id)
        ).scalar_one()
        with pytest.raises(
            IntegrityError, match="ck_post_typed_relation_distinct_ends"
        ):
            with connection.begin_nested():
                connection.execute(
                    typed_relation.insert().values(
                        from_post_id=post_id,
                        to_post_id=post_id,
                        type="gallery-of",
                        creation_time=util.utcnow(),
                    )
                )
    command.downgrade(settings, "a6b2c3d4e5f6")
    assert "post_typed_relation" not in sa.inspect(engine).get_table_names()
    assert "post_external_id" not in sa.inspect(engine).get_table_names()
    command.upgrade(settings, "head")
