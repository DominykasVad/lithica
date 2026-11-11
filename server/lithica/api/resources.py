"""
What the API returns, as models for the OpenAPI document.

These describe the output of the serializers in `lithica.func`; they do not
produce it. `schemas.ResponseModel` explains why, and why no field is marked
as required.
"""

from datetime import datetime
from typing import Any, Literal

from pydantic import ConfigDict, Field, JsonValue
from pydantic.alias_generators import to_camel

from lithica.api.schemas import ResponseModel, _nothing_is_required


class Resource(ResponseModel):
    """A response model whose fields are camelCase on the wire."""

    model_config = ConfigDict(
        extra="forbid",
        alias_generator=to_camel,
        json_schema_extra=_nothing_is_required,
    )


class Empty(Resource):
    """An empty object: the request succeeded and there is nothing to return."""


class Unpaged[T](Resource):
    """A list that is always returned whole."""

    results: list[T]


class Paged[T](Resource):
    """One page of a search result."""

    query: str = Field(description="The search query, as it was sent.")
    offset: int = Field(description="How many results were skipped.")
    limit: int = Field(description="The page size.")
    total: int = Field(description="How many results the query has in all.")
    results: list[T]


class MicroUser(Resource):
    name: str
    avatar_url: str


class User(Resource):
    version: int
    name: str
    email: str | bool | None = Field(
        description="`false` when the requester may not see it, "
        "`null` when the user has none."
    )
    rank: str
    last_login_time: datetime | None
    creation_time: datetime
    avatar_style: str
    avatar_url: str
    comment_count: int
    uploaded_post_count: int
    liked_post_count: int | bool = Field(
        description="`false` unless the requester is this user."
    )
    disliked_post_count: int | bool = Field(
        description="`false` unless the requester is this user."
    )
    favorite_post_count: int


class UserToken(Resource):
    id: int = Field(description="Names the token in the paths of its routes.")
    user: MicroUser
    token: str | None = Field(
        description="The token's value: only in the response that created the "
        "token, `null` everywhere else."
    )
    note: str | None
    enabled: bool
    expiration_time: datetime | None
    version: int
    creation_time: datetime
    last_edit_time: datetime | None
    last_usage_time: datetime | None


class AppToken(Resource):
    id: int = Field(description="Names the token in the paths of its routes.")
    user: MicroUser
    name: str
    rights: list[str] = Field(
        description="Names of its rights, as `appTokenRights` of `GET /info` lists "
        "them."
    )
    token: str | None = Field(
        description="The token's value: only in the response that created the "
        "token, `null` everywhere else."
    )
    enabled: bool
    expiration_time: datetime | None
    creation_time: datetime
    last_edit_time: datetime | None
    last_usage_time: datetime | None
    version: int


class TagCategory(Resource):
    version: int
    name: str
    color: str
    usages: int
    order: int
    default: bool


class MicroTag(Resource):
    names: list[str]
    category: str
    usages: int


class Tag(Resource):
    version: int
    names: list[str]
    category: str
    implications: list[MicroTag]
    suggestions: list[MicroTag]
    creation_time: datetime
    last_edit_time: datetime | None
    usages: int
    description: str | None


class TagSibling(Resource):
    tag: Tag
    occurrences: int = Field(description="How many posts have both tags.")


class MicroPost(Resource):
    id: int
    thumbnail_url: str | None


class Note(Resource):
    polygon: list[list[float]] = Field(
        description="Points of the outline, each coordinate within 0 to 1."
    )
    text: str


class Comment(Resource):
    version: int
    id: int
    post_id: int
    user: MicroUser | None
    text: str
    creation_time: datetime
    last_edit_time: datetime | None
    score: int
    own_score: int


class PoolCategory(Resource):
    version: int
    name: str
    color: str
    usages: int
    default: bool


class MicroPool(Resource):
    id: int
    names: list[str]
    category: str
    description: str | None
    post_count: int


class Pool(Resource):
    version: int
    id: int
    names: list[str]
    category: str
    posts: list[MicroPost]
    creation_time: datetime
    last_edit_time: datetime | None
    post_count: int
    description: str | None


class ExternalId(Resource):
    host: str
    id: str


class TypedRelationType(Resource):
    name: str
    from_kinds: list[str] | None
    to_kinds: list[str] | None


class TypedRelationPost(Resource):
    id: int
    kind: str
    type: str | None
    mime_type: str | None
    safety: str
    nsfw: bool
    content_url: str | None
    thumbnail_url: str | None


class TypedRelation(Resource):
    id: int
    type: str
    label: str | None
    direction: Literal["out", "in"]
    creation_time: datetime
    post: TypedRelationPost


class TypedRelations(Resource):
    results: list[TypedRelation]


class Post(Resource):
    listed: bool = Field(
        description="Whether searches include this post by default; "
        "unlisted is not private."
    )
    external_ids: list[ExternalId]
    kind: str = Field(
        description="media or a kind a module of the site registers, "
        "as postKinds of GET /info lists them; a post may carry "
        "the kind of a module that is now switched off."
    )
    version: int
    id: int
    creation_time: datetime
    last_edit_time: datetime | None
    safety: str
    source: str | None
    type: str | None
    mime_type: str | None
    checksum: str | None
    checksum_md5: str | None = Field(alias="checksumMD5")
    file_size: int | None
    canvas_width: int | None
    canvas_height: int | None
    content_url: str | None
    thumbnail_url: str | None
    flags: list[str]
    tags: list[MicroTag]
    nsfw: bool = Field(
        description="Whether the post carries the site's NSFW tag (nsfwTag in "
        "GET /info) or a tag that implies it, directly or through others."
    )
    relations: list[MicroPost]
    user: MicroUser | None
    score: int
    own_score: int
    own_favorite: bool
    tag_count: int
    favorite_count: int
    comment_count: int
    note_count: int
    relation_count: int
    feature_count: int
    last_feature_time: datetime | None
    favorited_by: list[MicroUser] = Field(
        description="The users who favourited the post, in the order they did "
        "(and by user for the same time)."
    )
    has_custom_thumbnail: bool
    notes: list[Note]
    comments: list[Comment]
    pools: list[MicroPool]
    content_kinds: list[str] = Field(
        description="The kinds of content extracted from the post's file by the "
        "modules of this installation. Empty without modules."
    )


class PostContent(Resource):
    """One piece of content a module read out of a post's file."""

    kind: str = Field(description="What the content is; names the module's format.")
    schema_version: int = Field(
        description="The version of that format the content was extracted with."
    )
    extracted_at: datetime
    content: Any = Field(
        description="The content, in the shape the module that owns the kind gives it."
    )


class PostsAround(Resource):
    prev: Post | None
    next: Post | None


class SimilarPost(Resource):
    distance: float = Field(description="0 to 1; lower is more similar.")
    post: Post


class ImageSearchResult(Resource):
    exact_post: Post | None
    similar_posts: list[SimilarPost]


class Snapshot(Resource):
    operation: str
    type: str
    id: int | str
    user: MicroUser | None
    # Any: depends on the operation and the resource type
    data: Any
    time: datetime


class InfoConfig(Resource):
    name: str
    user_name_regex: str
    password_regex: str
    tag_name_regex: str
    tag_category_name_regex: str
    default_user_rank: str
    enable_safety: bool
    contact_email: str | None
    can_send_mails: bool
    privileges: dict[str, str]


class AcceptedType(Resource):
    mime: list[str] = Field(
        description="Its MIME type(s), as the post's `mimeType` says them."
    )
    extensions: list[str] = Field(
        description="Usual file name extensions, without the dot; the one a stored "
        "file gets first."
    )


class Features(Resource):
    pools: bool
    favorites: bool
    scores: bool
    notes: bool
    comments: bool


class Info(Resource):
    features: Features
    share_links_nsfw: bool
    typed_relation_types: list[TypedRelationType]
    post_kinds: list[str] = Field(
        description="Post kinds: media, then loaded module post kinds."
    )
    post_count: int
    disk_usage: int | None = Field(
        description="Bytes used by the data directory; `null` until measured."
    )
    server_time: datetime
    modules: list[str] = Field(
        description="Names of the modules that are switched on, in config order."
    )
    config: InfoConfig
    app_token_rights: dict[str, list[str]] = Field(
        description="The rights an app token can carry, each with the privileges it "
        "lists (named as in `config.privileges`). A request made with an app token "
        "may use a privilege only when one of its rights lists it and the user's "
        "rank grants it, and never one about accounts or tokens."
    )
    max_upload_size: int | None = Field(
        description="The largest request the server takes, in bytes, as it checks it "
        "(`max_upload_size`); `null` if there is no limit. A larger one is refused "
        "with 413 `RequestTooLargeError`."
    )
    accepted_types: list[AcceptedType] = Field(
        description="The types of file a post can be made from on this site: the "
        "engine's, then those of the modules switched on. A hint for clients, to "
        "point out at once a file that would be refused: the server decides by the "
        "file's content, not by its name or the type a browser gives it."
    )
    visibility: Literal["open", "nsfw-login", "login"] = Field(
        description="Who sees what without logging in (`visibility`): `open`, as the "
        "privileges say; `nsfw-login`, posts carrying `nsfwTag` (or a tag that "
        "implies it) do not exist for anonymous users; `login`, nothing but logging "
        "in, password reset and this."
    )
    nsfw_tag: str = Field(
        description="The tag that marks a post as not safe for work (`nsfw_tag`)."
    )
    nsfw_hides_names: bool = Field(
        description="Whether clients hide the name and creator of a NSFW post's "
        "card, as they hide its picture and text, from a viewer who has not chosen "
        "to see NSFW posts (`nsfw_hide_names`). A hint for clients: the API gives "
        "the names either way."
    )
    featured_post: Post | None = Field(
        description="Present only if the requester may see the featured post."
    )
    featuring_user: User | None
    featuring_time: datetime | None


class PasswordResetResult(Resource):
    password: str = Field(description="The new, generated password.")


class UploadToken(Resource):
    token: str


class ShareLink(Resource):
    id: int
    post_id: int
    user: MicroUser
    note: str | None
    creation_time: datetime
    expires_at: datetime | None
    expired: bool
    url: str


class SiteSetting(Resource):
    name: str
    type: Literal["boolean", "integer", "string", "choice", "list"]
    value: JsonValue
    starting_value: JsonValue
    stored: bool
    runtime: bool
    choices: list[str] | None = None
    min: int | None = None


class SiteSettings(Resource):
    version: int
    file_links_signed: bool
    settings: list[SiteSetting]


class Job(Resource):
    id: int
    type: str
    status: Literal["queued", "running", "done", "failed"]
    attempts: int
    max_attempts: int
    run_after: datetime
    claimed_by: str | None
    lease_until: datetime | None
    creation_time: datetime
    start_time: datetime | None
    finish_time: datetime | None
    last_error: str | None
    user: MicroUser | None


class JobDetail(Job):
    payload: dict[str, JsonValue]
