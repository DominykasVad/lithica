import asyncio
import threading
from typing import Annotated

import httpx2
import pytest
from fastapi import Depends, FastAPI

from lithica import db, model
from lithica.app import SessionScopeMiddleware


def _open_sessions() -> int:
    return len(db.session.registry.registry)


def test_no_session_without_a_scope(scoped_db_session):
    with pytest.raises(RuntimeError, match="session scope"):
        db.session.query(model.User)


def test_scope_has_one_session_and_closes_it(scoped_db_session):
    with db.session_scope():
        first = db.session()
        assert db.session() is first
        assert _open_sessions() == 1
    assert _open_sessions() == 0


def test_nested_scopes_have_their_own_sessions(scoped_db_session):
    with db.session_scope():
        outer = db.session()
        with db.session_scope():
            assert db.session() is not outer
        assert db.session() is outer
    assert _open_sessions() == 0


def test_scope_is_closed_after_an_error(scoped_db_session):
    with pytest.raises(ZeroDivisionError):
        with db.session_scope():
            db.session()
            raise ZeroDivisionError()
    assert _open_sessions() == 0
    with pytest.raises(RuntimeError):
        db.session()


def test_threads_with_their_own_scopes_do_not_share_a_session(scoped_db_session):
    together = threading.Barrier(4)
    sessions = []

    def work():
        with db.session_scope():
            together.wait(timeout=10)
            sessions.append(db.session())
            together.wait(timeout=10)

    threads = [threading.Thread(target=work) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len({id(session) for session in sessions}) == 4
    assert _open_sessions() == 0


def test_a_thread_does_not_inherit_the_scope_of_its_parent(scoped_db_session):
    errors = []

    def work():
        try:
            db.session()
        except RuntimeError as ex:
            errors.append(ex)

    with db.session_scope():
        thread = threading.Thread(target=work)
        thread.start()
        thread.join()
    assert len(errors) == 1


def test_queries_are_counted_per_scope(scoped_db_session):
    assert db.get_query_count() == 0
    with db.session_scope():
        db._bump_query_count()
        db._bump_query_count()
        with db.session_scope():
            db._bump_query_count()
            assert db.get_query_count() == 1
        assert db.get_query_count() == 2
        db.reset_query_count()
        assert db.get_query_count() == 0
    assert db.get_query_count() == 0


def _app_reporting_sessions(concurrency: int) -> FastAPI:
    """
    An application whose one route reports the session its dependency saw
    and the session its endpoint saw, and holds every request until
    `concurrency` of them are inside the endpoint at the same time.
    """
    app = FastAPI()
    app.add_middleware(SessionScopeMiddleware)
    together = threading.Barrier(concurrency)

    def session_in_dependency() -> dict[str, int]:
        return {"session": id(db.session()), "thread": threading.get_ident()}

    @app.get("/")
    def endpoint(
        seen: Annotated[dict[str, int], Depends(session_in_dependency)],
    ) -> dict[str, int]:
        together.wait(timeout=10)
        report = {
            "dependency_session": seen["session"],
            "dependency_thread": seen["thread"],
            "endpoint_session": id(db.session()),
            "endpoint_thread": threading.get_ident(),
            "open_sessions": _open_sessions(),
        }
        # nobody leaves (and has its session closed) before all have counted
        together.wait(timeout=10)
        return report

    return app


def _get_concurrently(app: FastAPI, count: int) -> list[dict[str, int]]:
    async def run() -> list[dict[str, int]]:
        transport = httpx2.ASGITransport(app=app)
        async with httpx2.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            responses = await asyncio.gather(*[client.get("/") for _ in range(count)])
        return [response.json() for response in responses]

    return asyncio.run(run())


def test_concurrent_requests_never_share_a_session(scoped_db_session):
    count = 8
    results = _get_concurrently(_app_reporting_sessions(count), count)

    # all of them were in the endpoint at once, each with a session open
    assert all(result["open_sessions"] == count for result in results)
    assert len({result["endpoint_session"] for result in results}) == count
    # the endpoints really ran side by side, on different threads
    assert len({result["endpoint_thread"] for result in results}) == count
    # every session is closed once the responses are out
    assert _open_sessions() == 0


def test_one_request_has_one_session_on_every_thread(scoped_db_session):
    count = 8
    results = _get_concurrently(_app_reporting_sessions(count), count)
    for result in results:
        assert result["dependency_session"] == result["endpoint_session"]
    # the dependency and the endpoint are not tied to one thread: at least
    # one request was moved between threads and still kept its session
    assert any(
        result["dependency_thread"] != result["endpoint_thread"] for result in results
    )


def test_session_is_closed_when_the_endpoint_fails(scoped_db_session):
    app = FastAPI()
    app.add_middleware(SessionScopeMiddleware)

    @app.get("/")
    def endpoint() -> None:
        db.session()
        raise ZeroDivisionError()

    async def run() -> None:
        transport = httpx2.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx2.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            response = await client.get("/")
            assert response.status_code == 500

    asyncio.run(run())
    assert _open_sessions() == 0
