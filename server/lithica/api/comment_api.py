from typing import Annotated, Any

from fastapi import Depends

from lithica import db, model, search
from lithica.api import resources
from lithica.api.dependencies import (
    CurrentUser,
    Fields,
    PageParams,
    read_body,
    require,
)
from lithica.api.dependencies import search as run_search
from lithica.api.routing import ApiRouter
from lithica.api.schemas import (
    Int,
    RequestModel,
    Str,
    VersionOnly,
    request_body,
    required,
)
from lithica.func import auth, comments, posts, scores, util, versions

router = ApiRouter(tags=["Comments"])

_search_executor = search.Executor(search.configs.CommentSearchConfig())


class CommentCreate(RequestModel):
    text: Str = required()
    post_id: Int = required()


class CommentUpdate(RequestModel):
    version: Int = required()
    text: Str = required()


class ScoreUpdate(RequestModel):
    score: Int = required()


def _get_comment(comment_id: str) -> model.Comment:
    try:
        return comments.get_comment_by_id(int(comment_id))
    except ValueError:
        raise comments.InvalidCommentIdError(
            "Invalid comment ID: %r." % comment_id
        ) from None


# Any: the serializer's output, which the response model describes
def _serialize(comment: model.Comment, auth_user: model.User, fields: list[str]) -> Any:
    return comments.serialize_comment(comment, auth_user, options=fields)


@router.get(
    "/comments",
    response_model=resources.Paged[resources.Comment],
    summary="List comments",
)
def get_comments(
    auth_user: Annotated[model.User, Depends(require("comments:list"))],
    fields: Fields,
    page: PageParams,
) -> Any:
    """
    Searches for comments.

    The tokens `query` understands are listed under "Comment search" in
    doc/API.md.

    Errors:

    - privileges are too low
    """
    return run_search(
        _search_executor,
        page,
        lambda comment: _serialize(comment, auth_user, fields),
    )


@router.post(
    "/comments",
    response_model=resources.Comment,
    summary="Create a comment",
    openapi_extra=request_body(CommentCreate),
)
def create_comment(
    auth_user: Annotated[model.User, Depends(require("comments:create"))],
    fields: Fields,
    body: Annotated[CommentCreate, Depends(read_body(CommentCreate))],
) -> Any:
    """
    Creates a new comment under given post.

    Errors:

    - the post does not exist
    - comment text is empty
    - privileges are too low
    """
    text = body.require("text")
    post_id = body.require("post_id")
    post = posts.get_post_by_id(post_id)
    comment = comments.create_comment(auth_user if auth_user.name else None, post, text)
    db.session.add(comment)
    db.session.commit()
    return _serialize(comment, auth_user, fields)


@router.get(
    "/comment/{comment_id}",
    response_model=resources.Comment,
    summary="Get a comment",
)
def get_comment(
    comment_id: str,
    auth_user: Annotated[model.User, Depends(require("comments:view"))],
    fields: Fields,
) -> Any:
    """
    Retrieves information about an existing comment.

    Errors:

    - the comment does not exist
    - privileges are too low
    """
    comment = _get_comment(comment_id)
    return _serialize(comment, auth_user, fields)


@router.put(
    "/comment/{comment_id}",
    response_model=resources.Comment,
    summary="Update a comment",
    openapi_extra=request_body(CommentUpdate),
)
def update_comment(
    comment_id: str,
    auth_user: CurrentUser,
    fields: Fields,
    body: Annotated[CommentUpdate, Depends(read_body(CommentUpdate))],
) -> Any:
    """
    Updates an existing comment text.

    Errors:

    - the version is outdated
    - the comment does not exist
    - new comment text is empty
    - privileges are too low
    """
    comment = _get_comment(comment_id)
    versions.verify_version(comment, body.require("version"))
    versions.bump_version(comment)
    infix = "own" if auth_user.user_id == comment.user_id else "any"
    text = body.require("text")
    auth.verify_privilege(auth_user, "comments:edit:%s" % infix)
    comments.update_comment_text(comment, text)
    comment.last_edit_time = util.utcnow()
    db.session.commit()
    return _serialize(comment, auth_user, fields)


@router.delete(
    "/comment/{comment_id}",
    response_model=resources.Empty,
    summary="Delete a comment",
    openapi_extra=request_body(VersionOnly),
)
def delete_comment(
    comment_id: str,
    auth_user: CurrentUser,
    body: Annotated[VersionOnly, Depends(read_body(VersionOnly))],
) -> Any:
    """
    Deletes existing comment.

    Errors:

    - the version is outdated
    - the comment does not exist
    - privileges are too low
    """
    comment = _get_comment(comment_id)
    versions.verify_version(comment, body.require("version"))
    infix = "own" if auth_user.user_id == comment.user_id else "any"
    auth.verify_privilege(auth_user, "comments:delete:%s" % infix)
    db.session.delete(comment)
    db.session.commit()
    return {}


@router.put(
    "/comment/{comment_id}/score",
    response_model=resources.Comment,
    summary="Rate a comment",
    openapi_extra=request_body(ScoreUpdate),
)
def set_comment_score(
    comment_id: str,
    auth_user: Annotated[model.User, Depends(require("comments:score"))],
    fields: Fields,
    body: Annotated[ScoreUpdate, Depends(read_body(ScoreUpdate))],
) -> Any:
    """
    Updates score of authenticated user for given comment. Valid scores are -1,
    0 and 1.

    Errors:

    - comment does not exist
    - score is invalid
    - privileges are too low
    """
    score = body.require("score")
    comment = _get_comment(comment_id)
    scores.set_score(comment, auth_user, score)
    db.session.commit()
    return _serialize(comment, auth_user, fields)


@router.delete(
    "/comment/{comment_id}/score",
    response_model=resources.Comment,
    summary="Take back the rating of a comment",
)
def delete_comment_score(
    comment_id: str,
    auth_user: Annotated[model.User, Depends(require("comments:score"))],
    fields: Fields,
) -> Any:
    """
    Removes the requester's rating of the comment, as rating it with a score
    of 0 does.

    Errors:

    - the comment does not exist
    - privileges are too low
    """
    comment = _get_comment(comment_id)
    scores.delete_score(comment, auth_user)
    db.session.commit()
    return _serialize(comment, auth_user, fields)
