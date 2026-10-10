from collections import defaultdict
from collections.abc import Callable

from lithica.rest.context import Context, Response

RouteHandler = Callable[[Context, dict[str, str]], Response]
# The decorators return the handler with its own signature (F), so that a
# handler whose second parameter is optional can still be called without it.
routes: dict[str, dict[str, RouteHandler]] = defaultdict(dict)


def get[F: RouteHandler](url: str) -> Callable[[F], F]:
    def wrapper(handler: F) -> F:
        routes[url]["GET"] = handler
        return handler

    return wrapper


def put[F: RouteHandler](url: str) -> Callable[[F], F]:
    def wrapper(handler: F) -> F:
        routes[url]["PUT"] = handler
        return handler

    return wrapper


def post[F: RouteHandler](url: str) -> Callable[[F], F]:
    def wrapper(handler: F) -> F:
        routes[url]["POST"] = handler
        return handler

    return wrapper


def delete[F: RouteHandler](url: str) -> Callable[[F], F]:
    def wrapper(handler: F) -> F:
        routes[url]["DELETE"] = handler
        return handler

    return wrapper
