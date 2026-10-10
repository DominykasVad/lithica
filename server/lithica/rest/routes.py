from collections import defaultdict
from collections.abc import Callable

from lithica.rest.context import Context, Response

RouteHandler = Callable[[Context, dict[str, str]], Response]
routes: dict[str, dict[str, RouteHandler]] = defaultdict(dict)


def get(url: str) -> Callable[[RouteHandler], RouteHandler]:
    def wrapper(handler: RouteHandler) -> RouteHandler:
        routes[url]["GET"] = handler
        return handler

    return wrapper


def put(url: str) -> Callable[[RouteHandler], RouteHandler]:
    def wrapper(handler: RouteHandler) -> RouteHandler:
        routes[url]["PUT"] = handler
        return handler

    return wrapper


def post(url: str) -> Callable[[RouteHandler], RouteHandler]:
    def wrapper(handler: RouteHandler) -> RouteHandler:
        routes[url]["POST"] = handler
        return handler

    return wrapper


def delete(url: str) -> Callable[[RouteHandler], RouteHandler]:
    def wrapper(handler: RouteHandler) -> RouteHandler:
        routes[url]["DELETE"] = handler
        return handler

    return wrapper
