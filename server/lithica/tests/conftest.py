import contextlib
import json
import os
import random
import string
import sys
import textwrap
from datetime import datetime
from typing import Any
from unittest.mock import Mock, patch

import freezegun
import pytest
import sqlalchemy as sa
import sqlalchemy.orm as sa_orm

from lithica import config

_DEFAULT_DATABASE_URL = "postgresql://postgres:postgres@localhost:5433/postgres"

# lithica.db builds its engine at import time from the config. Outside a
# container the config has no database URL, so give it one before importing.
# Tests never use that engine; they swap db.session for their own session.
config.config.setdefault(
    "database",
    os.environ.get("LITHICA_TEST_DATABASE_URL", _DEFAULT_DATABASE_URL),
)

import httpx2  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from lithica import db, model, registry  # noqa: E402
from lithica.api import dependencies, responses  # noqa: E402
from lithica.app import app as lithica_app  # noqa: E402
from lithica.func import visibility  # noqa: E402


@pytest.fixture(scope="session")
def _pg_database_url(worker_id):
    """Create a database for this xdist worker and drop it at session end.

    The server comes from LITHICA_TEST_DATABASE_URL (see
    docker-compose.test.yml); the database named in that URL is only used to
    issue CREATE / DROP DATABASE.
    """
    admin_url = sa.make_url(
        os.environ.get("LITHICA_TEST_DATABASE_URL", _DEFAULT_DATABASE_URL)
    )
    name = "test_%s" % worker_id
    admin_engine = sa.create_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        with admin_engine.connect() as conn:
            conn.execute(sa.DDL("DROP DATABASE IF EXISTS %s" % name))
            conn.execute(sa.DDL("CREATE DATABASE %s" % name))
        yield admin_url.set(database=name)
        with admin_engine.connect() as conn:
            conn.execute(sa.DDL("DROP DATABASE IF EXISTS %s" % name))
    finally:
        admin_engine.dispose()


@pytest.fixture(scope="session")
def _pg_engine(_pg_database_url):
    engine = sa.create_engine(
        _pg_database_url, connect_args={"options": "-c timezone=UTC"}
    )
    yield engine
    engine.dispose()


# the scoped session lithica.db builds; the session fixtures put their own
# session in its place
REAL_DB_SESSION = db.session


class _TestSession(sa_orm.Session):
    """
    The session the tests put in place of lithica.db.session. The engine
    code treats that object as a scoped session: it calls it to get the
    session and calls remove() when a unit of work ends. A test's session
    outlives the units of work it is used for, so both do nothing here.
    """

    def __call__(self) -> "_TestSession":
        return self

    def remove(self) -> None:
        pass


class _TransactedTestDB:
    """Test DB fixture that rolls back the entire transaction on reset_db().

    DDL (CREATE TABLE) and DML both live inside an outer connection-level
    transaction.  session.commit() only releases a SAVEPOINT; the outer
    transaction is never committed, so trans.rollback() undoes everything.
    """

    def __init__(self, connection, session, transaction):
        self._connection = connection
        self._transaction = transaction
        self.session = session

    def create_table(self, *tables):
        for table in tables:
            table.create(bind=self._connection, checkfirst=True)

    def reset_db(self):
        self.session.close()
        if self._transaction.is_active:
            self._transaction.rollback()


class _CommittingTestDB:
    """Test DB fixture for tests that need real commits.

    reset_db() drops and recreates the public schema.
    """

    def __init__(self, session, engine):
        self.session = session
        self._engine = engine

    def create_table(self, *tables):
        with self._engine.begin() as conn:
            for table in tables:
                table.create(bind=conn, checkfirst=True)

    def reset_db(self):
        self.session.close()
        with self._engine.connect() as conn:
            conn.execute(sa.schema.DropSchema("public", cascade=True))
            conn.execute(sa.schema.CreateSchema("public"))
            conn.commit()


@pytest.fixture
def transacted_postgresql_db(_pg_engine):
    """Database fixture; the name is kept from pytest_pgsql, which it replaced."""
    conn = _pg_engine.connect()
    trans = conn.begin()
    # The session works in savepoints of the outer transaction: commit()
    # releases one and rollback() rolls one back, so neither touches the
    # tables the test created, and the outer rollback still undoes it all.
    session = _TestSession(bind=conn, join_transaction_mode="create_savepoint")

    try:
        yield _TransactedTestDB(conn, session, trans)
    finally:
        session.close()
        if trans.is_active:
            trans.rollback()
        conn.close()


@pytest.fixture
def postgresql_db(_pg_engine):
    """Database fixture; the name is kept from pytest_pgsql, which it replaced."""
    session = _TestSession(_pg_engine)
    try:
        yield _CommittingTestDB(session, _pg_engine)
    finally:
        session.close()
        with _pg_engine.connect() as conn:
            conn.execute(sa.schema.DropSchema("public", cascade=True))
            conn.execute(sa.schema.CreateSchema("public"))
            conn.commit()


def get_unique_name():
    alphabet = string.ascii_letters + string.digits
    return "".join(random.choice(alphabet) for _ in range(8))


@pytest.fixture
def fake_datetime():
    @contextlib.contextmanager
    def injector(now):
        freezer = freezegun.freeze_time(now)
        freezer.start()
        yield
        freezer.stop()

    return injector


@pytest.fixture(scope="session")
def query_logger(pytestconfig):
    if pytestconfig.option.verbose > 0:
        import logging

        import coloredlogs

        coloredlogs.install(fmt="[%(asctime)-15s] %(name)s %(message)s", isatty=True)
        logging.basicConfig()
        logging.getLogger("sqlalchemy.engine").setLevel(logging.INFO)


@pytest.fixture(scope="function", autouse=True)
def session(query_logger, transacted_postgresql_db):
    db.session = transacted_postgresql_db.session
    transacted_postgresql_db.create_table(*model.Base.metadata.sorted_tables)
    try:
        yield transacted_postgresql_db.session
    finally:
        transacted_postgresql_db.reset_db()


@pytest.fixture(scope="function")
def nontransacted_session(query_logger, postgresql_db):
    old_db_session = db.session
    db.session = postgresql_db.session
    postgresql_db.create_table(*model.Base.metadata.sorted_tables)
    try:
        yield postgresql_db.session
    finally:
        postgresql_db.reset_db()
        db.session = old_db_session


@pytest.fixture
def committing_session(transacted_postgresql_db, postgresql_db, _pg_engine):
    """
    Each request with a session of its own, as the server runs, on tables
    whose rows are committed: what one request commits another sees. For
    tests of requests that run at the same time. The test's own transaction
    is given up first; its uncommitted tables would hold up the ones made
    here.
    """
    transacted_postgresql_db.reset_db()
    postgresql_db.create_table(*model.Base.metadata.sorted_tables)
    test_session = db.session
    # the server's scoped session, on the test database
    db.session = sa_orm.scoped_session(
        sa_orm.sessionmaker(_pg_engine, autoflush=False),
        scopefunc=db._current_scope,
    )
    try:
        yield
    finally:
        db.session = test_session


@pytest.fixture
def scoped_db_session(session):
    """Put the real, scope-bound lithica.db.session back for one test."""
    db.session = REAL_DB_SESSION
    yield REAL_DB_SESSION
    db.session = session


_serialize_default = responses._serialize_default


def _serialize_with_mocks(obj: Any) -> str:
    """
    Many tests replace a serializer with a mock and do not care what the
    endpoint returns. A mock in a response is written as text instead of
    failing the request.
    """
    if isinstance(obj, Mock):
        return repr(obj)
    return _serialize_default(obj)


def _as_user(user: model.User) -> model.User:
    """What authenticating does besides finding the user (dependencies.get_user)."""
    visibility.set_viewer(user)
    return user


class ApiClient:
    """
    Calls the API over HTTP, in the application's own process.

    `user` is who the request comes from: authentication is replaced by that
    user, so a test does not need passwords. Without it the request is
    anonymous. `query` is the query string; `body` is sent as JSON, or as the
    `metadata` part of a multipart request when `files` are given.
    """

    def __init__(self, application: FastAPI = lithica_app) -> None:
        self._app = application
        # not used as a context manager: the startup work does not run
        self._client = TestClient(application, headers={"Accept": "application/json"})

    def request(
        self,
        method: str,
        path: str,
        *,
        user: model.User | None = None,
        query: dict[str, Any] | None = None,
        body: Any = None,
        files: dict[str, bytes] | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx2.Response:
        kwargs: dict[str, Any] = {"params": query, "headers": headers}
        if files:
            kwargs["files"] = {
                name: (name, content, "application/octet-stream")
                for name, content in files.items()
            }
            if body is not None:
                kwargs["data"] = {"metadata": json.dumps(body)}
        elif body is not None:
            kwargs["json"] = body
        overrides = self._app.dependency_overrides
        if user is not None:
            overrides[dependencies.get_user] = lambda: _as_user(user)
        try:
            with patch.object(responses, "_serialize_default", _serialize_with_mocks):
                return self._client.request(method, path, **kwargs)
        finally:
            overrides.pop(dependencies.get_user, None)

    def get(self, path: str, **kwargs: Any) -> httpx2.Response:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs: Any) -> httpx2.Response:
        return self.request("POST", path, **kwargs)

    def put(self, path: str, **kwargs: Any) -> httpx2.Response:
        return self.request("PUT", path, **kwargs)

    def delete(self, path: str, **kwargs: Any) -> httpx2.Response:
        return self.request("DELETE", path, **kwargs)


@pytest.fixture
def client(session):
    return ApiClient()


@pytest.fixture(autouse=True)
def no_modules():
    """Every test starts, and leaves, with no module loaded."""
    registry.use([])
    registry.forget_available()
    yield
    registry.use([])
    registry.forget_available()


@pytest.fixture
def module_package(tmp_path, monkeypatch):
    """A package of modules, written for the test; returns how to add one."""
    package = tmp_path / "some_modules"
    package.mkdir()
    (package / "__init__.py").write_text("")
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setattr(registry, "MODULE_PACKAGE", "some_modules")

    def add(name: str, source: str) -> None:
        (package / name).mkdir()
        (package / name / "__init__.py").write_text(textwrap.dedent(source))

    yield add
    for loaded in [name for name in sys.modules if name.startswith("some_modules")]:
        del sys.modules[loaded]


@pytest.fixture
def config_injector():
    original_config = config.config

    def injector(new_config_content):
        config.config = new_config_content

    yield injector
    config.config = original_config


@pytest.fixture
def user_factory():
    def factory(
        name=None,
        rank=model.User.RANK_REGULAR,
        email="dummy",
        password_salt=None,
        password_hash=None,
    ):
        user = model.User()
        user.name = name or get_unique_name()
        user.password_salt = password_salt or "dummy"
        user.password_hash = password_hash or "dummy"
        user.email = email
        user.rank = rank
        user.creation_time = datetime(1997, 1, 1)
        user.avatar_style = model.User.AVATAR_GRAVATAR
        return user

    return factory


@pytest.fixture
def user_token_factory(user_factory):
    def factory(
        user=None,
        token=None,
        expiration_time=None,
        enabled=None,
        creation_time=None,
    ):
        if user is None:
            user = user_factory()
            db.session.add(user)
        user_token = model.UserToken()
        user_token.user = user
        user_token.token = token or "dummy"
        user_token.expiration_time = expiration_time
        user_token.enabled = enabled if enabled is not None else True
        user_token.creation_time = creation_time or datetime(1997, 1, 1)
        return user_token

    return factory


@pytest.fixture
def tag_category_factory():
    def factory(name=None, color="dummy", order=1, default=False):
        category = model.TagCategory()
        category.name = name or get_unique_name()
        category.color = color
        category.order = order
        category.default = default
        return category

    return factory


@pytest.fixture
def tag_factory():
    def factory(names=None, category=None):
        if not category:
            category = model.TagCategory(get_unique_name())
            db.session.add(category)
        tag = model.Tag()
        tag.names = []
        for i, name in enumerate(names or [get_unique_name()]):
            tag.names.append(model.TagName(name, i))
        tag.category = category
        tag.creation_time = datetime(1996, 1, 1)
        return tag

    return factory


@pytest.fixture
def post_factory():
    def factory(
        id=None,
        safety=model.Post.SAFETY_SAFE,
        type=model.Post.TYPE_IMAGE,
        checksum="...",
    ):
        post = model.Post()
        if id is not None:
            post.post_id = id
        post.safety = safety
        post.type = type
        post.checksum = checksum
        post.flags = []
        post.mime_type = "application/octet-stream"
        post.creation_time = datetime(1996, 1, 1)
        return post

    return factory


@pytest.fixture
def comment_factory(user_factory, post_factory):
    def factory(user=None, post=None, text="dummy", time=None):
        if not user:
            user = user_factory()
            db.session.add(user)
        if not post:
            post = post_factory()
            db.session.add(post)
        comment = model.Comment()
        comment.user = user
        comment.post = post
        comment.text = text
        comment.creation_time = time or datetime(1996, 1, 1)
        return comment

    return factory


@pytest.fixture
def post_score_factory(user_factory, post_factory):
    def factory(post=None, user=None, score=1):
        if user is None:
            user = user_factory()
        if post is None:
            post = post_factory()
        return model.PostScore(
            post=post, user=user, score=score, time=datetime(1999, 1, 1)
        )

    return factory


@pytest.fixture
def post_favorite_factory(user_factory, post_factory):
    def factory(post=None, user=None):
        if user is None:
            user = user_factory()
        if post is None:
            post = post_factory()
        return model.PostFavorite(post=post, user=user, time=datetime(1999, 1, 1))

    return factory


@pytest.fixture
def pool_category_factory():
    def factory(name=None, color="dummy", default=False):
        category = model.PoolCategory()
        category.name = name or get_unique_name()
        category.color = color
        category.default = default
        return category

    return factory


@pytest.fixture
def pool_factory():
    def factory(id=None, names=None, description=None, category=None, time=None):
        if not category:
            category = model.PoolCategory(get_unique_name())
            db.session.add(category)
        pool = model.Pool()
        if id is not None:
            pool.pool_id = id
        pool.names = []
        for i, name in enumerate(names or [get_unique_name()]):
            pool.names.append(model.PoolName(name, i))
        pool.description = description
        pool.category = category
        pool.creation_time = time or datetime(1996, 1, 1)
        return pool

    return factory


@pytest.fixture
def pool_post_factory(pool_factory, post_factory):
    def factory(pool=None, post=None, order=None):
        if not pool:
            pool = pool_factory()
            db.session.add(pool)
        if not post:
            post = post_factory()
            db.session.add(post)
        pool_post = model.PoolPost(post)
        pool_post.pool = pool
        pool_post.post = post
        pool_post.order = order or 0
        return pool_post

    return factory


@pytest.fixture
def read_asset():
    def get(path):
        path = os.path.join(os.path.dirname(__file__), "assets", path)
        with open(path, "rb") as handle:
            return handle.read()

    return get
