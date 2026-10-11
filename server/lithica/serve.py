"""
Starts the server: `python -m lithica.serve [--reload]`.

It is uvicorn serving lithica.app:app, with one thing done here instead of
by uvicorn: opening the listening socket. Asked to listen on `::`, uvicorn
serves IPv6 only when it runs as a single process and both address families
when it runs several or reloads, because the two paths open the socket
differently. Here `::` always means IPv4 and IPv6.

Settings, from the environment:

    HOST     address to listen on. Default `::`: every address, IPv4 and
             IPv6. Use `0.0.0.0` on a host where IPv6 is disabled.
    PORT     port to listen on. Default 6666.
    WORKERS  server processes. Default 1.

`--reload` runs one process and restarts it when a source file changes.
"""

import logging
import os
import socket
import sys

import uvicorn
from uvicorn.supervisors import ChangeReload, Multiprocess

logger = logging.getLogger(__name__)

APPLICATION = "lithica.app:app"
DEFAULT_HOST = "::"
DEFAULT_PORT = 6666
# what uvicorn exits with when the application does not start
STARTUP_FAILURE = 3


def listening_socket(host: str, port: int) -> socket.socket:
    """
    A socket bound to the address. On `::` it accepts IPv4 connections as
    well, whatever the system's default for that is.
    """
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    sock = socket.socket(family=family)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if family == socket.AF_INET6 and host == "::":
            sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        sock.bind((host, port))
    except OSError:
        sock.close()
        raise
    # the worker processes inherit it
    sock.set_inheritable(True)
    return sock


def main(arguments: list[str]) -> int:
    host = os.environ.get("HOST") or DEFAULT_HOST
    port = int(os.environ.get("PORT") or DEFAULT_PORT)
    workers = int(os.environ.get("WORKERS") or 1)
    reload = "--reload" in arguments

    config = uvicorn.Config(
        APPLICATION,
        host=host,
        port=port,
        workers=workers,
        reload=reload,
        # the application writes its own line per request
        access_log=False,
    )
    try:
        sock = listening_socket(host, port)
    except OSError as ex:
        hint = ""
        if host == DEFAULT_HOST:
            hint = " If IPv6 is disabled on this host, set HOST=0.0.0.0."
        sys.stderr.write(
            "Cannot listen on %s port %d: %s.%s\n" % (host, port, ex, hint)
        )
        return STARTUP_FAILURE

    # as uvicorn.run() does, with our socket in every case
    server = uvicorn.Server(config)
    if config.should_reload:
        ChangeReload(config, target=server.run, sockets=[sock]).run()
    elif config.workers > 1:
        Multiprocess(config, sockets=[sock]).run()
    else:
        server.run(sockets=[sock])
        if not server.started:
            return STARTUP_FAILURE
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
