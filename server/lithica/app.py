"""
The ASGI application. Run it with `uvicorn lithica.app:app`.

Importing this module has no side effects beyond building the application
object: the configuration is checked and the background work is started when
the server starts the application (the lifespan), not at import.
"""

import contextlib
import logging
from collections.abc import AsyncIterator

import anyio
from a2wsgi import WSGIMiddleware
from fastapi import FastAPI
from starlette.concurrency import run_in_threadpool
from starlette.types import ASGIApp, Receive, Scope, Send

from lithica import db, facade, rest
from lithica.api import error_handlers
from lithica.api.dependencies import LOG_USER_KEY

logger = logging.getLogger(__name__)


class SessionScopeMiddleware:
    """
    Give every request its own database session scope (see lithica.db) and
    close the session when the response is out.

    Opening the scope here, before anything else runs, is what lets the
    dependencies and the endpoint of one request share a session although
    they run on different threads, and keeps two requests apart although
    they may run on the same thread one after the other.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        token = db.begin_scope()
        try:
            await self.app(scope, receive, send)
        finally:
            # One line per request. Only for the routes served here: the old
            # application still writes its own line for the ones it serves.
            if LOG_USER_KEY in scope:
                logger.info(
                    "%s %s (user=%s, queries=%d)",
                    scope["method"],
                    scope["path"],
                    scope[LOG_USER_KEY],
                    db.get_query_count(),
                )
            try:
                # Closing rolls back and returns the connection: blocking
                # work, so off the event loop. Shielded, because a request
                # cancelled half-way must still give its connection back.
                with anyio.CancelScope(shield=True):
                    await run_in_threadpool(db.close_session)
            finally:
                db.end_scope(token)


@contextlib.asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    facade.start()
    yield


def create_app() -> FastAPI:
    # The interactive documentation and the OpenAPI document stay off until
    # the contract is in place (PLAN.md 2.5). A trailing slash is answered
    # by the routes themselves, never by a redirect.
    application = FastAPI(
        title="Lithica",
        lifespan=_lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        redirect_slashes=False,
    )

    application.add_middleware(SessionScopeMiddleware)
    error_handlers.install(application)

    # Routes that are not ported to FastAPI yet are answered by the old WSGI
    # application. It must stay the last route: a mount at "/" matches
    # every path.
    facade.register_error_handlers()
    # a2wsgi and Starlette each declare the WSGI and ASGI callables with
    # their own, structurally equal, types; pyright cannot match them
    fallback = WSGIMiddleware(rest.application)  # type: ignore[arg-type]
    application.mount("/", fallback)  # type: ignore[arg-type]
    return application


app = create_app()
