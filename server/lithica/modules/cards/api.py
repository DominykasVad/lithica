"""The routes of the cards module, and what they return."""

from typing import Annotated, Any, cast

import sqlalchemy.orm as sa_orm
from fastapi import APIRouter, Depends
from pydantic import Field
from starlette.responses import FileResponse

from lithica import db, errors, model
from lithica.api import resources
from lithica.api.dependencies import get_user, require
from lithica.api.routing import ERROR_RESPONSES, ApiRouter
from lithica.func import file_types, files, posts
from lithica.modules.cards import card as card_format
from lithica.modules.cards import filename, view


class CardNotFoundError(errors.NotFoundError):
    pass


class LorebookEntry(resources.Resource):
    keys: list[str]
    secondary_keys: list[str]
    content: str
    enabled: bool | None
    order: float | None = Field(description="`insertion_order` of the card.")
    name: str
    comment: str
    constant: bool | None
    selective: bool | None
    case_sensitive: bool | None
    use_regex: bool | None
    position: str | None
    priority: float | None
    id: float | str | None
    extensions: dict[str, Any]


class Lorebook(resources.Resource):
    name: str
    description: str
    scan_depth: float | None
    token_budget: float | None
    recursive_scanning: bool | None
    extensions: dict[str, Any]
    entries: list[LorebookEntry]


class Card(resources.Resource):
    post_id: int
    spec: str = Field(description="The version of the card format: v1, v2 or v3.")
    format: str = Field(description="The file the card came in: png or charx.")
    name: str
    description: str
    personality: str
    scenario: str
    first_message: str
    alternate_greetings: list[str]
    example_messages: str
    creator_notes: str
    system_prompt: str
    post_history_instructions: str
    tags: list[str]
    creator: str
    character_version: str
    lorebook: Lorebook | None = Field(description="`null` for a card without one.")


def _post(post_id: str) -> model.Post:
    try:
        number = int(post_id)
    except ValueError:
        raise posts.InvalidPostIdError("Invalid post ID: %r." % post_id) from None
    return posts.get_post_by_id(number)


def _card_row(post: model.Post) -> model.PostContent:
    """The card of a post: the first row of a card kind, with its payload."""
    row = (
        db.session.query(model.PostContent)
        .filter(model.PostContent.post_id == post.post_id)
        .filter(model.PostContent.kind.in_(card_format.KINDS))
        .order_by(model.PostContent.post_content_id)
        .options(sa_orm.undefer(model.PostContent.payload))
        .first()
    )
    if row is None:
        raise CardNotFoundError("Post %d has no character card." % post.post_id)
    return row


def card_field(post: model.Post, _user: model.User) -> dict[str, Any] | None:
    """
    The post field `card`: the summary of the post's card, or null. It reads
    the summary alone, not the card, which may be megabytes.
    """
    row = (
        db.session.query(
            model.PostContent.kind,
            model.PostContent.payload["format"].as_string(),
            model.PostContent.payload["summary"],
        )
        .filter(model.PostContent.post_id == post.post_id)
        .filter(model.PostContent.kind.in_(card_format.KINDS))
        .order_by(model.PostContent.post_content_id)
        .first()
    )
    if row is None:
        return None
    kind, file_format, stored = row
    # absent for a card stored before there were summaries
    summary = cast(dict[str, Any], stored) if isinstance(stored, dict) else {}
    return {
        "name": summary.get("name"),
        "creator": summary.get("creator"),
        "spec": card_format.SPEC_NAMES[kind],
        "format": file_format,
        "greetingCount": summary.get("greetings"),
        "lorebookEntryCount": summary.get("lorebookEntries"),
    }


cards = ApiRouter()


@cards.get(
    "/post/{post_id}",
    response_model=Card,
    summary="Get the character card of a post",
)
def get_card(
    post_id: str,
    _auth_user: Annotated[model.User, Depends(require("posts:view"))],
) -> dict[str, Any]:
    """
    Returns the character card of a post, read for a viewer: the same fields
    for every version of the card format (V1, V2, V3) and for both files a
    card comes in (PNG, CHARX). Every field is present; a text the card does
    not have is empty, and a lorebook it does not have is `null`.

    The card as its file had it is the post's extracted content,
    `GET /post/<id>/content`.

    Errors:

    - the post does not exist
    - the post has no character card
    - privileges are too low
    """
    post = _post(post_id)
    row = _card_row(post)
    return view.normalised(post.post_id, row.kind, row.payload)


# The download answers with the file, not with JSON, so it does not ask the
# request to accept JSON and does not go through the JSON router.
downloads = APIRouter(dependencies=[Depends(get_user)], responses=ERROR_RESPONSES)


@downloads.get(
    "/post/{post_id}/download",
    summary="Download the character card of a post",
    response_class=FileResponse,
    responses={
        200: {
            "description": "The stored file, as it was uploaded.",
            "content": {
                "application/octet-stream": {
                    "schema": {"type": "string", "format": "binary"}
                }
            },
        }
    },
)
def download_card(
    post_id: str,
    _auth_user: Annotated[model.User, Depends(require("posts:view"))],
) -> FileResponse:
    """
    Returns the file of a post that has a character card, unchanged: the PNG
    picture or the CHARX file that was uploaded. It is sent as an attachment
    named after the character, with the extension of the stored file
    (`Content-Disposition`, with `filename*` for a name that is not ASCII),
    or `card-<post id>` where the card's name cannot be a file name.

    Unlike the rest of the API, this route answers with the file, so a
    request does not have to accept JSON; its errors are JSON all the same.

    Errors:

    - the post does not exist
    - the post has no character card, or its file is missing
    - privileges are too low
    """
    post = _post(post_id)
    row = _card_row(post)
    stored = files.get(posts.get_post_content_path(post))
    if stored is None:
        raise CardNotFoundError("The file of post %d is missing." % post.post_id)
    name = view.normalised(post.post_id, row.kind, row.payload)["name"]
    extension = file_types.get_extension(post.mime_type) or "dat"
    return FileResponse(
        stored.path,
        media_type=post.mime_type,
        headers={
            "Content-Disposition": filename.content_disposition(
                name, post.post_id, extension
            ),
            # the file is somebody's upload: a browser must not guess at it
            "X-Content-Type-Options": "nosniff",
        },
    )


# both, under the module's path; a plain router, so that the download is not
# wrapped as JSON
router = APIRouter()
router.include_router(cards)
router.include_router(downloads)
