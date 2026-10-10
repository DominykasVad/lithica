from collections.abc import Callable

from lithica.rest.context import Context

pre_hooks: list[Callable[[Context], None]] = []
post_hooks: list[Callable[[Context], None]] = []


def pre_hook(handler: Callable) -> None:
    pre_hooks.append(handler)


def post_hook(handler: Callable) -> None:
    post_hooks.insert(0, handler)
