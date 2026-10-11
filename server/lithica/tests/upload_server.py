"""
The real application in a process of its own, for test_upload_memory.

    python -m lithica.tests.upload_server <port> <data directory>

How much memory an upload costs the server cannot be measured inside the
test process: the test client there holds the whole request body itself. So
the test starts this server, sends the upload over a socket and asks the
server how large it has grown (GET /_peak_rss).

Every request is made as an administrator and nothing here uses the
database, so the server needs none.
"""

import resource
import sys

from lithica import config


def main(port: int, data_dir: str) -> None:
    # lithica.db builds an engine from this on import; it is never connected
    config.config.setdefault("database", "postgresql://unused@localhost/unused")
    config.config["data_dir"] = data_dir
    config.config["max_upload_size"] = 1024 * 1024 * 1024

    import uvicorn
    from starlette.requests import Request
    from starlette.responses import PlainTextResponse
    from starlette.routing import Route

    from lithica import model
    from lithica.api import dependencies
    from lithica.app import app

    def administrator() -> model.User:
        user = model.User()
        user.name = "uploader"
        user.rank = model.User.RANK_ADMINISTRATOR
        return user

    def peak_rss(_request: Request) -> PlainTextResponse:
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        # kilobytes on Linux, bytes on macOS
        return PlainTextResponse(str(peak if sys.platform == "darwin" else peak * 1024))

    app.dependency_overrides[dependencies.get_user] = administrator
    # in front of everything, the old application's mount included
    app.router.routes.insert(0, Route("/_peak_rss", peak_rss))
    # no lifespan: no configuration check, no background work
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning", lifespan="off")


if __name__ == "__main__":
    main(int(sys.argv[1]), sys.argv[2])
