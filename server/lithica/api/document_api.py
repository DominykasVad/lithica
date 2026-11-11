"""One version-history API for every registered document kind."""

from typing import Annotated, Any

from fastapi import Depends

from lithica import db, model
from lithica.api import resources
from lithica.api.dependencies import Page, get_page, read_body, require
from lithica.api.routing import ApiRouter
from lithica.api.schemas import Int, RequestModel, request_body, required
from lithica.func import documents, posts

router = ApiRouter(tags=["Documents"])
Viewer = Annotated[model.User, Depends(require("posts:view"))]
Editor = Annotated[model.User, Depends(require("posts:edit:document"))]


class RestoreDocument(RequestModel):
    version: Int = required()


@router.get("/post/{post_id}/document", response_model=resources.PostDocument)
def get_post_document(post_id: int, user: Viewer) -> Any:
    """Read the current document. Missing or unloaded documents and hidden posts
    answer 404 DocumentNotFoundError or PostNotFoundError; insufficient privileges
    answer 403 AuthError.
    """
    return documents.serialize(documents.get(posts.get_post_by_id(post_id)))


@router.get(
    "/post/{post_id}/document-versions",
    response_model=resources.Paged[resources.DocumentVersion],
)
def get_post_document_versions(
    post_id: int, user: Viewer, page: Annotated[Page, Depends(get_page)]
) -> Any:
    """List versions newest first, without data, at most 100 per page.
    Missing/unloaded documents or hidden posts answer 404; insufficient privileges
    answer 403; invalid paging answers 400 ValidationError.
    """
    return documents.list_versions(
        posts.get_post_by_id(post_id), page.offset, page.limit, user
    )


@router.get(
    "/post/{post_id}/document-version/{number}",
    response_model=resources.DocumentVersionData,
)
def get_post_document_version(post_id: int, number: int, user: Viewer) -> Any:
    """Read a version and its data. Missing, pruned or unloaded documents answer
    404 DocumentNotFoundError; hidden posts answer 404 PostNotFoundError;
    insufficient privileges answer 403 AuthError.
    """
    return documents.serialize_version(
        documents.get_version(posts.get_post_by_id(post_id), number), user, data=True
    )


@router.post(
    "/post/{post_id}/document-version/{number}/restore",
    response_model=resources.PostDocument,
    openapi_extra=request_body(RestoreDocument),
)
def restore_post_document_version(
    post_id: int,
    number: int,
    user: Editor,
    body: Annotated[RestoreDocument, Depends(read_body(RestoreDocument))],
) -> Any:
    """Restore a retained version as a new current version; identical data is a no-op.
    Missing/pruned/unloaded documents or hidden posts answer 404; stale version
    answers 409 IntegrityError; rejected data answers 400 ValidationError;
    insufficient privileges answer 403 AuthError.
    """
    result = documents.serialize(
        documents.restore(
            posts.get_post_by_id(post_id), number, body.require("version"), user
        )
    )
    db.session.commit()
    return result
