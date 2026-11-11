"""
Migration f3a9c1d27b64: login tokens are stored as hashes. A token made
before it still works after it; no value is left in the table; downgrade
then upgrade runs.
"""

import logging
import os
import uuid
from datetime import datetime

import pytest
import sqlalchemy as sa
import sqlalchemy.orm as sa_orm
from alembic import command
from alembic.config import Config

from lithica import config, db, model
from lithica.api import dependencies
from lithica.func import auth
from lithica.tests.fixtures.modules.dummy.model import DummyText

BEFORE = "e2b8d4f6a1c3"
REVISION = "f3a9c1d27b64"
SERVER_DIR = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))

_users = sa.table(
    "user",
    sa.column("id", sa.Integer),
    sa.column("name", sa.Unicode),
    sa.column("password_hash", sa.Unicode),
    sa.column("rank", sa.Unicode),
    sa.column("creation_time", sa.DateTime),
    sa.column("version", sa.Integer),
    sa.column("password_revision", sa.SmallInteger),
    sa.column("avatar_style", sa.Unicode),
)
_old_tokens = sa.table(
    "user_token",
    sa.column("user_id", sa.Integer),
    sa.column("token", sa.Unicode),
    sa.column("enabled", sa.Boolean),
    sa.column("creation_time", sa.DateTime),
    sa.column("version", sa.Integer),
)


@pytest.fixture
def migration_db(worker_id, _pg_database_url, tmp_path, monkeypatch):
    """An empty database of its own, and alembic pointed at it."""
    # The dummy table belongs to fixture-created schemas only. Alembic's
    # metadata must describe shipped tables, just as in a production process.
    metadata = sa.MetaData()
    for table in model.Base.metadata.sorted_tables:
        if table is not DummyText.__table__:
            table.to_metadata(metadata)
    monkeypatch.setattr(model.Base, "metadata", metadata)
    name = "test_migration_%s" % worker_id
    admin = sa.create_engine(_pg_database_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(sa.DDL("DROP DATABASE IF EXISTS %s" % name))
        conn.execute(sa.DDL("CREATE DATABASE %s" % name))
    url = _pg_database_url.set(database=name)
    original = {key: config.config.get(key) for key in ("database", "data_dir")}
    config.config["database"] = url.render_as_string(hide_password=False)
    # older migrations look at the data directory (02ef5f73f4ab renames
    # stored files): an empty one of the test's own, whatever the machine has
    config.config["data_dir"] = str(tmp_path)
    alembic_config = Config(os.path.join(SERVER_DIR, "alembic.ini"))
    alembic_config.set_main_option(
        "script_location", os.path.join(SERVER_DIR, "lithica", "migrations")
    )
    engine = sa.create_engine(url)
    # alembic's env.py configures logging from alembic.ini, which switches
    # off every logger that exists: the other tests of this process need them
    root = logging.getLogger()
    root_state = (root.level, list(root.handlers))
    loggers = {
        logger_name: (one.disabled, one.level)
        for logger_name, one in logging.Logger.manager.loggerDict.items()
        if isinstance(one, logging.Logger)
    }
    try:
        yield engine, alembic_config
    finally:
        root.setLevel(root_state[0])
        root.handlers[:] = root_state[1]
        for logger_name, (disabled, level) in loggers.items():
            one = logging.getLogger(logger_name)
            one.disabled = disabled
            one.setLevel(level)
        engine.dispose()
        for key, value in original.items():
            if value is None:
                config.config.pop(key, None)
            else:
                config.config[key] = value
        with admin.connect() as conn:
            conn.execute(sa.DDL("DROP DATABASE IF EXISTS %s" % name))
        admin.dispose()


def test_tokens_survive_the_migration(migration_db):
    engine, alembic_config = migration_db
    command.upgrade(alembic_config, BEFORE)
    value = str(uuid.uuid4())
    with engine.begin() as conn:
        user_id = conn.execute(
            sa.insert(_users)
            .values(
                name="u1",
                password_hash="x",
                rank="regular",
                creation_time=datetime(1997, 1, 1),
                version=1,
                password_revision=0,
                avatar_style="gravatar",
            )
            .returning(_users.c.id)
        ).scalar_one()
        conn.execute(
            sa.insert(_old_tokens),
            [
                {
                    "user_id": user_id,
                    "token": token,
                    "enabled": True,
                    "creation_time": datetime(1997, 1, 1),
                    "version": 1,
                }
                for token in [value, str(uuid.uuid4())]
            ],
        )

    command.upgrade(alembic_config, REVISION)

    columns = {
        column["name"] for column in sa.inspect(engine).get_columns("user_token")
    }
    assert "token" not in columns
    with engine.connect() as conn:
        rows = conn.execute(
            sa.select(sa.column("token_hash"), sa.column("kind")).select_from(
                sa.table("user_token")
            )
        ).all()
    assert len(rows) == 2
    assert all(kind == "login" for _, kind in rows)
    assert auth.hash_token(value) in {token_hash for token_hash, _ in rows}
    assert value not in {token_hash for token_hash, _ in rows}

    # the old value still authenticates, through the server's own lookup
    test_session = db.session
    session = sa_orm.Session(engine)
    db.session = session
    try:
        user, token = dependencies._authenticate_token("u1", value)
        assert user.name == "u1"
        assert token.kind == "login"
    finally:
        session.close()
        db.session = test_session

    command.downgrade(alembic_config, BEFORE)
    with engine.connect() as conn:
        count = conn.execute(
            sa.select(sa.func.count()).select_from(sa.table("user_token"))
        ).scalar_one()
    assert count == 0
    command.upgrade(alembic_config, "head")
