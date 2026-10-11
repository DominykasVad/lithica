"""
The API's own documentation, served next to the API when the `api_docs`
setting is on: the OpenAPI document and two pages that display it.

The pages load the OpenAPI document by a relative URL and the document
names its server relatively, so all of it works under whatever base path
the API is deployed at. The pages take their scripts and styles from a
public CDN; that is one reason the setting is off unless switched on.
"""

from typing import Any

from fastapi import APIRouter, Request
from fastapi.openapi.docs import get_redoc_html
from starlette.exceptions import HTTPException
from starlette.responses import HTMLResponse, JSONResponse

from lithica import config

router = APIRouter(include_in_schema=False)

# relative to the page that loads it
OPENAPI_URL = "openapi.json"
TITLE = "Lithica API"


def _require_enabled() -> None:
    if not config.config.get("api_docs"):
        # as for any path that does not exist
        raise HTTPException(status_code=404)


@router.get("/openapi.json")
def get_openapi_document(request: Request) -> JSONResponse:
    _require_enabled()
    document: dict[str, Any] = request.app.openapi()
    return JSONResponse(document)


# FastAPI's own Swagger UI page, plus one thing: every request the page
# makes for the user says that it accepts JSON, which the API insists on and
# Swagger UI on its own does not send.
SWAGGER_UI_PAGE = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>%(title)s</title>
<link rel="stylesheet" href="%(cdn)s/swagger-ui.css">
</head>
<body>
<div id="swagger-ui"></div>
<script src="%(cdn)s/swagger-ui-bundle.js"></script>
<script>
SwaggerUIBundle({
    url: "%(openapi_url)s",
    dom_id: "#swagger-ui",
    presets: [SwaggerUIBundle.presets.apis, SwaggerUIBundle.SwaggerUIStandalonePreset],
    layout: "BaseLayout",
    deepLinking: true,
    requestInterceptor: (request) => {
        if (!request.loadSpec) {
            request.headers["Accept"] = "application/json";
        }
        return request;
    },
});
</script>
</body>
</html>
"""
SWAGGER_UI_CDN = "https://cdn.jsdelivr.net/npm/swagger-ui-dist@5"


@router.get("/docs")
def get_swagger_ui() -> HTMLResponse:
    _require_enabled()
    return HTMLResponse(
        SWAGGER_UI_PAGE
        % {"title": TITLE, "cdn": SWAGGER_UI_CDN, "openapi_url": OPENAPI_URL}
    )


@router.get("/redoc")
def get_redoc() -> HTMLResponse:
    _require_enabled()
    return get_redoc_html(openapi_url=OPENAPI_URL, title=TITLE)
