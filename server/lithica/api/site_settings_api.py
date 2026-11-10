from typing import Annotated, Any

from fastapi import Depends

from lithica import db, model
from lithica.api import resources
from lithica.api.dependencies import CurrentUser, read_body, require
from lithica.api.routing import ApiRouter
from lithica.api.schemas import Int, RequestModel, request_body, required
from lithica.func import auth, site_settings

router = ApiRouter(tags=["Site settings"])


class SiteSettingsUpdate(RequestModel):
    version: Int = required()
    # Any: raw JSON is validated per setting by the registry, without coercion.
    values: dict[str, Any] = required()


@router.get("/site-settings", response_model=resources.SiteSettings)
def get_site_settings(user: CurrentUser) -> dict[str, Any]:
    """Read effective settings and their config.yaml starting values."""
    auth.verify_privilege(user, "site_settings:view")
    return site_settings.describe()


@router.put(
    "/site-settings",
    response_model=resources.SiteSettings,
    openapi_extra=request_body(SiteSettingsUpdate),
)
def update_site_settings(
    user: Annotated[model.User, Depends(require("site_settings:edit"))],
    body: Annotated[SiteSettingsUpdate, Depends(read_body(SiteSettingsUpdate))],
) -> dict[str, Any]:
    """Atomically change named runtime settings; null restores config.yaml."""
    auth.verify_privilege(user, "site_settings:edit")
    site_settings.update(body.require("version"), body.require("values"), user)
    db.session.commit()
    return site_settings.describe()
