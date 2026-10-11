"""
The database session.

`session` hands out one SQLAlchemy session per *scope*. A scope is one unit of
work: an HTTP request, one run of a background job, one admin command. The
current scope lives in a ContextVar, not in thread-local storage, because one
request does not stay on one thread: its dependencies and its endpoint may run
on different pool threads, and every such thread runs in a copy of the
request's context. The copies all hold the same scope object, so they all
reach the same session.

There is no implicit scope. Code that runs outside a request has to open one
with `session_scope()`; using `session` without a scope is an error rather
than a session that is silently shared or never closed.
"""

import contextlib
from collections.abc import Iterator
from contextvars import ContextVar, Token
from typing import Any

import sqlalchemy as sa
import sqlalchemy.event as sa_event
import sqlalchemy.orm as sa_orm

from lithica import config


class _Scope:
    """Identity of one unit of work; also counts its queries for the log."""

    def __init__(self) -> None:
        self.query_count = 0


_scope: ContextVar[_Scope | None] = ContextVar("lithica_db_scope", default=None)


def _current_scope() -> _Scope:
    scope = _scope.get()
    if scope is None:
        raise RuntimeError(
            "No database session scope is active. "
            "Wrap the work in lithica.db.session_scope()."
        )
    return scope


_engine: Any = sa.create_engine(config.config["database"])
_sessionmaker: Any = sa_orm.sessionmaker(_engine, autoflush=False)
# Any: the tests replace this with a plain session bound to their transaction
session: Any = sa_orm.scoped_session(_sessionmaker, scopefunc=_current_scope)


def begin_scope() -> Token[_Scope | None]:
    """Start a scope. Pair with close_session() and end_scope()."""
    return _scope.set(_Scope())


def close_session() -> None:
    """Close the session of the current scope, if one was ever used."""
    session.remove()


def end_scope(token: Token[_Scope | None]) -> None:
    _scope.reset(token)


@contextlib.contextmanager
def session_scope() -> Iterator[None]:
    """
    Run a block of work with its own session, closed at the end. For
    background threads, startup work and the admin CLI; requests get their
    scope from the application's middleware.
    """
    token = begin_scope()
    try:
        yield
    finally:
        try:
            close_session()
        finally:
            end_scope(token)


def get_session() -> Any:
    global session
    return session


def set_sesssion(new_session: Any) -> None:
    global session
    session = new_session


def reset_query_count() -> None:
    scope = _scope.get()
    if scope is not None:
        scope.query_count = 0


def get_query_count() -> int:
    scope = _scope.get()
    return scope.query_count if scope is not None else 0


def _bump_query_count() -> None:
    scope = _scope.get()
    if scope is not None:
        scope.query_count += 1


sa_event.listen(_engine, "after_execute", lambda *args: _bump_query_count())
