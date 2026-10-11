"""
The ASGI application. Run it with `uvicorn lithica.app:app`.

Importing this module has no side effects beyond building the application
object: the configuration is checked and the background work is started when
the server starts the application (the lifespan), not at import.
"""

import contextlib
import logging
import os
import threading
from collections.abc import AsyncIterator

import anyio
import coloredlogs
from a2wsgi import WSGIMiddleware
from fastapi import FastAPI
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from lithica import config, db, facade, rest
from lithica.api import (
    comment_api,
    error_handlers,
    info_api,
    password_reset_api,
    pool_api,
    pool_category_api,
    tag_api,
    tag_category_api,
    user_api,
    user_token_api,
)
from lithica.api.dependencies import LOG_USER_KEY
from lithica.func import file_uploads, posts

logger = logging.getLogger(__name__)


CORS_ALLOWED_METHODS = "GET, POST, PUT, DELETE, OPTIONS"
CORS_ALLOWED_HEADERS = "Authorization, Content-Type"


class CorsMiddleware:
    """
    Answer cross-origin requests from the origins listed in the cors_origins
    setting, and only from those. With the default empty list no header is
    sent and browsers allow same-origin requests only.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        allowed_origins = config.config.get("cors_origins") or []
        if scope["type"] != "http" or not allowed_origins:
            await self.app(scope, receive, send)
            return

        request_headers = Headers(scope=scope)
        origin = request_headers.get("origin")
        # the response differs by origin, so shared caches must key on it
        cors_headers = {"Vary": "Origin"}
        if origin is not None and origin in allowed_origins:
            cors_headers["Access-Control-Allow-Origin"] = origin

        is_allowed_preflight = (
            scope["method"] == "OPTIONS"
            and "access-control-request-method" in request_headers
            and origin in allowed_origins
        )
        if is_allowed_preflight:
            response = Response(
                status_code=200,
                headers={
                    "Access-Control-Allow-Methods": CORS_ALLOWED_METHODS,
                    "Access-Control-Allow-Headers": CORS_ALLOWED_HEADERS,
                    **cors_headers,
                },
            )
            await response(scope, receive, send)
            return

        async def send_with_cors(message: Message) -> None:
            # on error responses too, or the client could not read the error
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message).update(cors_headers)
            await send(message)

        await self.app(scope, receive, send_with_cors)


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


# how often the temporary uploads are checked for files to delete
UPLOAD_PURGE_INTERVAL = 60 * 5


def _configure_logging() -> None:
    coloredlogs.install(fmt="[%(asctime)-15s] %(name)s %(message)s")
    if config.config["debug"]:
        logging.getLogger("lithica").setLevel(logging.INFO)
    if config.config["show_sql"]:
        logging.getLogger("sqlalchemy.engine").setLevel(logging.INFO)


def _limit_request_threads() -> None:
    """
    Endpoints and their dependencies are synchronous and run on a pool of
    threads; its size is how many requests are worked on at once. THREADS
    sets it, as it set the thread count of the server used before. Without
    it the pool keeps the library's default size.
    """
    threads = os.environ.get("THREADS")
    if threads:
        anyio.to_thread.current_default_thread_limiter().total_tokens = int(threads)


def _purge_old_uploads_until(stop: threading.Event) -> None:
    while True:
        file_uploads.purge_old_uploads_once()
        if stop.wait(UPLOAD_PURGE_INTERVAL):
            return


def _warn_about_pending_backfills() -> None:
    # the startup work is its own unit of work, with its own session
    with db.session_scope():
        try:
            posts.warn_about_pending_backfills()
        except Exception as ex:
            # a missing backfill is no reason to stay down
            logger.exception(ex)


@contextlib.asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """
    What the server does when it starts and stops the application. A
    configuration error raised here stops the server before it listens.
    Every server process runs this for itself.
    """
    config.validate()
    _configure_logging()
    _limit_request_threads()
    # the check queries the database: off the event loop
    await run_in_threadpool(_warn_about_pending_backfills)

    stop_purging = threading.Event()
    threading.Thread(
        target=_purge_old_uploads_until,
        args=(stop_purging,),
        name="upload-purge",
        daemon=True,
    ).start()
    try:
        yield
    finally:
        stop_purging.set()


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
    # added last, so outermost: also answers for responses made further in
    application.add_middleware(CorsMiddleware)
    error_handlers.install(application)

    for ported in [
        info_api,
        user_api,
        user_token_api,
        password_reset_api,
        tag_category_api,
        tag_api,
        pool_category_api,
        pool_api,
        comment_api,
    ]:
        application.include_router(ported.router)

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
