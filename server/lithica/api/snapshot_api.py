from lithica import rest, search
from lithica.func import auth, snapshots

_search_executor = search.Executor(search.configs.SnapshotSearchConfig())


@rest.routes.get("/snapshots/?")
def get_snapshots(
    ctx: rest.Context, _params: dict[str, str] | None = None
) -> rest.Response:
    if _params is None:
        _params = {}
    auth.verify_privilege(ctx.user, "snapshots:list")
    return _search_executor.execute_and_serialize(
        ctx, lambda snapshot: snapshots.serialize_snapshot(snapshot, ctx.user)
    )
