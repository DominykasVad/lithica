"""Existing cards remain intact across image-map expansion and rollback."""

import sqlalchemy as sa
from alembic import command
from alembic.config import Config

from lithica.func import util
from lithica.tests.test_migration_token_hashes import migration_db  # noqa: F401


def test_card_images_migration(migration_db: tuple[sa.Engine, Config]) -> None:  # noqa: F811
    engine, settings = migration_db
    command.upgrade(settings, "e72a01c42e90")
    metadata = sa.MetaData()
    post = sa.Table("post", metadata, autoload_with=engine)
    card = sa.Table("cards_card", metadata, autoload_with=engine)
    with engine.begin() as connection:
        post_id = connection.execute(
            post.insert()
            .values(
                creation_time=util.utcnow(),
                safety="safe",
                version=1,
                kind="card",
                listed=True,
            )
            .returning(post.c.id)
        ).scalar_one()
        connection.execute(
            card.insert().values(
                post_id=post_id,
                spec="chara_card_v3",
                name="Existing",
                creator="",
                greetings=1,
                data_hash="unchanged",
            )
        )
    command.upgrade(settings, "head")
    card = sa.Table("cards_card", sa.MetaData(), autoload_with=engine)
    with engine.connect() as connection:
        assert connection.execute(
            sa.select(card.c.name, card.c.data_hash, card.c.images_read)
        ).one() == ("Existing", "unchanged", False)
    image = sa.Table("cards_card_image", sa.MetaData(), autoload_with=engine)
    assert image.c.label.nullable
    assert (
        isinstance(image.c.label.type, sa.String) and image.c.label.type.length == 128
    )
    assert not image.c.position.nullable
    assert {c.name for c in image.primary_key} == {"card_post_id", "uri"}
    assert all(fk.ondelete == "CASCADE" for fk in image.foreign_keys)
    command.check(settings)
    command.downgrade(settings, "e72a01c42e90")
    assert "cards_card_image" not in sa.inspect(engine).get_table_names()
    card = sa.Table("cards_card", sa.MetaData(), autoload_with=engine)
    assert "images_read" not in card.c
    with engine.connect() as connection:
        assert connection.execute(sa.select(card.c.name, card.c.data_hash)).one() == (
            "Existing",
            "unchanged",
        )
    command.upgrade(settings, "head")
    command.check(settings)
