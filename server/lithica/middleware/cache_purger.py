from lithica import rest
from lithica.func import cache
from lithica.rest import middleware


@middleware.pre_hook
def process_request(ctx: rest.Context) -> None:
    if ctx.method != "GET":
        cache.purge()
