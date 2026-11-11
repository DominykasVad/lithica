"""Module state shares the engine's schema lifecycle, never its behavior."""

from collections.abc import Callable

import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.orm import Session

from lithica import model, registry
from lithica.tests.fixtures.modules.dummy.model import DummyText
from lithica.tests.test_migration_token_hashes import migration_db  # noqa: F401


def test_dummy_table(session: Session, post_factory: Callable[[], model.Post]) -> None:
    assert not registry.modules()
    post = post_factory()
    session.add(post)
    session.flush()
    session.add(DummyText(post_id=post.post_id, text="module state"))
    session.flush()
    assert session.scalar(sa.select(DummyText.text)) == "module state"
    session.delete(post)
    session.flush()
    assert session.scalar(sa.select(sa.func.count()).select_from(DummyText)) == 0


def test_module_migrations(
    migration_db: tuple[sa.Engine, Config],  # noqa: F811
) -> None:
    engine, settings = migration_db
    registry.import_models()
    expected = {
        table.name
        for table in model.Base.metadata.tables.values()
        if any(
            table.name.startswith(module.name + "_") for module in registry.available()
        )
    }
    command.upgrade(settings, "head")
    assert expected <= set(sa.inspect(engine).get_table_names())
    # Module tables start after v0.4.0; exercise that boundary, not upstream's
    # historical downgrades (which use application models from their time).
    command.downgrade(settings, "f2a7b8c9d0e1")
    assert not expected & set(sa.inspect(engine).get_table_names())
