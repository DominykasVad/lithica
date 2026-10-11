from typing import Annotated, Any

from fastapi import Depends

from lithica import model, search
from lithica.api import resources
from lithica.api.dependencies import PageParams, require
from lithica.api.dependencies import search as run_search
from lithica.api.routing import ApiRouter
from lithica.func import snapshots

router = ApiRouter(tags=["Snapshots"])

_search_executor = search.Executor(search.configs.SnapshotSearchConfig())


@router.get(
    "/snapshots",
    response_model=resources.Paged[resources.Snapshot],
    summary="List snapshots",
)
def get_snapshots(
    auth_user: Annotated[model.User, Depends(require("snapshots:list"))],
    page: PageParams,
) -> Any:
    """The history of changes to tags, posts, pools and their categories."""
    return run_search(
        _search_executor,
        page,
        lambda snapshot: snapshots.serialize_snapshot(snapshot, auth_user),
    )
