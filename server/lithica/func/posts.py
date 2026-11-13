import dataclasses
import functools
import hmac
import logging
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Any, cast

import sqlalchemy as sa
import sqlalchemy.event as sa_event
import sqlalchemy.orm as sa_orm

from lithica import config, db, errors, model, registry
from lithica.func import (
    auth,
    comments,
    file_links,
    file_types,
    files,
    image_hash,
    images,
    mime,
    pools,
    post_content,
    post_kinds,
    scores,
    serialization,
    site_settings,
    tag_categories,
    tags,
    users,
    util,
    visibility,
)
from lithica.func import content as content_module
from lithica.func.content import ContentLike

logger = logging.getLogger(__name__)


EMPTY_PIXEL = (
    b"\x47\x49\x46\x38\x39\x61\x01\x00\x01\x00\x80\x01\x00\x00\x00\x00"
    b"\xff\xff\xff\x21\xf9\x04\x01\x00\x00\x01\x00\x2c\x00\x00\x00\x00"
    b"\x01\x00\x01\x00\x00\x02\x02\x4c\x01\x00\x3b"
)


class PostNotFoundError(errors.NotFoundError):
    pass


class PostAlreadyFeaturedError(errors.ValidationError):
    pass


class PostAlreadyUploadedError(errors.ValidationError):
    def __init__(self, other_post: model.Post | None) -> None:
        if other_post is None:
            # the post is one this user may not see: that it exists is all
            super().__init__("Post already uploaded.")
            return
        super().__init__(
            "Post already uploaded (%d)" % other_post.post_id,
            {
                "otherPostUrl": get_post_content_url(other_post),
                "otherPostId": other_post.post_id,
            },
        )


class InvalidPostIdError(errors.ValidationError):
    pass


class InvalidPostSafetyError(errors.ValidationError):
    pass


class InvalidPostSourceError(errors.ValidationError):
    pass


class InvalidPostContentError(errors.ValidationError):
    pass


class InvalidPostRelationError(errors.ValidationError):
    pass


class InvalidPostNoteError(errors.ValidationError):
    pass


class InvalidPostFlagError(errors.ValidationError):
    pass


SAFETY_MAP = {
    model.Post.SAFETY_SAFE: "safe",
    model.Post.SAFETY_SKETCHY: "sketchy",
    model.Post.SAFETY_UNSAFE: "unsafe",
}

TYPE_MAP = {
    model.Post.TYPE_IMAGE: "image",
    model.Post.TYPE_ANIMATION: "animation",
    model.Post.TYPE_VIDEO: "video",
    model.Post.TYPE_FLASH: "flash",
}

FLAG_MAP = {
    model.Post.FLAG_LOOP: "loop",
    model.Post.FLAG_SOUND: "sound",
}


def get_post_security_hash(id: int) -> str:
    return hmac.new(
        config.config["secret"].encode("utf8"),
        msg=str(id).encode("utf-8"),
        digestmod="md5",
    ).hexdigest()[0:16]


def has_file(post: model.Post) -> bool:
    """Whether the post has a file: its MIME type says so, here and in queries."""
    return post.mime_type is not None


def with_file() -> sa.ColumnElement[bool]:
    """has_file() as a filter for queries."""
    return model.Post.mime_type.is_not(None)


def require_file(post: model.Post) -> None:
    if not has_file(post):
        raise errors.ValidationError("This post has no file.")


def create_fileless_post(
    kind: str,
    user: model.User | None,
    safety: str = model.Post.SAFETY_SAFE,
    tags: list[str] | None = None,
) -> model.Post:
    if kind not in registry.document_kinds():
        raise errors.ValidationError("This kind has no registered document kind.")
    post = model.Post(kind=kind, user=user, creation_time=util.utcnow(), listed=True)
    post.flags = []
    update_post_safety(post, safety)
    update_post_tags(post, tags or [])
    db.session.add(post)
    return post


def get_post_content_url(post: model.Post) -> str | None:
    """The file's address, signed when the site signs its file links."""
    assert post
    if not has_file(post):
        return None
    path = get_post_content_path(post)
    return file_links.link(
        "%s/%s" % (config.config["data_url"].rstrip("/"), path), path
    )


def get_post_thumbnail_url(post: model.Post) -> str | None:
    """The thumbnail's address, signed when the site signs its file links."""
    assert post
    if not has_file(post):
        return None
    path = get_post_thumbnail_path(post)
    return file_links.link(
        "%s/%s" % (config.config["data_url"].rstrip("/"), path), path
    )


def get_post_content_path(post: model.Post) -> str:
    require_file(post)
    assert post
    assert post.post_id
    return "posts/%d_%s.%s" % (
        post.post_id,
        get_post_security_hash(post.post_id),
        file_types.get_extension(post.mime_type or "") or "dat",
    )


def get_post_thumbnail_path(post: model.Post) -> str:
    require_file(post)
    assert post
    return "generated-thumbnails/%d_%s.jpg" % (
        post.post_id,
        get_post_security_hash(post.post_id),
    )


def get_post_thumbnail_backup_path(post: model.Post) -> str:
    require_file(post)
    assert post
    return "posts/custom-thumbnails/%d_%s.dat" % (
        post.post_id,
        get_post_security_hash(post.post_id),
    )


def serialize_note(note: model.PostNote) -> dict[str, Any]:
    assert note
    return {
        "polygon": note.polygon,
        "text": note.text,
    }


@dataclass
class Preloaded:
    """
    What the serializer of a page of posts would otherwise ask the database
    for once per post, asked for once for the whole page (`preload_posts`).
    A value that is None was not loaded: the serializer asks for it itself.
    """

    default_tag_category: str | None = None
    # post id -> the requesting user's score of it (absent: 0)
    own_scores: dict[int, int] | None = None
    # post id -> the kinds of its extracted content
    content_kinds: dict[int, set[str]] | None = None
    # comment id -> its score, and the requesting user's score of it
    comment_scores: dict[int, int] | None = None
    comment_own_scores: dict[int, int] | None = None
    # module field name -> post id -> its value
    module_fields: dict[str, dict[int, Any]] = dataclasses.field(
        default_factory=dict[str, dict[int, Any]]
    )


class PostSerializer(serialization.BaseSerializer):
    feature_resource = "post"

    def __init__(
        self,
        post: model.Post,
        auth_user: model.User,
        preloaded: Preloaded | None = None,
    ) -> None:
        self.post = post
        self.auth_user = auth_user
        self.preloaded = preloaded or Preloaded()

    def _serializers(self) -> dict[str, Callable[[], Any]]:
        serializers = self._engine_serializers()
        # the fields the loaded modules add to a post
        module_fields = {**registry.post_fields(), **registry.requested_post_fields()}
        for name, serialize in module_fields.items():
            serializers[name] = functools.partial(
                self._serialize_module_field, name, serialize
            )
        return serializers

    def _serialize_module_field(self, name: str, serialize: registry.PostField) -> Any:
        values = self.preloaded.module_fields.get(name)
        if values is not None and self.post.post_id in values:
            return values[self.post.post_id]
        return serialize(self.post, self.auth_user)

    def serialize(self, options: list[str]) -> Any:
        if not options:
            # everything, except what a module returns only on request
            on_request = registry.requested_post_fields()
            options = [name for name in self._serializers() if name not in on_request]
        return super().serialize(options)

    def _engine_serializers(self) -> dict[str, Callable[[], Any]]:
        return {
            "id": self.serialize_id,
            "version": self.serialize_version,
            "creationTime": self.serialize_creation_time,
            "lastEditTime": self.serialize_last_edit_time,
            "safety": self.serialize_safety,
            "source": self.serialize_source,
            "kind": lambda: self.post.kind,
            "listed": lambda: self.post.listed,
            "type": self.serialize_type,
            "mimeType": self.serialize_mime,
            "checksum": self.serialize_checksum,
            "checksumMD5": self.serialize_checksum_md5,
            "fileSize": self.serialize_file_size,
            "canvasWidth": self.serialize_canvas_width,
            "canvasHeight": self.serialize_canvas_height,
            "contentUrl": self.serialize_content_url,
            "thumbnailUrl": self.serialize_thumbnail_url,
            "flags": self.serialize_flags,
            "nsfw": self.serialize_nsfw,
            "tags": self.serialize_tags,
            "relations": self.serialize_relations,
            "externalIds": lambda: [
                {"host": row.host, "id": row.external_id}
                for row in sorted(
                    self.post.external_ids, key=lambda row: (row.host, row.external_id)
                )
            ],
            "user": self.serialize_user,
            "score": self.serialize_score,
            "ownScore": self.serialize_own_score,
            "ownFavorite": self.serialize_own_favorite,
            "tagCount": self.serialize_tag_count,
            "favoriteCount": self.serialize_favorite_count,
            "commentCount": self.serialize_comment_count,
            "noteCount": self.serialize_note_count,
            "relationCount": self.serialize_relation_count,
            "featureCount": self.serialize_feature_count,
            "lastFeatureTime": self.serialize_last_feature_time,
            "favoritedBy": self.serialize_favorited_by,
            "hasCustomThumbnail": self.serialize_has_custom_thumbnail,
            "notes": self.serialize_notes,
            "comments": self.serialize_comments,
            "pools": self.serialize_pools,
            "contentKinds": self.serialize_content_kinds,
        }

    def serialize_id(self) -> Any:
        return self.post.post_id

    def serialize_version(self) -> Any:
        return self.post.version

    def serialize_creation_time(self) -> Any:
        return self.post.creation_time

    def serialize_last_edit_time(self) -> Any:
        return self.post.last_edit_time

    def serialize_safety(self) -> Any:
        return SAFETY_MAP[self.post.safety]

    def serialize_source(self) -> Any:
        return self.post.source

    def serialize_type(self) -> Any:
        # a type of a module is its own name
        return (
            TYPE_MAP.get(self.post.type, self.post.type)
            if self.post.type is not None
            else None
        )

    def serialize_mime(self) -> Any:
        return self.post.mime_type

    def serialize_checksum(self) -> Any:
        return self.post.checksum

    def serialize_checksum_md5(self) -> Any:
        return self.post.checksum_md5 if has_file(self.post) else None

    def serialize_file_size(self) -> Any:
        return self.post.file_size if has_file(self.post) else None

    def serialize_canvas_width(self) -> Any:
        return self.post.canvas_width if has_file(self.post) else None

    def serialize_canvas_height(self) -> Any:
        return self.post.canvas_height if has_file(self.post) else None

    def serialize_content_url(self) -> Any:
        return get_post_content_url(self.post)

    def serialize_thumbnail_url(self) -> Any:
        return get_post_thumbnail_url(self.post)

    def serialize_flags(self) -> Any:
        return self.post.flags

    def serialize_nsfw(self) -> Any:
        return visibility.is_nsfw(self.post)

    def serialize_tags(self) -> Any:
        return [
            {
                "names": [name.name for name in tag.names],
                "category": tag.category.name,
                "usages": tag.post_count,
            }
            for tag in tags.sort_tags(
                self.post.tags, self.preloaded.default_tag_category
            )
        ]

    def serialize_relations(self) -> Any:
        return sorted(
            {
                post["id"]: post
                for post in [
                    serialize_micro_post(rel, self.auth_user)
                    for rel in self.post.relations
                ]
            }.values(),
            key=lambda post: post["id"],
        )

    def serialize_user(self) -> Any:
        return users.serialize_micro_user(self.post.user, self.auth_user)

    def serialize_score(self) -> Any:
        return self.post.score

    def serialize_own_score(self) -> Any:
        if self.preloaded.own_scores is not None:
            return self.preloaded.own_scores.get(self.post.post_id, 0)
        return scores.get_score(self.post, self.auth_user)

    def serialize_own_favorite(self) -> Any:
        return (
            len(
                [
                    user
                    for user in self.post.favorited_by
                    if user.user_id == self.auth_user.user_id
                ]
            )
            > 0
        )

    def serialize_tag_count(self) -> Any:
        return self.post.tag_count

    def serialize_favorite_count(self) -> Any:
        return self.post.favorite_count

    def serialize_comment_count(self) -> Any:
        return self.post.comment_count

    def serialize_note_count(self) -> Any:
        return self.post.note_count

    def serialize_relation_count(self) -> Any:
        # the relations the request may see: as many as `relations` lists
        return self.post.relation_count

    def serialize_feature_count(self) -> Any:
        return self.post.feature_count

    def serialize_last_feature_time(self) -> Any:
        return self.post.last_feature_time

    def serialize_favorited_by(self) -> Any:
        # in the order they favourited the post, then by user
        return [
            users.serialize_micro_user(rel.user, self.auth_user)
            for rel in sorted(
                self.post.favorited_by,
                key=lambda favorite: (favorite.time, favorite.user_id),
            )
        ]

    def serialize_has_custom_thumbnail(self) -> Any:
        return has_file(self.post) and files.has(
            get_post_thumbnail_backup_path(self.post)
        )

    def serialize_notes(self) -> Any:
        return sorted(
            [serialize_note(note) for note in self.post.notes],
            key=lambda x: x["polygon"],
        )

    def serialize_comments(self) -> Any:
        return [
            comments.serialize_comment(
                comment,
                self.auth_user,
                scores=self.preloaded.comment_scores,
                own_scores=self.preloaded.comment_own_scores,
            )
            for comment in sorted(
                self.post.comments, key=lambda comment: comment.creation_time
            )
        ]

    def serialize_pools(self) -> list[Any]:
        return [
            pools.serialize_micro_pool(pool)
            for pool in sorted(self.post.pools, key=lambda pool: pool.creation_time)
        ]

    def serialize_content_kinds(self) -> Any:
        if self.preloaded.content_kinds is not None:
            return post_content.owned_content_kinds(
                self.preloaded.content_kinds.get(self.post.post_id, set())
            )
        return post_content.get_content_kinds(self.post)


def serialize_post(
    post: model.Post | None,
    auth_user: model.User,
    options: list[str] | None = None,
    preloaded: Preloaded | None = None,
) -> serialization.Response | None:
    """
    A post. What its fields need is loaded first (`preload_posts`), unless
    the caller did that already for a page of posts (`preloaded`).
    """
    if not post:
        return None
    options = options or []
    if preloaded is None:
        preloaded = preload_posts([post], auth_user, options)
    return PostSerializer(post, auth_user, preloaded).serialize(options)


def serialize_posts(
    posts: Sequence[model.Post | None],
    auth_user: model.User,
    options: list[str] | None = None,
) -> list[serialization.Response | None]:
    """
    Posts, as `serialize_post` gives each (None for None): what the fields
    need is loaded for all of them at once (`preload_posts`), so the
    queries do not grow with the number of posts.
    """
    options = options or []
    preloaded = preload_posts(posts, auth_user, options)
    return [serialize_post(post, auth_user, options, preloaded) for post in posts]


def serialize_micro_post(
    post: model.Post, auth_user: model.User | None
) -> dict[str, Any]:
    # the two fields of a micro post do not depend on who is asking
    serializer = PostSerializer(post, cast(model.User, auth_user))
    return serializer.serialize(["id", "thumbnailUrl"])


def _fields_asked(options: list[str]) -> set[str]:
    """The fields a serialization with these options gives."""
    if options:
        return set(site_settings.active_fields("post", options))
    names = set(get_engine_post_field_names()) | set(registry.post_fields())
    return set(
        site_settings.active_fields(
            "post", list(names - set(registry.requested_post_fields()))
        )
    )


def _deferred_counts(fields: set[str]) -> list[tuple[str, Any]]:
    # the columns of a post that the search leaves out until they are read
    columns = {
        "tagCount": model.Post.tag_count,
        "noteCount": model.Post.note_count,
        "featureCount": model.Post.feature_count,
        "lastFeatureTime": model.Post.last_feature_time,
    }
    return [(column.key, column) for name, column in columns.items() if name in fields]


def _relationship_loaders(fields: set[str]) -> list[tuple[str, Any]]:
    """
    What the asked fields read of a post's relationships, by selectin loads:
    (the relationship's name, its loader).
    """
    post, lazy = model.Post, sa_orm.lazyload("*")
    loaders: list[tuple[str, Any]] = []
    if fields & {"tags", "nsfw"}:
        loaders.append(("tags", sa_orm.selectinload(post.tags).options(lazy)))
    if "relations" in fields:
        # A micro post needs MIME too, to distinguish a file-less thumbnail.
        loaders.append(
            (
                "relations",
                sa_orm.selectinload(post.relations).options(
                    lazy, sa_orm.load_only(post.post_id, post.mime_type)
                ),
            )
        )
    if "user" in fields:
        loaders.append(("user", sa_orm.selectinload(post.user).options(lazy)))
    if fields & {"favoritedBy", "ownFavorite"}:
        loaders.append(
            (
                "favorited_by",
                sa_orm.selectinload(post.favorited_by).options(
                    lazy, sa_orm.selectinload(model.PostFavorite.user).options(lazy)
                ),
            )
        )
    if "externalIds" in fields:
        loaders.append(("external_ids", sa_orm.selectinload(post.external_ids)))
    if "notes" in fields:
        loaders.append(("notes", sa_orm.selectinload(post.notes).options(lazy)))
    if "comments" in fields:
        loaders.append(
            (
                "comments",
                sa_orm.selectinload(post.comments).options(
                    lazy, sa_orm.selectinload(model.Comment.user).options(lazy)
                ),
            )
        )
    if "pools" in fields:
        loaders.append(
            (
                "_pools",
                sa_orm.selectinload(post._pools).options(
                    lazy,
                    sa_orm.selectinload(model.PoolPost.pool).options(
                        lazy,
                        sa_orm.selectinload(model.Pool.names),
                        sa_orm.selectinload(model.Pool.category),
                        sa_orm.undefer(model.Pool.post_count),
                    ),
                ),
            )
        )
    return loaders


def _unloaded(objects: Iterable[Any]) -> set[str]:
    """The attributes that are not loaded yet on any of these objects."""
    found: set[str] = set()
    for one in objects:
        found |= sa.inspect(one).unloaded
    return found


def preload_posts(
    posts: Iterable[model.Post | None], auth_user: model.User, options: list[str]
) -> Preloaded:
    """
    Load what serializing these posts with these options reads, for all of
    them at once: one query per field (or per relationship it reads), not
    one per post. Only the asked fields are loaded. What is loaded goes
    into the session (the posts' relationships and columns) or into the
    returned Preloaded; the serializer reads it from there.

    The queries are the ORM's, so the visibility criteria
    (lithica.func.visibility) apply to them as to any other: a post this
    request may not see is not loaded as a relation, a pool's post or the
    post of a comment.
    """
    preloaded = Preloaded()
    page = [post for post in posts if post is not None]
    ids = sorted({post.post_id for post in page})
    if not ids:
        return preloaded
    fields = _fields_asked(options)

    # only what is not loaded yet: a post looked up by its id comes with
    # its eager relationships, a post of a search without them
    unloaded = _unloaded(page)
    loaders = [one for key, one in _relationship_loaders(fields) if key in unloaded]
    counts = [one for key, one in _deferred_counts(fields) if key in unloaded]
    if loaders or counts:
        # the posts are in the session: this fills in, for each, what is
        # not loaded yet, and leaves what is as it is
        db.session.query(model.Post).filter(model.Post.post_id.in_(ids)).options(
            sa_orm.lazyload("*"),
            sa_orm.load_only(model.Post.post_id, *counts),
            *loaders,
        ).all()

    if "tags" in fields:
        page_tags = {tag.tag_id: tag for post in page for tag in post.tags}
        tag_ids = sorted(page_tags)
        if _unloaded(page_tags.values()) & {"post_count", "names", "category"}:
            # the search leaves out how often a tag is used
            db.session.query(model.Tag).filter(model.Tag.tag_id.in_(tag_ids)).options(
                sa_orm.lazyload("*"),
                sa_orm.load_only(model.Tag.tag_id, model.Tag.post_count),
                sa_orm.selectinload(model.Tag.names),
                sa_orm.selectinload(model.Tag.category),
            ).all()
        # without one, each post's tags ask, and fail, as they always have
        default = tag_categories.try_get_default_category()
        preloaded.default_tag_category = default.name if default else None

    if "ownScore" in fields:
        preloaded.own_scores = {}
        if auth_user.user_id is not None:
            rows = db.session.execute(
                sa.select(model.PostScore.post_id, model.PostScore.score)
                .where(model.PostScore.user_id == auth_user.user_id)
                .where(model.PostScore.post_id.in_(ids))
            )
            preloaded.own_scores = {post_id: score for post_id, score in rows}

    if "contentKinds" in fields and registry.content_kinds():
        kinds: dict[int, set[str]] = {}
        rows = db.session.execute(
            sa.select(model.PostContent.post_id, model.PostContent.kind).where(
                model.PostContent.post_id.in_(ids)
            )
        )
        for post_id, kind in rows:
            kinds.setdefault(post_id, set()).add(kind)
        preloaded.content_kinds = kinds

    if "comments" in fields:
        comment_ids = sorted(
            {comment.comment_id for post in page for comment in post.comments}
        )
        (
            preloaded.comment_scores,
            preloaded.comment_own_scores,
        ) = comments.load_comment_scores(comment_ids, auth_user)

    for name, batch in registry.post_field_batches().items():
        if name in fields:
            preloaded.module_fields[name] = dict(batch(page, auth_user))
    return preloaded


PRIVATE_CONTENT_PRIVILEGE = "posts:view:content:private"


def serialize_post_contents(
    post: model.Post, auth_user: model.User
) -> list[dict[str, Any]]:
    """
    The content extracted from the post's file, as this user may see it:
    without the fields modules marked as private, unless the user has the
    privilege for them.
    """
    show_private = auth.has_privilege(auth_user, PRIVATE_CONTENT_PRIVILEGE)
    return post_content.serialize_post_contents(post, show_private)


def get_engine_post_field_names() -> set[str]:
    """The fields of a post that are the engine's own; a module may not take them."""
    # only the names are read: no post is needed to list them
    serializer = PostSerializer(cast(model.Post, None), cast(model.User, None))
    return set(serializer._engine_serializers())


def get_post_count() -> int:
    return db.session.query(sa.func.count(model.Post.post_id)).one()[0]


def try_get_post_by_id(post_id: int) -> model.Post | None:
    return (
        db.session.query(model.Post).filter(model.Post.post_id == post_id).one_or_none()
    )


def get_post_by_id(post_id: int) -> model.Post:
    post = try_get_post_by_id(post_id)
    if not post:
        raise PostNotFoundError("Post %r not found." % post_id)
    return post


def get_posts_by_ids(ids: list[int]) -> list[model.Post]:
    if len(ids) == 0:
        return []
    posts = (
        db.session.query(model.Post)
        .filter(sa.sql.or_(*[model.Post.post_id == post_id for post_id in ids]))
        .all()
    )
    id_order = {v: k for k, v in enumerate(ids)}
    return sorted(posts, key=lambda post: id_order[post.post_id])


def try_get_current_post_feature() -> model.PostFeature | None:
    return (
        db.session.query(model.PostFeature)
        .order_by(model.PostFeature.time.desc())
        .first()
    )


def try_get_featured_post() -> model.Post | None:
    post_feature = try_get_current_post_feature()
    return post_feature.post if post_feature else None


def create_post(
    content: ContentLike,
    tag_names: list[str],
    user: model.User | None,
    *,
    defer_file: bool = False,
    as_media: bool = False,
) -> tuple[model.Post, list[model.Tag]]:
    post = model.Post()
    post.safety = model.Post.SAFETY_SAFE
    post.user = user
    post.creation_time = util.utcnow()
    post.flags = []

    post.type = ""
    post.checksum = ""
    post.mime_type = ""

    if defer_file:
        update_post_content(post, content, defer_file=True, as_media=as_media)
    else:
        update_post_content(post, content, as_media=as_media)
    new_tags = update_post_tags(post, tag_names)

    db.session.add(post)
    return post, new_tags


def update_post_listed(post: model.Post, listed: bool) -> None:
    post.listed = listed


def update_post_safety(post: model.Post, safety: str) -> None:
    assert post
    internal_safety = util.flip(SAFETY_MAP).get(safety, None)
    if not internal_safety:
        raise InvalidPostSafetyError(
            "Safety can be either of %r." % list(SAFETY_MAP.values())
        )
    post.safety = internal_safety


def update_post_source(post: model.Post, source: str | None) -> None:
    assert post
    if util.value_exceeds_column_size(source, model.Post.source):
        raise InvalidPostSourceError("Source is too long.")
    post.source = source or None


@sa_event.listens_for(model.Post, "after_insert")
def _after_post_insert(_mapper: Any, _connection: Any, post: model.Post) -> None:
    _sync_post_content(post)


@sa_event.listens_for(model.Post, "after_update")
def _after_post_update(_mapper: Any, _connection: Any, post: model.Post) -> None:
    _sync_post_content(post)


@sa_event.listens_for(model.Post, "before_delete")
def _before_post_delete(_mapper: Any, _connection: Any, post: model.Post) -> None:
    if post.post_id and has_file(post):
        if config.config["delete_source_files"]:
            files.delete(get_post_content_path(post))
            files.delete(get_post_thumbnail_path(post))


def _sync_post_content(post: model.Post) -> None:
    if getattr(post, "__defer_file", False) or not has_file(post):
        return
    regenerate_thumb = False

    if hasattr(post, "__content"):
        content = getattr(post, "__content")
        files.save(get_post_content_path(post), content)
        delattr(post, "__content")
        regenerate_thumb = True
        if hasattr(post, "__old_content_path"):
            old_path = getattr(post, "__old_content_path")
            delattr(post, "__old_content_path")
            if old_path != get_post_content_path(post):
                # Scope removals to the savepoint that replaced this file.
                session = sa_orm.object_session(post)
                assert session is not None
                transaction = (
                    session.get_nested_transaction() or session.get_transaction()
                )
                assert transaction is not None
                pending = _obsolete_post_files(session).setdefault(transaction, {})
                pending.setdefault(post.post_id, set()).add(old_path)

    if hasattr(post, "__thumbnail"):
        if getattr(post, "__thumbnail"):
            files.save(
                get_post_thumbnail_backup_path(post),
                getattr(post, "__thumbnail"),
            )
        else:
            files.delete(get_post_thumbnail_backup_path(post))
        delattr(post, "__thumbnail")
        regenerate_thumb = True

    if regenerate_thumb:
        generate_post_thumbnail(post)


type _ObsoletePostFiles = dict[sa_orm.SessionTransaction, dict[int, set[str]]]


def _obsolete_post_files(session: sa_orm.Session) -> _ObsoletePostFiles:
    return cast(_ObsoletePostFiles, session.info.setdefault("obsolete_post_files", {}))


@sa_event.listens_for(sa_orm.Session, "before_commit")
def _remove_obsolete_post_files(session: sa_orm.Session) -> None:
    if session.in_nested_transaction():
        return
    # Flush final writes first, while the post-row locks still belong to us.
    # Every request validation has finished before the caller commits.
    session.flush()
    transaction = session.get_transaction()
    assert transaction is not None
    pending = _obsolete_post_files(session).pop(transaction, {})
    if not pending:
        return
    active: dict[int, str] = {}
    for post_id, mime_type in session.execute(
        sa.select(model.Post.post_id, model.Post.mime_type)
        .where(model.Post.post_id.in_(pending))
        .with_for_update()
        .execution_options(**{visibility.ALL_POSTS: True})
    ):
        if mime_type is not None:
            # Columns only: do not cache an entity across visibility boundaries.
            active[post_id] = get_post_content_path(
                model.Post(post_id=post_id, mime_type=mime_type)
            )
    for post_id, paths in pending.items():
        for path in paths:
            if path != active.get(post_id):
                files.delete(path)


@sa_event.listens_for(sa_orm.Session, "after_commit")
def _promote_obsolete_post_files(session: sa_orm.Session) -> None:
    transaction = session.get_nested_transaction()
    if transaction is None:
        session.info.pop("obsolete_post_files", None)
        return
    pending = _obsolete_post_files(session).pop(transaction, {})
    if pending:
        assert transaction.parent is not None
        parent = _obsolete_post_files(session).setdefault(transaction.parent, {})
        for post_id, paths in pending.items():
            parent.setdefault(post_id, set()).update(paths)


@sa_event.listens_for(sa_orm.Session, "after_soft_rollback")
def _forget_obsolete_post_files(
    session: sa_orm.Session, transaction: sa_orm.SessionTransaction
) -> None:
    if transaction.parent is None:
        session.info.pop("obsolete_post_files", None)
    else:
        _obsolete_post_files(session).pop(transaction, None)


def release_post_content(post: model.Post) -> None:
    """Allow a module's validated pending file to be saved on the next flush."""
    if hasattr(post, "__defer_file"):
        delattr(post, "__defer_file")
    sa_orm.attributes.flag_dirty(post)


def generate_alternate_formats(
    post: model.Post, content: ContentLike
) -> list[tuple[model.Post, list[model.Tag]]]:
    assert post
    assert content
    new_posts = []
    if mime.is_animated_gif(content):
        tag_names = [tag.first_name for tag in post.tags]

        if config.config["convert"]["gif"]["to_mp4"]:
            mp4_post, new_tags = create_post(
                images.Image(content).to_mp4(), tag_names, post.user
            )
            update_post_flags(mp4_post, ["loop"])
            update_post_safety(mp4_post, post.safety)
            update_post_source(mp4_post, post.source)
            new_posts += [(mp4_post, new_tags)]

        if config.config["convert"]["gif"]["to_webm"]:
            webm_post, new_tags = create_post(
                images.Image(content).to_webm(), tag_names, post.user
            )
            update_post_flags(webm_post, ["loop"])
            update_post_safety(webm_post, post.safety)
            update_post_source(webm_post, post.source)
            new_posts += [(webm_post, new_tags)]

        db.session.flush()

        new_posts = [p for p in new_posts if p[0] is not None]

        new_relations = [p[0].post_id for p in new_posts]
        if len(new_relations) > 0:
            update_post_relations(post, new_relations)

    for alternate_post, _new_tags in new_posts:
        post_content.after_file_or_kind(alternate_post, post.user)
    return new_posts


def get_default_flags(content: ContentLike) -> list[str]:
    assert content
    ret = []
    if mime.is_video(mime.get_mime_type(content)):
        ret.append(model.Post.FLAG_LOOP)
        if images.Image(content).check_for_sound():
            ret.append(model.Post.FLAG_SOUND)
    return ret


def purge_post_signature(post: model.Post) -> None:
    # Deleted through the session, not with a bulk delete: the session must
    # forget the signature's words too, or a new signature for the same post
    # would be mistaken for an update of the old rows.
    signatures = (
        db.session.query(model.PostSignature)
        .filter(model.PostSignature.post_id == post.post_id)
        .all()
    )
    for signature in signatures:
        db.session.delete(signature)
    db.session.flush()


def generate_post_signature(post: model.Post, content: ContentLike) -> None:
    if not has_file(post):
        return
    try:
        unpacked_signature = image_hash.generate_signature(content)
        packed_signature = image_hash.pack_signature(unpacked_signature)
        words = image_hash.generate_words(unpacked_signature)

        db.session.add(
            model.PostSignature(post=post, signature=packed_signature, words=words)
        )
    except errors.ProcessingError as ex:
        if not config.config["allow_broken_uploads"]:
            raise InvalidPostContentError("Unable to generate image hash data.") from ex


def generate_post_signature_from_thumbnail(
    post: model.Post, file_type: registry.FileType, content: ContentLike
) -> None:
    """
    Sign a post of a module's file type by the picture the module offers as
    its thumbnail, so that the similar-image search finds it. Without a
    picture, or with one that cannot be read, the post has no signature. It
    never fails the upload: the file was accepted for what it is, and the
    picture is an extra.
    """
    picture = file_types.get_thumbnail(file_type, content)
    if picture is None:
        return
    try:
        unpacked_signature = image_hash.generate_signature(picture)
        packed_signature = image_hash.pack_signature(unpacked_signature)
        words = image_hash.generate_words(unpacked_signature)
    except errors.ProcessingError:
        logger.warning(
            "The thumbnail of a %r file could not be signed.", file_type.post_type
        )
        return
    db.session.add(
        model.PostSignature(post=post, signature=packed_signature, words=words)
    )


BACKFILL_BATCH_SIZE = 100


def _query_posts_without_signature() -> sa_orm.Query:
    return (
        db.session.query(model.Post)
        .filter(
            (model.Post.type == model.Post.TYPE_IMAGE)
            | (model.Post.type == model.Post.TYPE_ANIMATION)
        )
        .filter(model.Post.signature == None)  # noqa: E711
    )


def _query_posts_without_md5_checksum() -> sa_orm.Query:
    return db.session.query(model.Post).filter(
        with_file(),
        model.Post.checksum_md5 == None,  # noqa: E711
    )


def count_posts_without_signature() -> int:
    return _query_posts_without_signature().count()


def count_posts_without_md5_checksum() -> int:
    return _query_posts_without_md5_checksum().count()


def _backfill(
    query_factory: Callable[[], sa_orm.Query],
    fill: Callable[[model.Post], bool],
    description: str,
) -> tuple[int, int]:
    """
    Run fill() on every post the query returns, a batch at a time, committing
    after each post. Returns how many posts were filled and how many were
    not. Posts that could not be filled are skipped, not retried, so the run
    always ends; running it again is safe and picks up only what is left.
    """
    filled = 0
    failed = 0
    last_post_id = 0
    while True:
        batch = (
            query_factory()
            .filter(model.Post.post_id > last_post_id)
            .order_by(model.Post.post_id.asc())
            .limit(BACKFILL_BATCH_SIZE)
            .all()
        )
        if not batch:
            break
        post_ids = [post.post_id for post in batch]
        last_post_id = post_ids[-1]
        for post_id, post in zip(post_ids, batch, strict=True):
            try:
                done = fill(post)
                db.session.commit()
            except Exception as ex:
                db.session.rollback()
                logger.exception(ex)
                done = False
            if done:
                filled += 1
                logger.info("Created %s - Post %d", description, post_id)
            else:
                failed += 1
                logger.warning("Could not create %s - Post %d", description, post_id)
    return filled, failed


def update_all_post_signatures() -> tuple[int, int]:
    """Create the image signature of every post that lacks one."""

    def fill(post: model.Post) -> bool:
        content = files.get(get_post_content_path(post))
        if content is None:
            logger.warning("Post %d has no content file", post.post_id)
            return False
        generate_post_signature(post, content)
        # with allow_broken_uploads an unreadable image is left unsigned
        return post.signature is not None

    return _backfill(_query_posts_without_signature, fill, "Signature")


def update_all_md5_checksums() -> tuple[int, int]:
    """Compute the MD5 checksum of every post that lacks one."""

    def fill(post: model.Post) -> bool:
        content = files.get(get_post_content_path(post))
        if content is None:
            logger.warning("Post %d has no content file", post.post_id)
            return False
        post.checksum_md5 = util.get_md5(content)
        return True

    return _backfill(_query_posts_without_md5_checksum, fill, "MD5")


def _query_posts_to_reextract(kinds: list[str] | None) -> sa_orm.Query:
    """
    The posts a re-extraction has to look at: those of a type an extractor
    reads, and those that have rows of the kinds in question, which may be
    stale.
    """
    target_kinds = list(registry.content_kinds()) if kinds is None else kinds
    with_rows = sa.select(model.PostContent.post_id).where(
        model.PostContent.kind.in_(target_kinds)
    )
    return db.session.query(model.Post).filter(
        with_file(),
        sa.or_(
            model.Post.mime_type.in_(post_content.get_extracted_mime_types(kinds)),
            model.Post.post_id.in_(with_rows),
        ),
    )


def count_posts_to_reextract(kinds: list[str] | None = None) -> int:
    return _query_posts_to_reextract(kinds).count()


def reextract_all_post_contents(kinds: list[str] | None = None) -> tuple[int, int]:
    """
    Run the extractors of the loaded modules over the files of the existing
    posts again, for all kinds or for the given ones, a batch of posts at a
    time. For when a module is switched on, or its extractor has changed.
    Extracted content and, when its content kinds change, the post kind
    are updated. Tags and version are unchanged.
    Returns how many posts were done and how many were not.
    """

    def fill(post: model.Post) -> bool:
        content = files.get(get_post_content_path(post))
        if content is None:
            logger.warning("Post %d has no content file", post.post_id)
            return False
        return post_content.reextract_post_contents(post, content, kinds)

    return _backfill(
        lambda: _query_posts_to_reextract(kinds), fill, "extracted content"
    )


def warn_about_pending_backfills() -> None:
    """
    Tell the administrator, in the log, that posts wait for a backfill. The
    server does not run backfills itself: with several server processes each
    would start one.
    """
    pending = [
        (
            count_posts_without_signature(),
            "image signature",
            "signatures",
            "similar-image search does not find them",
        ),
        (
            count_posts_without_md5_checksum(),
            "MD5 checksum",
            "md5",
            "they cannot be found by MD5",
        ),
    ]
    for count, what, command, consequence in pending:
        if count:
            logger.warning(
                "%d posts have no %s, so %s. Run 'lithica-admin backfill %s'.",
                count,
                what,
                consequence,
                command,
            )


def _update_post_contents(
    post: model.Post, content: ContentLike, *, as_media: bool = False
) -> None:
    try:
        post_content.update_post_contents(post, content, as_media=as_media)
    except post_content.ContentRejectedError as ex:
        # a module refused the file, in its words
        raise InvalidPostContentError(str(ex)) from ex


def update_post_content(
    post: model.Post,
    content: ContentLike | None,
    *,
    allow_document: bool = False,
    defer_file: bool = False,
    as_media: bool = False,
) -> None:
    """Replace file metadata; modules may explicitly retain document ownership.

    A module opting in must update its document before flushing pending file
    content. With defer_file, release_post_content enables file storage after
    the module finishes its validations. Ordinary API edits retain the guard.
    """
    if defer_file:
        setattr(post, "__defer_file", True)
    from lithica.func import documents

    if documents.have_documents([post], lock=True) and not allow_document:
        raise InvalidPostContentError(
            "Replacing the file of a post with a document comes later."
        )
    # create_post sets the file fields to "" first, so a new upload passes
    if not allow_document:
        require_file(post)
    assert post
    if not content:
        raise InvalidPostContentError("Post content missing.")

    if post.post_id and has_file(post) and not hasattr(post, "__old_content_path"):
        setattr(post, "__old_content_path", get_post_content_path(post))
    update_signature = False
    # a type of a module, for a file the engine itself does not know
    file_type: registry.FileType | None = None
    mime_type = mime.get_mime_type(content)
    post.mime_type = mime_type
    if mime.is_flash(mime_type):
        post.type = model.Post.TYPE_FLASH
    elif mime.is_image(mime_type):
        update_signature = True
        if mime.is_animated_gif(content):
            post.type = model.Post.TYPE_ANIMATION
        else:
            post.type = model.Post.TYPE_IMAGE
    elif mime.is_video(mime_type):
        post.type = model.Post.TYPE_VIDEO
    else:
        if post.mime_type == "application/octet-stream":
            try:
                file_type = file_types.detect(content)
            except file_types.FileRejectedError as ex:
                raise InvalidPostContentError(str(ex)) from ex
        if file_type is None:
            raise InvalidPostContentError("Unhandled file type: %r" % post.mime_type)
        post.mime_type = file_type.mime_type
        post.type = file_type.post_type

    checksum = util.get_sha1(content)
    post.checksum = checksum
    post.checksum_md5 = util.get_md5(content)
    with db.session.no_autoflush:
        # Card data takes precedence when the same carrier is also a media avatar.
        # Both constraints are checked before pending file metadata can flush.
        _update_post_contents(post, content, as_media=as_media)
    # every post, also one this user may not see: a file is on the site once.
    # Only its id: a post loaded here would stay in the session, where a
    # lookup by id later in the request finds it without a query
    same_ids = (
        db.session.query(model.Post.post_id)
        .autoflush(False)
        .filter(_checksum_matches(checksum))
        .filter(model.Post.post_id != post.post_id)
        .execution_options(**{visibility.ALL_POSTS: True})
        .all()
    )
    # Exclude the current post even when it already has an ID.
    other_post_id = next(
        (row.post_id for row in same_ids if row.post_id != post.post_id), None
    )
    if other_post_id:
        # one this user may see is loaded as any other lookup
        with db.session.no_autoflush:
            other_post = try_get_post_by_id(other_post_id)
        raise PostAlreadyUploadedError(other_post)

    with db.session.no_autoflush:
        own_retired = db.session.get(model.PostRetiredChecksum, post.checksum)
        if own_retired is not None and own_retired.post_id == post.post_id:
            db.session.delete(own_retired)

    if update_signature:
        purge_post_signature(post)
        generate_post_signature(post, content)
    elif file_type is not None:
        # the picture the post had before, if any, is not this file's
        purge_post_signature(post)
        generate_post_signature_from_thumbnail(post, file_type, content)

    post.file_size = content_module.size(content)
    if file_type is not None:
        # not a picture: it has no canvas
        post.canvas_width = None
        post.canvas_height = None
        setattr(post, "__content", content)
        return
    try:
        image = images.Image(content)
        post.canvas_width = image.width
        post.canvas_height = image.height
    except errors.ProcessingError as ex:
        logger.exception(ex)
        if not config.config["allow_broken_uploads"]:
            raise InvalidPostContentError("Unable to process image metadata") from ex
        else:
            post.canvas_width = None
            post.canvas_height = None
    width, height = post.canvas_width, post.canvas_height
    if (width is not None and width <= 0) or (height is not None and height <= 0):
        if not config.config["allow_broken_uploads"]:
            raise InvalidPostContentError(
                "Invalid image dimensions returned during processing"
            )
        else:
            post.canvas_width = None
            post.canvas_height = None
    setattr(post, "__content", content)


def update_post_auto_tags(
    post: model.Post, *, wanted: list[tuple[str, str]] | None = None
) -> list[model.Tag]:
    """
    Add the tags the loaded modules derive from what was extracted from the
    post's file (see lithica.registry.Module.auto_tag). Tags the post has
    stay; a tag that does not exist yet is created in the category the
    module names, or in the default one if the site has no such category.
    Returns the tags created.

    Call it once the post has its tags and before the session is flushed.
    It never fails the request: a module's wish for a tag is not worth an
    upload.
    """
    if wanted is None:
        wanted = post_content.get_auto_tags(post)
    if not wanted:
        return []
    present = {name.name.lower() for tag in post.tags for name in tag.names}
    new_tags: list[model.Tag] = []
    try:
        for category_name, name in wanted:
            if name.lower() in present:
                continue
            existing_tags, created_tags = tags.get_or_create_tags_by_names([name])
            for tag in created_tags:
                if tag_categories.try_get_category_by_name(category_name):
                    tags.update_tag_category_name(tag, category_name)
                else:
                    logger.warning(
                        "No tag category %r: an automatic tag was put in the "
                        "default category.",
                        category_name,
                    )
            for tag in existing_tags + created_tags:
                post.tags.append(tag)
                present |= {tag_name.name.lower() for tag_name in tag.names}
            new_tags += created_tags
    except errors.BaseError as ex:
        # for one: a site without any tag category cannot create a tag
        logger.warning("Automatic tags were not all added: %s", ex)
    return new_tags


def update_post_thumbnail(post: model.Post, content: ContentLike | None = None) -> None:
    require_file(post)
    assert post
    setattr(post, "__thumbnail", content)


def generate_post_thumbnail(post: model.Post) -> None:
    if not has_file(post):
        return
    assert post.mime_type is not None
    file_type = registry.file_type_for(post.mime_type)
    if files.has(get_post_thumbnail_backup_path(post)):
        content = files.get(get_post_thumbnail_backup_path(post))
    else:
        content = files.get(get_post_content_path(post))
        if file_type is not None:
            # a file of a module: the picture the module offers, if any
            content = file_types.get_thumbnail(file_type, content) if content else None
            if content is None:
                files.save(get_post_thumbnail_path(post), EMPTY_PIXEL)
                return
    try:
        assert content
        image = images.Image(content)
        image.resize_fill(
            int(config.config["thumbnails"]["post_width"]),
            int(config.config["thumbnails"]["post_height"]),
        )
        files.save(get_post_thumbnail_path(post), image.to_jpeg())
    except errors.ProcessingError:
        files.save(get_post_thumbnail_path(post), EMPTY_PIXEL)


def update_post_tags(post: model.Post, tag_names: list[str]) -> list[model.Tag]:
    assert post
    existing_tags, new_tags = tags.get_or_create_tags_by_names(tag_names)
    post.tags = existing_tags + new_tags
    return new_tags


def update_post_relations(post: model.Post, new_post_ids: list[int]) -> None:
    assert post
    try:
        new_post_ids = [int(id) for id in new_post_ids]
    except ValueError as ex:
        raise InvalidPostRelationError("A relation must be numeric post ID.") from ex
    old_posts = post.relations
    old_post_ids = [int(p.post_id) for p in old_posts]
    if new_post_ids:
        new_posts = (
            db.session.query(model.Post)
            .filter(model.Post.post_id.in_(new_post_ids))
            .all()
        )
    else:
        new_posts = []
    if len(new_posts) != len(new_post_ids):
        raise InvalidPostRelationError("One of relations does not exist.")
    if post.post_id in new_post_ids:
        raise InvalidPostRelationError("Post cannot relate to itself.")

    relations_to_del = [p for p in old_posts if p.post_id not in new_post_ids]
    relations_to_add = [p for p in new_posts if p.post_id not in old_post_ids]
    for relation in relations_to_del:
        post.relations.remove(relation)
        relation.relations.remove(post)
    for relation in relations_to_add:
        post.relations.append(relation)
        relation.relations.append(post)


def update_post_notes(post: model.Post, notes: Any) -> None:
    assert post
    post.notes = []
    for note in notes:
        for field in ("polygon", "text"):
            if field not in note:
                raise InvalidPostNoteError("Note is missing %r field." % field)
        if not note["text"]:
            raise InvalidPostNoteError("A note's text cannot be empty.")
        if not isinstance(note["polygon"], (list, tuple)):
            raise InvalidPostNoteError("A note's polygon must be a list of points.")
        if len(note["polygon"]) < 3:
            raise InvalidPostNoteError("A note's polygon must have at least 3 points.")
        for point in note["polygon"]:
            if not isinstance(point, (list, tuple)):
                raise InvalidPostNoteError(
                    "A note's polygon point must be a list of length 2."
                )
            if len(point) != 2:
                raise InvalidPostNoteError(
                    "A point in note's polygon must have two coordinates."
                )
            try:
                pos_x = float(point[0])
                pos_y = float(point[1])
                if not 0 <= pos_x <= 1 or not 0 <= pos_y <= 1:
                    raise InvalidPostNoteError(
                        "All points must fit in the image (0..1 range)."
                    )
            except ValueError as ex:
                raise InvalidPostNoteError(
                    "A point in note's polygon must be numeric."
                ) from ex
        if util.value_exceeds_column_size(note["text"], model.PostNote.text):
            raise InvalidPostNoteError("Note text is too long.")
        post.notes.append(
            model.PostNote(polygon=note["polygon"], text=str(note["text"]))
        )


def update_post_flags(post: model.Post, flags: list[str]) -> None:
    assert post
    target_flags = []
    for flag in flags:
        flag = util.flip(FLAG_MAP).get(flag, None)
        if not flag:
            raise InvalidPostFlagError(
                "Flag must be one of %r." % list(FLAG_MAP.values())
            )
        target_flags.append(flag)
    post.flags = target_flags


def feature_post(post: model.Post, user: model.User | None) -> None:
    assert post
    if user and not user.name:
        user = None
    post_feature = model.PostFeature()
    post_feature.time = util.utcnow()
    post_feature.post = post
    post_feature.user = user
    db.session.add(post_feature)


def delete(post: model.Post) -> None:
    assert post
    db.session.delete(post)


def merge_posts(
    source_post: model.Post, target_post: model.Post, replace_content: bool
) -> None:
    require_file(source_post)
    require_file(target_post)
    from lithica.func import documents

    if documents.have_documents([source_post, target_post], lock=True):
        raise errors.ValidationError("Posts with documents cannot be merged.")
    assert source_post
    assert target_post
    if source_post.post_id == target_post.post_id:
        raise InvalidPostRelationError("Cannot merge post with itself.")

    def merge_tables(
        # any mapped class with a post_id column, and a comparison of two
        # aliases of it; which columns exist depends on the class passed in
        table: Any,
        anti_dup_func: Callable[[Any, Any], Any] | None,
        source_post_id: int,
        target_post_id: int,
    ) -> None:
        alias1 = table
        alias2 = sa_orm.aliased(table)
        update_stmt = sa.sql.expression.update(alias1).where(
            alias1.post_id == source_post_id
        )

        if anti_dup_func is not None:
            update_stmt = update_stmt.where(
                ~sa.exists()
                .where(anti_dup_func(alias1, alias2))
                .where(alias2.post_id == target_post_id)
            )

        update_stmt = update_stmt.values(post_id=target_post_id)
        db.session.execute(update_stmt)

    def merge_tags(source_post_id: int, target_post_id: int) -> None:
        merge_tables(
            model.PostTag,
            lambda alias1, alias2: alias1.tag_id == alias2.tag_id,
            source_post_id,
            target_post_id,
        )

    def merge_scores(source_post_id: int, target_post_id: int) -> None:
        merge_tables(
            model.PostScore,
            lambda alias1, alias2: alias1.user_id == alias2.user_id,
            source_post_id,
            target_post_id,
        )

    def merge_favorites(source_post_id: int, target_post_id: int) -> None:
        merge_tables(
            model.PostFavorite,
            lambda alias1, alias2: alias1.user_id == alias2.user_id,
            source_post_id,
            target_post_id,
        )

    def merge_comments(source_post_id: int, target_post_id: int) -> None:
        merge_tables(model.Comment, None, source_post_id, target_post_id)

    def merge_relations(source_post_id: int, target_post_id: int) -> None:
        alias1 = model.PostRelation
        alias2 = sa_orm.aliased(model.PostRelation)
        update_stmt = (
            sa.sql.expression.update(alias1)
            .where(alias1.parent_id == source_post_id)
            .where(alias1.child_id != target_post_id)
            .where(
                ~sa.exists()
                .where(alias2.child_id == alias1.child_id)
                .where(alias2.parent_id == target_post_id)
            )
            .values(parent_id=target_post_id)
        )
        db.session.execute(update_stmt)

        update_stmt = (
            sa.sql.expression.update(alias1)
            .where(alias1.child_id == source_post_id)
            .where(alias1.parent_id != target_post_id)
            .where(
                ~sa.exists()
                .where(alias2.parent_id == alias1.parent_id)
                .where(alias2.child_id == target_post_id)
            )
            .values(child_id=target_post_id)
        )
        db.session.execute(update_stmt)

    from lithica.func import post_metadata

    post_metadata.merge_metadata(source_post, target_post)
    merge_tags(source_post.post_id, target_post.post_id)
    merge_comments(source_post.post_id, target_post.post_id)
    merge_scores(source_post.post_id, target_post.post_id)
    merge_favorites(source_post.post_id, target_post.post_id)
    merge_relations(source_post.post_id, target_post.post_id)

    def transfer_flags(source_post_id: int, target_post_id: int) -> None:
        target = get_post_by_id(target_post_id)
        source = get_post_by_id(source_post_id)
        target.flags = source.flags
        db.session.flush()

    content = None
    if replace_content:
        stored = files.get(get_post_content_path(source_post))
        if stored is not None:
            # the source post is deleted below, and its file with it, before
            # the target takes the content over: keep a copy until then
            content = content_module.temporary_copy(stored)
        transfer_flags(source_post.post_id, target_post.post_id)

    # fixes unknown issue with SA's cascade deletions
    purge_post_signature(source_post)
    delete(source_post)
    db.session.flush()

    if content is not None:
        # The copy is written to the target's file when the post is flushed
        # (see _sync_post_content), which may be after this function
        # returns. It is a temporary content: its file goes away when the
        # post lets go of it.
        update_post_content(target_post, content)


def retire_checksum(post: model.Post, checksum: str, reason: str) -> None:
    """Reserve a former file until its post is deleted."""
    if not reason or len(reason) > 32:
        raise errors.ValidationError("Invalid checksum retirement reason.")
    existing = db.session.get(model.PostRetiredChecksum, checksum)
    if existing is not None:
        if existing.post_id != post.post_id:
            raise PostAlreadyUploadedError(try_get_post_by_id(existing.post_id))
        return
    db.session.add(
        model.PostRetiredChecksum(
            checksum=checksum,
            post_id=post.post_id,
            reason=reason,
            creation_time=util.utcnow(),
        )
    )


def _checksum_matches(checksum: str) -> sa.ColumnElement[bool]:
    return sa.or_(
        model.Post.checksum == checksum,
        model.Post.post_id.in_(
            sa.select(model.PostRetiredChecksum.post_id).where(
                model.PostRetiredChecksum.checksum == checksum
            )
        ),
    )


def search_by_image_exact(image_content: ContentLike) -> model.Post | None:
    checksum = util.get_sha1(image_content)
    return (
        db.session.query(model.Post).filter(_checksum_matches(checksum)).one_or_none()
    )


SIMILAR_SIGNATURE_LIMIT = 100


def _find_similar_signatures(query_words: list[int]) -> list[tuple[int, bytes, int]]:
    """
    Return (post id, packed signature, score) for the signatures that share
    the most words with the query, best first. The score is the number of
    positions at which the stored word equals the query word.
    """
    word = model.PostSignatureWord
    score = sa.func.count().label("score")
    scores = (
        db.session.query(word.post_id.label("post_id"), score)
        .filter(
            sa.or_(
                *[
                    sa.and_(word.position == position, word.word == query_word)
                    for position, query_word in enumerate(query_words)
                ]
            )
        )
        .group_by(word.post_id)
        .order_by(score.desc(), word.post_id.asc())
        .limit(SIMILAR_SIGNATURE_LIMIT)
        .subquery()
    )
    rows = (
        db.session.query(
            model.PostSignature.post_id,
            model.PostSignature.signature,
            scores.c.score,
        )
        .join(scores, scores.c.post_id == model.PostSignature.post_id)
        .order_by(scores.c.score.desc(), model.PostSignature.post_id.asc())
        .all()
    )
    return [(post_id, signature, score) for post_id, signature, score in rows]


def search_by_image(
    image_content: ContentLike,
) -> list[tuple[float, model.Post]]:
    query_signature = image_hash.generate_signature(image_content)
    query_words = image_hash.generate_words(query_signature)

    candidates = _find_similar_signatures(query_words)
    data = tuple(
        zip(
            *[
                (post_id, image_hash.unpack_signature(packedsig))
                for post_id, packedsig, score in candidates
            ],
            strict=False,
        )
    )
    if data:
        candidate_post_ids, sigarray = data
        distances = image_hash.normalized_distance(sigarray, query_signature)
        candidate_posts = [
            (distance, try_get_post_by_id(candidate_post_id))
            for candidate_post_id, distance in zip(
                candidate_post_ids, distances, strict=False
            )
            if distance < image_hash.DISTANCE_CUTOFF
        ]
        # a post deleted since the candidates were read is left out
        return [
            (distance, post)
            for distance, post in candidate_posts
            if post is not None and has_file(post)
        ]
    else:
        return []


def count_posts_for_kind_backfill() -> int:
    return db.session.query(model.Post).filter(with_file()).count()


def update_all_post_kinds() -> tuple[int, int]:
    """Derive kinds from stored rows, without reading files, including manual kinds."""

    def fill(post: model.Post) -> bool:
        post_kinds.derive_existing(post)
        return True

    return _backfill(
        lambda: db.session.query(model.Post).filter(with_file()),
        fill,
        "post kind",
    )
