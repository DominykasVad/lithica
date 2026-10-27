from typing import Annotated, Any, cast

from fastapi import Depends, Query

from lithica import db, errors, model, search
from lithica.api import resources
from lithica.api.dependencies import (
    CurrentUser,
    PageParams,
    RequestDataParam,
    fields_of,
    read_body,
    require,
)
from lithica.api.dependencies import search as run_search
from lithica.api.routing import ApiRouter
from lithica.api.schemas import (
    AnyList,
    Bool,
    Int,
    IntList,
    RequestModel,
    Str,
    StrList,
    VersionOnly,
    optional,
    request_body,
    required,
)
from lithica.func import (
    auth,
    favorites,
    posts,
    scores,
    snapshots,
    util,
    versions,
)

# checked before the endpoint runs (see fields_of)
CheckedFields = Annotated[list[str], Depends(fields_of(posts.PostSerializer))]

router = ApiRouter(tags=["Posts"])

_search_executor_config = search.configs.PostSearchConfig()
_search_executor = search.Executor(_search_executor_config)


class PostCreate(RequestModel):
    # the content, when it is not uploaded as the `content` part: a URL to
    # fetch it from, or the token of a temporary upload
    content_url: Str = optional()
    content_token: Str = optional()
    thumbnail_url: Str = optional()
    thumbnail_token: Str = optional()
    safety: Str = required()
    tags: StrList = []
    source: Str = ""
    relations: IntList = []
    notes: AnyList = []
    # when left out, the flags are worked out from the content
    flags: StrList = optional()
    anonymous: Bool = False


class PostUpdate(RequestModel):
    version: Int = required()
    content_url: Str = optional()
    content_token: Str = optional()
    thumbnail_url: Str = optional()
    thumbnail_token: Str = optional()
    safety: Str = optional()
    tags: StrList = optional()
    source: Str = optional()
    relations: IntList = optional()
    notes: AnyList = optional()
    flags: StrList = optional()


class PostMerge(RequestModel):
    remove: Int = required()
    merge_to: Int = required()
    remove_version: Int = required()
    merge_to_version: Int = required()
    replace_content: Bool = required()


class PostFeature(RequestModel):
    id: Int = required()


class ScoreUpdate(RequestModel):
    score: Int = required()


class ReverseSearch(RequestModel):
    content_url: Str = optional()
    content_token: Str = optional()


def _get_post_id(post_id: str) -> int:
    try:
        return int(post_id)
    except ValueError:
        raise posts.InvalidPostIdError("Invalid post ID: %r." % post_id) from None


def _get_post(post_id: str) -> model.Post:
    return posts.get_post_by_id(_get_post_id(post_id))


# Any: the serializer's output, which the response model describes
def _serialize_post(
    post: model.Post | None, auth_user: model.User, fields: list[str]
) -> Any:
    return posts.serialize_post(post, auth_user, options=fields)


def create_snapshots_for_post(
    post: model.Post, new_tags: list[model.Tag], user: model.User | None
) -> None:
    snapshots.create(post, user)
    for tag in new_tags:
        snapshots.create(tag, user)


@router.get(
    "/posts", response_model=resources.Paged[resources.Post], summary="List posts"
)
def get_posts(
    auth_user: Annotated[model.User, Depends(require("posts:list"))],
    fields: CheckedFields,
    page: PageParams,
) -> Any:
    """
    Searches for posts.

    The tokens `query` understands are listed under "Post search" in doc/API.md.

    Errors:

    - privileges are too low
    """
    _search_executor_config.user = auth_user
    return run_search(
        _search_executor, page, lambda post: _serialize_post(post, auth_user, fields)
    )


@router.post(
    "/posts",
    response_model=resources.Post,
    summary="Create a post",
    openapi_extra=request_body(PostCreate, "content", "thumbnail"),
)
def create_post(
    auth_user: CurrentUser,
    fields: CheckedFields,
    data: RequestDataParam,
    body: Annotated[PostCreate, Depends(read_body(PostCreate))],
) -> Any:
    """
    Creates a new post. If specified tags do not exist yet, they will be
    automatically created. Tags created automatically have no implications, no
    suggestions, one name and their category is set to the first tag category
    found. Safety must be any of `"safe"`, `"sketchy"` or `"unsafe"`. Relations
    must contain valid post IDs. If `<flag>` is omitted, they will be defined by
    default (`"loop"` will be set for all video posts, and `"sound"` will be
    auto-detected). Sending empty `thumbnail` will cause the post to use default
    thumbnail. If `anonymous` is set to truthy value, the uploader name won't be
    recorded (privilege verification still applies; it's possible to disallow
    anonymous uploads completely from config.) For details on how to pass
    `content` and `thumbnail`, see file uploads.

    Errors:

    - tags have invalid names
    - safety, notes or flags are invalid
    - relations refer to non-existing posts
    - privileges are too low
    """
    if body.anonymous:
        auth.verify_privilege(auth_user, "posts:create:anonymous")
    else:
        auth.verify_privilege(auth_user, "posts:create:identified")
    content = data.get_file(
        "content",
        use_video_downloader=auth.has_privilege(auth_user, "uploads:use_downloader"),
    )
    safety = body.require("safety")
    source = body.source
    if body.has("content_url") and not source:
        source = body.content_url
    flags = body.flags if body.has("flags") else posts.get_default_flags(content)

    post, new_tags = posts.create_post(
        content, body.tags, None if body.anonymous else auth_user
    )
    if len(new_tags):
        auth.verify_privilege(auth_user, "tags:create")
    posts.update_post_safety(post, safety)
    posts.update_post_source(post, source)
    posts.update_post_relations(post, body.relations)
    posts.update_post_notes(post, body.notes)
    posts.update_post_flags(post, flags)
    if data.has_file("thumbnail"):
        posts.update_post_thumbnail(post, data.get_file("thumbnail"))
    # tags the modules add are not the uploader's: no privilege is asked
    new_tags = new_tags + posts.update_post_auto_tags(post)
    db.session.add(post)
    db.session.flush()
    create_snapshots_for_post(post, new_tags, None if body.anonymous else auth_user)
    alternate_format_posts = posts.generate_alternate_formats(post, content)
    for alternate_post, alternate_post_new_tags in alternate_format_posts:
        create_snapshots_for_post(
            alternate_post,
            alternate_post_new_tags,
            None if body.anonymous else auth_user,
        )
    db.session.commit()
    return _serialize_post(post, auth_user, fields)


@router.post(
    "/posts/reverse-search",
    response_model=resources.ImageSearchResult,
    summary="Find posts that look like an image",
    openapi_extra=request_body(ReverseSearch, "content"),
)
def get_posts_by_image(
    auth_user: Annotated[model.User, Depends(require("posts:reverse_search"))],
    fields: CheckedFields,
    data: RequestDataParam,
) -> Any:
    """
    Retrieves posts that look like the input image.

    Errors:

    - privileges are too low
    """
    content = data.get_file("content")

    try:
        lookalikes = posts.search_by_image(content)
    except (errors.ThirdPartyError, errors.ProcessingError):
        lookalikes = []

    return {
        "exactPost": _serialize_post(
            posts.search_by_image_exact(content), auth_user, fields
        ),
        "similarPosts": [
            {
                "distance": distance,
                "post": _serialize_post(post, auth_user, fields),
            }
            for distance, post in lookalikes
        ],
    }


@router.get("/post/{post_id}", response_model=resources.Post, summary="Get a post")
def get_post(
    post_id: str,
    auth_user: Annotated[model.User, Depends(require("posts:view"))],
    fields: CheckedFields,
) -> Any:
    """
    Retrieves information about an existing post.

    Errors:

    - the post does not exist
    - privileges are too low
    """
    post = _get_post(post_id)
    return _serialize_post(post, auth_user, fields)


@router.get(
    "/post/{post_id}/content",
    response_model=resources.Unpaged[resources.PostContent],
    summary="Get the content extracted from a post's file",
)
def get_post_content(
    post_id: str,
    auth_user: Annotated[model.User, Depends(require("posts:view"))],
) -> Any:
    """
    Retrieves what the modules of this installation read out of the post's
    file: metadata embedded in it, such as PNG text chunks or EXIF. There is
    one result per piece of content found, and a post may have several of
    one kind. What `content` holds depends on the kind and is described by
    the module that owns it. The kinds a post has are listed in the
    `contentKinds` field of the post.

    Without modules, and for a post in which nothing was found, the list is
    empty. A module can mark parts of its content as private; those are left
    out unless the requester has the `posts:view:content:private` privilege.

    Errors:

    - the post does not exist
    - privileges are too low
    """
    post = _get_post(post_id)
    return {"results": posts.serialize_post_contents(post, auth_user)}


@router.put(
    "/post/{post_id}",
    response_model=resources.Post,
    summary="Update a post",
    openapi_extra=request_body(PostUpdate, "content", "thumbnail"),
)
def update_post(
    post_id: str,
    auth_user: CurrentUser,
    fields: CheckedFields,
    data: RequestDataParam,
    body: Annotated[PostUpdate, Depends(read_body(PostUpdate))],
) -> Any:
    """
    Updates existing post. If specified tags do not exist yet, they will be
    automatically created. Tags created automatically have no implications, no
    suggestions, one name and their category is set to the first tag category
    found. Safety must be any of `"safe"`, `"sketchy"` or `"unsafe"`. Relations
    must contain valid post IDs. `<flag>` can be either `"loop"` to enable
    looping for video posts or `"sound"` to indicate sound. Sending empty
    `thumbnail` will reset the post thumbnail to default. For details how to
    pass `content` and `thumbnail`, see file uploads. All fields except the
    `version` are optional - update concerns only provided fields.

    Errors:

    - the version is outdated
    - tags have invalid names
    - safety, notes or flags are invalid
    - relations refer to non-existing posts
    - privileges are too low
    """
    post = _get_post(post_id)
    versions.verify_version(post, body.require("version"))
    versions.bump_version(post)
    content_changed = data.has_file("content")
    if content_changed:
        auth.verify_privilege(auth_user, "posts:edit:content")
        posts.update_post_content(
            post,
            data.get_file(
                "content",
                use_video_downloader=auth.has_privilege(
                    auth_user, "uploads:use_downloader"
                ),
            ),
        )
    if body.has("tags"):
        auth.verify_privilege(auth_user, "posts:edit:tags")
        new_tags = posts.update_post_tags(post, body.tags)
        if len(new_tags):
            auth.verify_privilege(auth_user, "tags:create")
            db.session.flush()
            for tag in new_tags:
                snapshots.create(tag, auth_user)
    if body.has("safety"):
        auth.verify_privilege(auth_user, "posts:edit:safety")
        posts.update_post_safety(post, body.safety)
    if body.has("source"):
        auth.verify_privilege(auth_user, "posts:edit:source")
        posts.update_post_source(post, body.source)
    elif body.has("content_url"):
        posts.update_post_source(post, body.content_url)
    if body.has("relations"):
        auth.verify_privilege(auth_user, "posts:edit:relations")
        posts.update_post_relations(post, body.relations)
    if body.has("notes"):
        auth.verify_privilege(auth_user, "posts:edit:notes")
        posts.update_post_notes(post, body.notes)
    if body.has("flags"):
        auth.verify_privilege(auth_user, "posts:edit:flags")
        posts.update_post_flags(post, body.flags)
    if data.has_file("thumbnail"):
        auth.verify_privilege(auth_user, "posts:edit:thumbnail")
        posts.update_post_thumbnail(post, data.get_file("thumbnail"))
    # new content may bring new tags from the modules; as on creation, no
    # privilege is asked for those
    auto_tags = posts.update_post_auto_tags(post) if content_changed else []
    post.last_edit_time = util.utcnow()
    db.session.flush()
    for tag in auto_tags:
        snapshots.create(tag, auth_user)
    snapshots.modify(post, auth_user)
    db.session.commit()
    return _serialize_post(post, auth_user, fields)


@router.delete(
    "/post/{post_id}",
    response_model=resources.Empty,
    summary="Delete a post",
    openapi_extra=request_body(VersionOnly),
)
def delete_post(
    post_id: str,
    auth_user: Annotated[model.User, Depends(require("posts:delete"))],
    body: Annotated[VersionOnly, Depends(read_body(VersionOnly))],
) -> Any:
    """
    Deletes existing post. Related posts and tags are kept.

    Errors:

    - the version is outdated
    - the post does not exist
    - privileges are too low
    """
    post = _get_post(post_id)
    versions.verify_version(post, body.require("version"))
    snapshots.delete(post, auth_user)
    posts.delete(post)
    db.session.commit()
    return {}


@router.post(
    "/post-merge",
    response_model=resources.Post,
    summary="Merge one post into another",
    openapi_extra=request_body(PostMerge),
)
def merge_posts(
    auth_user: CurrentUser,
    fields: CheckedFields,
    body: Annotated[PostMerge, Depends(read_body(PostMerge))],
) -> Any:
    """
    Removes source post and merges all of its tags, relations, scores, favorites
    and comments to the target post. If `replaceContent` is set to true, content
    of the target post is replaced using the content of the source post;
    otherwise it remains unchanged. Source post properties such as its safety,
    source, whether to loop the video and other scalar values do not get
    transferred and are discarded.

    Errors:

    - the version of either post is outdated
    - the source or target post does not exist
    - the source post is the same as the target post
    - privileges are too low
    """
    source_post_id = body.require("remove")
    target_post_id = body.require("merge_to")
    source_post = posts.get_post_by_id(source_post_id)
    target_post = posts.get_post_by_id(target_post_id)
    replace_content = body.require("replace_content")
    versions.verify_version(source_post, body.require("remove_version"))
    versions.verify_version(target_post, body.require("merge_to_version"))
    versions.bump_version(target_post)
    auth.verify_privilege(auth_user, "posts:merge")
    posts.merge_posts(source_post, target_post, replace_content)
    snapshots.merge(source_post, target_post, auth_user)
    db.session.commit()
    return _serialize_post(target_post, auth_user, fields)


@router.get(
    "/featured-post",
    response_model=resources.Post | None,
    summary="Get the featured post",
)
def get_featured_post(
    auth_user: Annotated[model.User, Depends(require("posts:view:featured"))],
    fields: CheckedFields,
) -> Any:
    """
    Retrieves the post that is currently featured on the main page in web
    client. If no post is featured, `<post>` is null. Note that this method
    exists mostly for compatibility with setting featured post - most of times,
    you'd want to use query global info which contains more information.

    Errors:

    - privileges are too low
    """
    post = posts.try_get_featured_post()
    return _serialize_post(post, auth_user, fields)


@router.post(
    "/featured-post",
    response_model=resources.Post,
    summary="Feature a post",
    openapi_extra=request_body(PostFeature),
)
def set_featured_post(
    auth_user: Annotated[model.User, Depends(require("posts:feature"))],
    fields: CheckedFields,
    body: Annotated[PostFeature, Depends(read_body(PostFeature))],
) -> Any:
    """
    Features a post on the main page in web client.

    Errors:

    - privileges are too low
    - trying to feature a post that is currently featured
    """
    post_id = body.require("id")
    post = posts.get_post_by_id(post_id)
    featured_post = posts.try_get_featured_post()
    if featured_post and featured_post.post_id == post.post_id:
        raise posts.PostAlreadyFeaturedError("Post %r is already featured." % post_id)
    posts.feature_post(post, auth_user)
    snapshots.modify(post, auth_user)
    db.session.commit()
    return _serialize_post(post, auth_user, fields)


@router.put(
    "/post/{post_id}/score",
    response_model=resources.Post,
    summary="Rate a post",
    openapi_extra=request_body(ScoreUpdate),
)
def set_post_score(
    post_id: str,
    auth_user: Annotated[model.User, Depends(require("posts:score"))],
    fields: CheckedFields,
    body: Annotated[ScoreUpdate, Depends(read_body(ScoreUpdate))],
) -> Any:
    """
    Updates score of authenticated user for given post. Valid scores are -1, 0
    and 1.

    Errors:

    - post does not exist
    - score is invalid
    - privileges are too low
    """
    post = _get_post(post_id)
    score = body.require("score")
    scores.set_score(post, auth_user, score)
    db.session.commit()
    return _serialize_post(post, auth_user, fields)


@router.delete(
    "/post/{post_id}/score",
    response_model=resources.Post,
    summary="Take back the rating of a post",
)
def delete_post_score(
    post_id: str,
    auth_user: Annotated[model.User, Depends(require("posts:score"))],
    fields: CheckedFields,
) -> Any:
    """
    Removes the requester's rating of the post, as rating it with a score of
    0 does.

    Errors:

    - the post does not exist
    - privileges are too low
    """
    post = _get_post(post_id)
    scores.delete_score(post, auth_user)
    db.session.commit()
    return _serialize_post(post, auth_user, fields)


@router.post(
    "/post/{post_id}/favorite",
    response_model=resources.Post,
    summary="Add a post to the favorites",
)
def add_post_to_favorites(
    post_id: str,
    auth_user: Annotated[model.User, Depends(require("posts:favorite"))],
    fields: CheckedFields,
) -> Any:
    """
    Marks the post as favorite for authenticated user.

    Errors:

    - post does not exist
    - privileges are too low
    """
    post = _get_post(post_id)
    favorites.set_favorite(post, auth_user)
    db.session.commit()
    return _serialize_post(post, auth_user, fields)


@router.delete(
    "/post/{post_id}/favorite",
    response_model=resources.Post,
    summary="Remove a post from the favorites",
)
def delete_post_from_favorites(
    post_id: str,
    auth_user: Annotated[model.User, Depends(require("posts:favorite"))],
    fields: CheckedFields,
) -> Any:
    """
    Unmarks the post as favorite for authenticated user.

    Errors:

    - post does not exist
    - privileges are too low
    """
    post = _get_post(post_id)
    favorites.unset_favorite(post, auth_user)
    db.session.commit()
    return _serialize_post(post, auth_user, fields)


@router.get(
    "/post/{post_id}/around",
    response_model=resources.PostsAround,
    summary="Get the posts before and after a post in a search",
)
def get_posts_around(
    post_id: str,
    auth_user: Annotated[model.User, Depends(require("posts:list"))],
    fields: CheckedFields,
    query: Annotated[
        str, Query(description="The search the post was found with.")
    ] = "",
) -> Any:
    """
    Retrieves information about posts that are before or after an existing post.

    Errors:

    - the post does not exist
    - privileges are too low
    """
    _search_executor_config.user = auth_user
    around = _search_executor.get_around(query, _get_post_id(post_id))
    # the post search yields posts; either neighbour may be missing
    previous_post, next_post = cast(tuple[model.Post | None, model.Post | None], around)
    return {
        "prev": _serialize_post(previous_post, auth_user, fields),
        "next": _serialize_post(next_post, auth_user, fields),
    }
