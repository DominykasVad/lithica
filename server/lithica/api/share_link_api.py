from typing import Annotated, Any

from fastapi import APIRouter, Depends
from starlette.responses import Response

from lithica import db, errors, model
from lithica.api import resources
from lithica.api.dependencies import CurrentUser, Page, get_page, read_body
from lithica.api.paths import SHARE_LINK_PATH
from lithica.api.routing import ERROR_RESPONSES, ApiRouter
from lithica.api.schemas import RequestModel, Str, request_body
from lithica.func import auth, posts, share_links, users

# Any return values are serializer output, described by the response models.
router = ApiRouter(tags=["Share links"])
delivery_router = APIRouter(tags=["Share links"], responses=ERROR_RESPONSES)


class ShareLinkCreate(RequestModel):
    note: Str | None = None
    expires_at: Str | None = None


@router.post(
    "/post/{post_id}/share-links",
    response_model=resources.ShareLink,
    openapi_extra=request_body(ShareLinkCreate),
)
def create(
    post_id: int,
    user: CurrentUser,
    body: Annotated[ShareLinkCreate, Depends(read_body(ShareLinkCreate))],
) -> Any:
    """Create a reusable bearer link with an optional note and expiry."""
    auth.verify_privilege(user, "share_links:create")
    link = share_links.create(
        posts.get_post_by_id(post_id), user, body.note, body.expires_at
    )
    db.session.commit()
    return share_links.serialize(link, user)


@router.get(
    "/post/{post_id}/share-links", response_model=resources.Unpaged[resources.ShareLink]
)
def list_post(post_id: int, user: CurrentUser) -> Any:
    """List your links of this visible post, or all with share_links:list:any."""
    posts.get_post_by_id(post_id)
    query = db.session.query(model.ShareLink).filter_by(post_id=post_id)
    if not auth.has_privilege(user, "share_links:list:any"):
        auth.verify_privilege(user, "share_links:list:self")
        query = query.filter_by(user_id=user.user_id)
    return {
        "results": [
            share_links.serialize(link, user)
            for link in query.order_by(model.ShareLink.id)
        ]
    }


@router.get(
    "/user/{user_name}/share-links", response_model=resources.Paged[resources.ShareLink]
)
def list_user(
    user_name: str, user: CurrentUser, page: Annotated[Page, Depends(get_page)]
) -> Any:
    """Page through a user's share links; another user requires share_links:list:any."""
    owner = users.get_user_by_name(user_name)
    infix = "self" if owner.user_id == user.user_id else "any"
    if not auth.has_privilege(user, "share_links:list:any"):
        auth.verify_privilege(user, "share_links:list:" + infix)
    # Join the post so anonymous NSFW filtering also covers these resources.
    query = (
        db.session.query(model.ShareLink)
        .join(model.Post, model.ShareLink.post_id == model.Post.post_id)
        .filter(model.ShareLink.user_id == owner.user_id)
    )
    return {
        "query": page.query,
        "offset": page.offset,
        "limit": page.limit,
        "total": query.count(),
        "results": [
            share_links.serialize(link, user)
            for link in query.order_by(model.ShareLink.id)
            .offset(page.offset)
            .limit(page.limit)
        ],
    }


@router.delete("/share-link/{link_id}", response_model=resources.Empty)
def delete(link_id: int, user: CurrentUser) -> Any:
    """Revoke a share link by id, for its owner or a caller with delete:any."""
    link = db.session.get(model.ShareLink, link_id)
    if link is None:
        raise errors.NotFoundError("Share link not found.")
    infix = "self" if link.user_id == user.user_id else "any"
    if not auth.has_privilege(user, "share_links:delete:any"):
        auth.verify_privilege(user, "share_links:delete:" + infix)
    db.session.delete(link)
    db.session.commit()
    return {}


@delivery_router.get(
    SHARE_LINK_PATH, response_class=Response, openapi_extra={"security": []}
)
def deliver(token: str) -> Response:
    """Authorize anonymous file delivery through nginx. Every refusal is the same 404.

    The server itself returns no bytes; nginx preserves Content-Type and serves
    the internal X-Accel-Redirect target. Authorization headers are ignored.
    """
    filename, mime = share_links.delivery(token)
    return Response(
        headers={"X-Accel-Redirect": "/_share/" + filename, "Content-Type": mime}
    )
