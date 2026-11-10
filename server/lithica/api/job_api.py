from typing import Annotated, Any

from fastapi import Depends, Query

from lithica.api import resources
from lithica.api.dependencies import CurrentUser, Page, get_page
from lithica.api.routing import ApiRouter
from lithica.func import auth, jobs

router = ApiRouter(tags=["Jobs"])


@router.get(
    "/jobs",
    response_model=resources.Paged[resources.Job],
    summary="List background jobs",
)
def get_jobs(
    user: CurrentUser,
    page: Annotated[Page, Depends(get_page)],
    status: str | None = None,
    type: Annotated[str | None, Query()] = None,
) -> Any:
    """List jobs newest first, without payloads, with status and type filters.

    Errors: 403 without jobs:list; 400 for an invalid status or paging value.
    """
    auth.verify_privilege(user, "jobs:list")
    query = jobs.listing(status, type)
    return {
        "query": page.query,
        "offset": page.offset,
        "limit": page.limit,
        "total": query.count(),
        "results": [
            jobs.serialize(job) for job in query.offset(page.offset).limit(page.limit)
        ],
    }


@router.get(
    "/job/{id}", response_model=resources.JobDetail, summary="View a background job"
)
def get_job(id: int, user: CurrentUser) -> Any:
    """Read a job, including its payload.

    Errors: 403 without jobs:view; 404 when the job does not exist.
    """
    auth.verify_privilege(user, "jobs:view")
    return jobs.serialize(jobs.get(id), payload=True)
