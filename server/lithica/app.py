"""
The ASGI application. Run it with `uvicorn lithica.app:app`.

Importing this module has no side effects beyond building the application
object: the configuration is checked and the background work is started when
the server starts the application (the lifespan), not at import.
"""

import contextlib
from collections.abc import AsyncIterator

from a2wsgi import WSGIMiddleware
from fastapi import FastAPI

from lithica import facade, rest


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
