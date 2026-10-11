"""
What the API returns, as models for the OpenAPI document.

These describe the output of the serializers in `lithica.func`; they do not
produce it. `schemas.ResponseModel` explains why, and why no field is marked
as required.
"""

from datetime import datetime
from typing import Any

from pydantic import ConfigDict, Field
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
    user: MicroUser
    token: str
    note: str | None
    enabled: bool
    expiration_time: datetime | None
    version: int
    creation_time: datetime
    last_edit_time: datetime | None
    last_usage_time: datetime | None


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
    thumbnail_url: str


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


class Post(Resource):
    version: int
    id: int
    creation_time: datetime
    last_edit_time: datetime | None
    safety: str
    source: str | None
    type: str
    mime_type: str
    checksum: str
    checksum_md5: str | None = Field(alias="checksumMD5")
    file_size: int | None
    canvas_width: int | None
    canvas_height: int | None
    content_url: str
    thumbnail_url: str
    flags: list[str]
    tags: list[MicroTag]
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
    favorited_by: list[MicroUser]
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


class Info(Resource):
    post_count: int
    disk_usage: int | None = Field(
        description="Bytes used by the data directory; `null` until measured."
    )
    server_time: datetime
    config: InfoConfig
    featured_post: Post | None = Field(
        description="Present only if the requester may see the featured post."
    )
    featuring_user: User | None
    featuring_time: datetime | None


class PasswordResetResult(Resource):
    password: str = Field(description="The new, generated password.")


class UploadToken(Resource):
    token: str
