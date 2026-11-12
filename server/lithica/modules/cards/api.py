"""The routes of the cards module, and what they return."""

from collections.abc import Sequence
from typing import Annotated, Any

import sqlalchemy as sa
from fastapi import APIRouter, Depends
from pydantic import Field
from starlette.responses import FileResponse

from lithica import db, errors, model
from lithica.api import resources
from lithica.api.dependencies import get_user, require
from lithica.api.routing import ERROR_RESPONSES, ApiRouter
from lithica.func import documents, file_types, files, posts
from lithica.modules.cards import card as card_format
from lithica.modules.cards import filename, reading, view
from lithica.modules.cards.model import (
    Card as CardRow,
)
from lithica.modules.cards.model import (
    CardLorebook,
)
from lithica.modules.cards.model import (
    Lorebook as LorebookRow,
)


class CardNotFoundError(errors.NotFoundError):
    pass


class CardSummary(resources.Resource):
    """The summary of a post's card, for lists of posts: the post field `card`."""

    name: str | None = Field(description="The card's name, shortened.")
    creator: str | None = Field(description="The card's creator, shortened.")
    spec: str = Field(description="`v1`, `v2` or `v3`.")
    format: str | None = Field(description="The file: `png` or `charx`.")
    greeting_count: int | None = Field(
        description="The first message and the alternate greetings."
    )
    lorebook_entry_count: int | None = Field(
        description="The entries of the card's lorebook."
    )


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


class LorebookLink(resources.Resource):
    id: int
    name: str
    entry_count: int


class LorebookAnswer(LorebookLink):
    spec: str
    lorebook: Lorebook
    card_ids: list[int]


class LorebookNotFoundError(errors.NotFoundError):
    pass


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
    lorebooks: list[LorebookLink] = Field(default_factory=list[LorebookLink])
    lorebook: Lorebook | None = Field(description="`null` for a card without one.")


def _post(post_id: str) -> model.Post:
    try:
        number = int(post_id)
    except ValueError:
        raise posts.InvalidPostIdError("Invalid post ID: %r." % post_id) from None
    return posts.get_post_by_id(number)


def card_field(post: model.Post, user: model.User) -> dict[str, Any] | None:
    return card_fields([post], user)[post.post_id]


def card_fields(
    posts: Sequence[model.Post], _user: model.User
) -> dict[int, dict[str, Any] | None]:
    """Current summaries, file format and linked entry totals in one query."""
    ids = [post.post_id for post in posts]
    found: dict[int, dict[str, Any] | None] = dict.fromkeys(ids)
    if not ids:
        return found
    entries = (
        sa.select(sa.func.coalesce(sa.func.sum(LorebookRow.entries), 0))
        .select_from(CardLorebook)
        .join(LorebookRow, LorebookRow.post_id == CardLorebook.lorebook_post_id)
        .where(CardLorebook.card_post_id == CardRow.post_id)
        .correlate(CardRow)
        .scalar_subquery()
    )
    file_format = (
        sa.select(model.PostContent.payload["format"].as_string())
        .where(
            model.PostContent.post_id == CardRow.post_id,
            model.PostContent.kind.in_(card_format.KINDS),
        )
        .order_by(model.PostContent.post_content_id)
        .limit(1)
        .correlate(CardRow)
        .scalar_subquery()
    )
    for row, format_, count in db.session.execute(
        sa.select(CardRow, file_format, entries).where(CardRow.post_id.in_(ids))
    ):
        found[row.post_id] = {
            "name": row.name,
            "creator": row.creator,
            "spec": card_format.SPEC_NAMES[row.spec],
            "format": format_,
            "greetingCount": row.greetings,
            "lorebookEntryCount": count,
        }
    return found


def _card_name(post: model.Post) -> str:
    row = db.session.get(CardRow, post.post_id)
    if row is not None:
        return row.name
    # An unconverted card still has its original download. Read only its
    # name from the file data, without the obsolete extracted summary.
    payload = model.PostContent.payload
    names = db.session.execute(
        sa.select(
            payload[("card", "data", "name")].as_string(),
            payload[("card", "name")].as_string(),
        )
        .where(
            model.PostContent.post_id == post.post_id,
            model.PostContent.kind.in_(card_format.KINDS),
        )
        .order_by(model.PostContent.post_content_id)
        .limit(1)
    ).first()
    if names is None:
        raise CardNotFoundError("Post %d has no character card." % post.post_id)
    return next((name for name in names if isinstance(name, str)), "")


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
    Returns the current document of a character card, read for a viewer: the same fields
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
    if post.kind != "card":
        raise CardNotFoundError("Post %d has no character card." % post.post_id)
    try:
        document = documents.get(post)
    except documents.DocumentNotFoundError:
        raise CardNotFoundError("The card hasn't been converted.") from None
    data = document.data
    books = reading.visible_books(post.post_id)
    merged = reading.merge_books([book["book"] for _, book in books])
    # The normaliser retains the file-format meaning of the existing answer.
    file_format = db.session.scalar(
        sa.select(model.PostContent.payload["format"].as_string())
        .where(
            model.PostContent.post_id == post.post_id,
            model.PostContent.kind.in_(card_format.KINDS),
        )
        .order_by(model.PostContent.post_content_id)
        .limit(1)
    )
    result = view.normalised(
        post.post_id, data["spec"], {"card": data["card"], "format": file_format}
    )
    result["lorebook"] = (
        view.normalised_lorebook(merged) if merged is not None else None
    )
    result["lorebooks"] = [
        {
            "id": id_,
            "name": card_format.as_text(book["book"].get("name")),
            "entryCount": len(
                card_format.lorebook_entries({"character_book": book["book"]})
            ),
        }
        for id_, book in books
    ]
    return result


@cards.get(
    "/lorebook/{post_id}", response_model=LorebookAnswer, summary="Get a lorebook"
)
def get_lorebook(
    post_id: str, _auth_user: Annotated[model.User, Depends(require("posts:view"))]
) -> dict[str, Any]:
    """Return the current lorebook document, normalised as in a card answer.

    Includes its id, name, entryCount, format spec (`v2` or `v3`) and
    visible linking cardIds in ascending order. Unlisted linking cards
    remain accessible; the site's NSFW visibility rules still apply.

    Errors:

    - the post is hidden, missing, or not a lorebook (404 LorebookNotFoundError)
    - the post has no lorebook document (404 LorebookNotFoundError)
    - privileges are too low (403)
    """
    try:
        post = _post(post_id)
        if post.kind != "lorebook":
            raise LorebookNotFoundError("Lorebook not found.")
        document = documents.get(post)
    except (posts.PostNotFoundError, documents.DocumentNotFoundError):
        raise LorebookNotFoundError("Lorebook not found.") from None
    book = view.normalised_lorebook(document.data["book"])
    card_ids = list(
        db.session.scalars(
            sa.select(model.Post.post_id)
            .join(CardLorebook, CardLorebook.card_post_id == model.Post.post_id)
            .where(
                CardLorebook.lorebook_post_id == post.post_id, model.Post.kind == "card"
            )
            .order_by(model.Post.post_id)
        )
    )
    return {
        "id": post.post_id,
        "spec": card_format.SPEC_NAMES[document.data["spec"]],
        "name": book["name"],
        "entryCount": len(book["entries"]),
        "lorebook": book,
        "cardIds": card_ids,
    }


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
    if post.mime_type is None:
        raise CardNotFoundError("The file of post %d is missing." % post.post_id)
    # only the name: the card may be megabytes, and the file is what is sent
    name = _card_name(post)
    stored = files.get(posts.get_post_content_path(post))
    if stored is None:
        raise CardNotFoundError("The file of post %d is missing." % post.post_id)
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
