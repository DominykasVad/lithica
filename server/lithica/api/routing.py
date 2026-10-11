import functools
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends

from lithica.api.dependencies import get_user, require_json_accept
from lithica.api.responses import JsonResponse
from lithica.api.schemas import ErrorResponse

# described once for every operation; the statuses an endpoint can answer
# with depend on the business errors it runs into
ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    "4XX": {"model": ErrorResponse, "description": "The request was refused."},
}


class ApiRouter(APIRouter):
    """
    Router of one API resource. On top of FastAPI's router:

    - an endpoint returns plain data and it is written with `JsonResponse`,
      the wire format of the old framework. A `response_model` given on the
      route documents the response and is not applied to it (see
      `schemas.ResponseModel`);
    - every path is also served with a trailing slash, as the old routes
      were, without a redirect. Paths that end in a `:path` parameter are
      the exception: there the slash is part of the value;
    - a request must accept JSON, and is authenticated.
    """

    def __init__(self, **kwargs: Any) -> None:
        # every request is authenticated, whether or not its endpoint asks
        # who the user is: wrong credentials are refused everywhere
        kwargs.setdefault(
            "dependencies", [Depends(require_json_accept), Depends(get_user)]
        )
        kwargs.setdefault("responses", ERROR_RESPONSES)
        super().__init__(**kwargs)

    # Any: the signature is FastAPI's, passed through unchanged
    def add_api_route(
        self, path: str, endpoint: Callable[..., Any], **kwargs: Any
    ) -> None:
        @functools.wraps(endpoint)
        def respond(*args: Any, **endpoint_kwargs: Any) -> JsonResponse:
            return JsonResponse(endpoint(*args, **endpoint_kwargs))

        super().add_api_route(path, respond, **kwargs)
        if not path.endswith("/") and not path.endswith(":path}"):
            kwargs["include_in_schema"] = False
            super().add_api_route(path + "/", respond, **kwargs)
