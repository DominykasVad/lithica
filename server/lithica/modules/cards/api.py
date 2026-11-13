"""The routes of the cards module, and what they return."""

from collections.abc import Sequence
from typing import Annotated, Any

import sqlalchemy as sa
import sqlalchemy.orm as sa_orm
from fastapi import APIRouter, Depends, Request
from pydantic import Field
from starlette.responses import FileResponse, Response

from lithica import db, errors, model
from lithica.api import resources
from lithica.api.dependencies import (
    RequestDataParam,
    fields_of,
    get_user,
    read_body,
    require,
)
from lithica.api.routing import ERROR_RESPONSES, ApiRouter
from lithica.api.schemas import (
    Bool,
    Int,
    RequestModel,
    Str,
    optional,
    request_body,
    required,
)
from lithica.func import documents, file_types, file_uploads, files, mime, posts
from lithica.modules.cards import card as card_format
from lithica.modules.cards import filename, pictures, reading, replacement, view
from lithica.modules.cards.model import (
    Card as CardRow,
)
from lithica.modules.cards.model import (
    CardLorebook,
)
from lithica.modules.cards.model import (
    Lorebook as LorebookRow,
)

CardNotFoundError = replacement.CardNotFoundError


class CardAvatar(resources.Resource):
    id: int
    thumbnail_url: str | None
    content_url: str | None


class CardSummary(resources.Resource):
    """The summary of a post's card, for lists of posts: the post field `card`."""

    name: str | None = Field(description="The card's name, shortened.")
    creator: str | None = Field(description="The card's creator, shortened.")
    spec: str = Field(description="`v1`, `v2` or `v3`.")
    format: str | None = Field(description="The file: `png` or `charx`.")
    avatar: CardAvatar | None
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
    format: str | None = Field(
        description="The file the card came in: png or charx; null without a file."
    )
    avatar: CardAvatar | None
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
    file_ids = {post.post_id for post in posts if post.mime_type is not None}
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
    avatars = sa.select(model.Post).where(model.Post.kind == "media").subquery()
    avatar = sa_orm.aliased(model.Post, avatars)
    for row, format_, count, picture in db.session.execute(
        sa.select(CardRow, file_format, entries, avatar)
        .outerjoin(avatar, avatar.post_id == CardRow.avatar_post_id)
        .where(CardRow.post_id.in_(ids))
        .options(sa_orm.lazyload("*"))
    ):
        found[row.post_id] = {
            "name": row.name,
            "creator": row.creator,
            "spec": card_format.SPEC_NAMES[row.spec],
            "format": format_ if row.post_id in file_ids else None,
            "avatar": avatar_resource(picture),
            "greetingCount": row.greetings,
            "lorebookEntryCount": count,
        }
    return found


def avatar_resource(post: model.Post | None) -> dict[str, object] | None:
    if post is None:
        return None
    return {
        "id": post.post_id,
        "thumbnailUrl": posts.get_post_thumbnail_url(post),
        "contentUrl": posts.get_post_content_url(post),
    }


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
    result["format"] = file_format if posts.has_file(post) else None
    result["lorebook"] = (
        view.normalised_lorebook(merged) if merged is not None else None
    )
    row = db.session.get(CardRow, post.post_id)
    result["avatar"] = avatar_resource(
        posts.try_get_post_by_id(row.avatar_post_id)
        if row is not None and row.avatar_post_id is not None
        else None
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


class CardFileInput(RequestModel):
    content_token: Str = optional()
    content_url: Str = optional()


class CardFileReplace(CardFileInput):
    version: Int = required()
    keep_old_picture: Bool = True


class CardFileReplaced(resources.Resource):
    post: resources.Post
    kept_post_id: int | None
    same_picture: bool


@cards.put(
    "/post/{post_id}/file",
    operation_id="replace_card_file",
    response_model=CardFileReplaced,
    openapi_extra=request_body(CardFileReplace, "content"),
    summary="Replace a character card's file",
)
def replace_card_file(
    post_id: str,
    auth_user: Annotated[model.User, Depends(require("posts:edit:content"))],
    fields: Annotated[list[str], Depends(fields_of(posts.PostSerializer))],
    data: RequestDataParam,
    body: Annotated[CardFileReplace, Depends(read_body(CardFileReplace))],
) -> dict[str, Any]:
    """Replace a converted card's file against its post version.

    keepOldPicture defaults to true. Differing old pictures become related
    media when permitted; identical pixels are never kept. Creates a document
    version noted `File replaced.` only when data changes. Refused files leave
    database state and stored files unchanged; stale post versions give 409.
    """
    post = _post(post_id)
    kept_id, same = replacement.replace(
        post,
        data.get_file("content", use_video_downloader=False),
        body.require("version"),
        body.keep_old_picture,
        auth_user,
    )
    db.session.commit()
    return {
        "post": posts.serialize_post(post, auth_user, fields),
        "keptPostId": kept_id,
        "samePicture": same,
    }


class CardFileComparison(resources.Resource):
    same_pixels: bool
    similarity: float | None
    old_picture: bool
    new_picture: bool


@cards.post(
    "/post/{post_id}/file/compare",
    operation_id="compare_card_file",
    response_model=CardFileComparison,
    openapi_extra=request_body(CardFileInput, "content"),
    summary="Compare a new card file's picture with the current one",
)
def compare_card_file(
    post_id: str,
    _auth_user: Annotated[model.User, Depends(require("posts:edit:content"))],
    data: RequestDataParam,
) -> pictures.Comparison:
    """Compare RGBA pixels and advisory greyscale signatures without writes.

    Uses the same file inputs as replacement. Similarity is rounded to two
    decimals, or null when no signature is available; it never decides keeping.
    """
    post = _post(post_id)
    replacement.card_document(post)
    return pictures.compare(
        replacement.old_picture(post),
        pictures.picture(data.get_file("content", use_video_downloader=False)),
    )


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


class CardPictureInput(RequestModel):
    content_token: Str = required()


@downloads.post(
    "/file-picture",
    operation_id="get_card_file_picture",
    response_class=Response,
    openapi_extra=request_body(CardPictureInput),
    summary="Get a temporary card file's picture",
    responses={
        200: {
            "description": "The card's picture, with its detected image type.",
            "content": {"image/*": {"schema": {"type": "string", "format": "binary"}}},
        }
    },
)
def get_card_file_picture(
    request: Request,
    _auth_user: Annotated[model.User, Depends(require("uploads:create"))],
    body: Annotated[CardPictureInput, Depends(read_body(CardPictureInput))],
) -> Response:
    """Return a temporary PNG card's picture or a CHARX's engine-image icon.

    Accepts only a contentToken in the body. Returns 404 when no picture
    exists, with nosniff, sandbox CSP and no-store headers on image responses.
    """
    if request.query_params:
        raise errors.ValidationError(
            "This route accepts contentToken only in the request body."
        )
    token = body.require("content_token")
    stored = file_uploads.get(token)
    if stored is None:
        raise errors.MissingRequiredFileError("Required file 'content' is missing.")
    picture = pictures.picture(stored)
    if picture is None:
        raise CardNotFoundError("The file has no picture.")
    return Response(
        picture,
        media_type=mime.get_mime_type(picture),
        headers={
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; sandbox",
            "Cache-Control": "no-store",
        },
    )


# both, under the module's path; a plain router, so that the download is not
# wrapped as JSON
router = APIRouter()
router.include_router(cards)
router.include_router(downloads)
