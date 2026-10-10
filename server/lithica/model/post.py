from datetime import datetime
from typing import Any

import sqlalchemy as sa
import sqlalchemy.orm as sa_orm
from sqlalchemy.ext.associationproxy import association_proxy
from sqlalchemy.ext.hybrid import hybrid_property

from lithica.model.base import Base
from lithica.model.comment import Comment


class PostFeature(Base):
    __tablename__ = "post_feature"

    post_feature_id: sa_orm.Mapped[int] = sa_orm.mapped_column(
        "id", sa.Integer, primary_key=True
    )
    post_id: sa_orm.Mapped[int] = sa_orm.mapped_column(
        "post_id",
        sa.Integer,
        sa.ForeignKey("post.id"),
        nullable=False,
        index=True,
    )
    user_id: sa_orm.Mapped[int | None] = sa_orm.mapped_column(
        "user_id",
        sa.Integer,
        sa.ForeignKey("user.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    time: sa_orm.Mapped[datetime] = sa_orm.mapped_column(
        "time", sa.DateTime, nullable=False
    )

    post = sa_orm.relationship("Post", back_populates="features")
    user = sa_orm.relationship(
        "User",
        backref=sa_orm.backref("post_features", cascade="all, delete-orphan"),
    )


class PostScore(Base):
    __tablename__ = "post_score"

    post_id: sa_orm.Mapped[int] = sa_orm.mapped_column(
        "post_id",
        sa.Integer,
        sa.ForeignKey("post.id"),
        primary_key=True,
        nullable=False,
        index=True,
    )
    user_id: sa_orm.Mapped[int] = sa_orm.mapped_column(
        "user_id",
        sa.Integer,
        sa.ForeignKey("user.id"),
        primary_key=True,
        nullable=False,
        index=True,
    )
    time: sa_orm.Mapped[datetime] = sa_orm.mapped_column(
        "time", sa.DateTime, nullable=False
    )
    score: sa_orm.Mapped[int] = sa_orm.mapped_column(
        "score", sa.Integer, nullable=False
    )

    post = sa_orm.relationship("Post", back_populates="scores")
    user = sa_orm.relationship(
        "User",
        backref=sa_orm.backref("post_scores", cascade="all, delete-orphan"),
    )


class PostFavorite(Base):
    __tablename__ = "post_favorite"

    post_id: sa_orm.Mapped[int] = sa_orm.mapped_column(
        "post_id",
        sa.Integer,
        sa.ForeignKey("post.id"),
        primary_key=True,
        nullable=False,
        index=True,
    )
    user_id: sa_orm.Mapped[int] = sa_orm.mapped_column(
        "user_id",
        sa.Integer,
        sa.ForeignKey("user.id"),
        primary_key=True,
        nullable=False,
        index=True,
    )
    time: sa_orm.Mapped[datetime] = sa_orm.mapped_column(
        "time", sa.DateTime, nullable=False
    )

    post = sa_orm.relationship("Post", back_populates="favorited_by")
    user = sa_orm.relationship(
        "User",
        backref=sa_orm.backref("post_favorites", cascade="all, delete-orphan"),
    )


class PostNote(Base):
    __tablename__ = "post_note"

    post_note_id: sa_orm.Mapped[int] = sa_orm.mapped_column(
        "id", sa.Integer, primary_key=True
    )
    post_id: sa_orm.Mapped[int] = sa_orm.mapped_column(
        "post_id",
        sa.Integer,
        sa.ForeignKey("post.id"),
        nullable=False,
        index=True,
    )
    polygon: sa_orm.Mapped[Any] = sa_orm.mapped_column(
        "polygon", sa.PickleType, nullable=False
    )
    text: sa_orm.Mapped[str] = sa_orm.mapped_column(
        "text", sa.UnicodeText, nullable=False
    )

    post = sa_orm.relationship("Post", back_populates="notes")


class PostRelation(Base):
    __tablename__ = "post_relation"

    parent_id: sa_orm.Mapped[int] = sa_orm.mapped_column(
        "parent_id",
        sa.Integer,
        sa.ForeignKey("post.id"),
        primary_key=True,
        nullable=False,
        index=True,
    )
    child_id: sa_orm.Mapped[int] = sa_orm.mapped_column(
        "child_id",
        sa.Integer,
        sa.ForeignKey("post.id"),
        primary_key=True,
        nullable=False,
        index=True,
    )

    def __init__(self, parent_id: int, child_id: int) -> None:
        self.parent_id = parent_id
        self.child_id = child_id


class PostTag(Base):
    __tablename__ = "post_tag"

    post_id: sa_orm.Mapped[int] = sa_orm.mapped_column(
        "post_id",
        sa.Integer,
        sa.ForeignKey("post.id"),
        primary_key=True,
        nullable=False,
        index=True,
    )
    tag_id: sa_orm.Mapped[int] = sa_orm.mapped_column(
        "tag_id",
        sa.Integer,
        sa.ForeignKey("tag.id"),
        primary_key=True,
        nullable=False,
        index=True,
    )

    def __init__(self, post_id: int, tag_id: int) -> None:
        self.post_id = post_id
        self.tag_id = tag_id


class PostSignatureWord(Base):
    """
    One word of a post signature. A signature has a fixed number of words and
    two images are candidates for being similar when they have equal words at
    the same positions.
    """

    __tablename__ = "post_signature_word"

    post_id: sa_orm.Mapped[int] = sa_orm.mapped_column(
        "post_id",
        sa.Integer,
        sa.ForeignKey("post_signature.post_id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )
    position: sa_orm.Mapped[int] = sa_orm.mapped_column(
        "position",
        sa.Integer,
        primary_key=True,
        nullable=False,
        autoincrement=False,
    )
    word: sa_orm.Mapped[int] = sa_orm.mapped_column("word", sa.Integer, nullable=False)

    __table_args__ = (
        sa.Index("ix_post_signature_word_word_position", "word", "position"),
    )

    def __init__(self, position: int, word: int) -> None:
        self.position = position
        self.word = word


class PostSignature(Base):
    __tablename__ = "post_signature"

    post_id: sa_orm.Mapped[int] = sa_orm.mapped_column(
        "post_id",
        sa.Integer,
        sa.ForeignKey("post.id"),
        primary_key=True,
        nullable=False,
        index=True,
    )
    signature: sa_orm.Mapped[bytes] = sa_orm.mapped_column(
        "signature", sa.LargeBinary, nullable=False
    )
    word_rows = sa_orm.relationship(
        "PostSignatureWord",
        order_by="PostSignatureWord.position",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    post = sa_orm.relationship("Post", back_populates="signature")

    @property
    def words(self) -> list[int]:
        return [row.word for row in self.word_rows]

    @words.setter
    def words(self, words: list[int]) -> None:
        self.word_rows = [
            PostSignatureWord(position, word) for position, word in enumerate(words)
        ]


class Post(Base):
    __tablename__ = "post"

    SAFETY_SAFE = "safe"
    SAFETY_SKETCHY = "sketchy"
    SAFETY_UNSAFE = "unsafe"

    TYPE_IMAGE = "image"
    TYPE_ANIMATION = "animation"
    TYPE_VIDEO = "video"
    TYPE_FLASH = "flash"

    FLAG_LOOP = "loop"
    FLAG_SOUND = "sound"

    # basic meta
    post_id: sa_orm.Mapped[int] = sa_orm.mapped_column(
        "id", sa.Integer, primary_key=True
    )
    user_id: sa_orm.Mapped[int | None] = sa_orm.mapped_column(
        "user_id",
        sa.Integer,
        sa.ForeignKey("user.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    version: sa_orm.Mapped[int] = sa_orm.mapped_column(
        "version", sa.Integer, default=1, nullable=False
    )
    creation_time: sa_orm.Mapped[datetime] = sa_orm.mapped_column(
        "creation_time", sa.DateTime, nullable=False
    )
    last_edit_time: sa_orm.Mapped[datetime | None] = sa_orm.mapped_column(
        "last_edit_time", sa.DateTime
    )
    safety: sa_orm.Mapped[str] = sa_orm.mapped_column(
        "safety", sa.Unicode(32), nullable=False
    )
    source: sa_orm.Mapped[str | None] = sa_orm.mapped_column("source", sa.Unicode(2048))
    flags_string: sa_orm.Mapped[str | None] = sa_orm.mapped_column(
        "flags", sa.Unicode(32), default=""
    )

    # content description
    type: sa_orm.Mapped[str] = sa_orm.mapped_column(
        "type", sa.Unicode(32), nullable=False
    )
    checksum: sa_orm.Mapped[str] = sa_orm.mapped_column(
        "checksum", sa.Unicode(64), nullable=False
    )
    checksum_md5: sa_orm.Mapped[str | None] = sa_orm.mapped_column(
        "checksum_md5", sa.Unicode(32)
    )
    file_size: sa_orm.Mapped[int | None] = sa_orm.mapped_column(
        "file_size", sa.BigInteger
    )
    canvas_width: sa_orm.Mapped[int | None] = sa_orm.mapped_column(
        "image_width", sa.Integer
    )
    canvas_height: sa_orm.Mapped[int | None] = sa_orm.mapped_column(
        "image_height", sa.Integer
    )
    mime_type: sa_orm.Mapped[str] = sa_orm.mapped_column(
        "mime-type", sa.Unicode(32), nullable=False
    )

    # foreign tables
    user = sa_orm.relationship("User")
    tags = sa_orm.relationship("Tag", backref="posts", secondary="post_tag")
    signature = sa_orm.relationship(
        "PostSignature",
        uselist=False,
        cascade="all, delete, delete-orphan",
        lazy="joined",
        back_populates="post",
    )
    relations = sa_orm.relationship(
        "Post",
        secondary="post_relation",
        primaryjoin=post_id == PostRelation.parent_id,
        secondaryjoin=post_id == PostRelation.child_id,
        lazy="joined",
        backref="related_by",
    )
    features = sa_orm.relationship(
        "PostFeature",
        cascade="all, delete-orphan",
        lazy="joined",
        back_populates="post",
    )
    scores = sa_orm.relationship(
        "PostScore", cascade="all, delete-orphan", lazy="joined", back_populates="post"
    )
    favorited_by = sa_orm.relationship(
        "PostFavorite",
        cascade="all, delete-orphan",
        lazy="joined",
        back_populates="post",
    )
    notes = sa_orm.relationship(
        "PostNote", cascade="all, delete-orphan", lazy="joined", back_populates="post"
    )
    comments = sa_orm.relationship(
        "Comment", cascade="all, delete-orphan", back_populates="post"
    )
    _pools = sa_orm.relationship(
        "PoolPost",
        cascade="all,delete-orphan",
        lazy="select",
        order_by="PoolPost.order",
        back_populates="post",
    )
    pools = association_proxy("_pools", "pool")

    # dynamic columns
    tag_count = sa_orm.column_property(
        sa.sql.expression.select(sa.sql.expression.func.count(PostTag.tag_id))
        .where(PostTag.post_id == post_id)
        .correlate_except(PostTag)
        .scalar_subquery()
    )

    canvas_area = sa_orm.column_property(canvas_width * canvas_height)
    canvas_aspect_ratio = sa_orm.column_property(
        sa.sql.expression.func.cast(canvas_width, sa.Float)
        / sa.sql.expression.func.cast(canvas_height, sa.Float)
    )

    @property
    def is_featured(self) -> bool:
        featured_post = (
            sa_orm.object_session(self)
            .query(PostFeature)
            .order_by(PostFeature.time.desc())
            .first()
        )
        return featured_post and featured_post.post_id == self.post_id

    @hybrid_property
    def flags(self) -> list[str]:
        return sorted([x for x in self.flags_string.split(",") if x])

    @flags.setter
    def flags(self, data: list[str]) -> None:
        self.flags_string = ",".join([x for x in data if x])

    score = sa_orm.column_property(
        sa.sql.expression.select(
            sa.sql.expression.func.coalesce(
                sa.sql.expression.func.sum(PostScore.score), 0
            )
        )
        .where(PostScore.post_id == post_id)
        .correlate_except(PostScore)
        .scalar_subquery()
    )

    favorite_count = sa_orm.column_property(
        sa.sql.expression.select(sa.sql.expression.func.count(PostFavorite.post_id))
        .where(PostFavorite.post_id == post_id)
        .correlate_except(PostFavorite)
        .scalar_subquery()
    )

    last_favorite_time = sa_orm.column_property(
        sa.sql.expression.select(sa.sql.expression.func.max(PostFavorite.time))
        .where(PostFavorite.post_id == post_id)
        .correlate_except(PostFavorite)
        .scalar_subquery()
    )

    feature_count = sa_orm.column_property(
        sa.sql.expression.select(sa.sql.expression.func.count(PostFeature.post_id))
        .where(PostFeature.post_id == post_id)
        .correlate_except(PostFeature)
        .scalar_subquery()
    )

    last_feature_time = sa_orm.column_property(
        sa.sql.expression.select(sa.sql.expression.func.max(PostFeature.time))
        .where(PostFeature.post_id == post_id)
        .correlate_except(PostFeature)
        .scalar_subquery()
    )

    comment_count = sa_orm.column_property(
        sa.sql.expression.select(sa.sql.expression.func.count(Comment.post_id))
        .where(Comment.post_id == post_id)
        .correlate_except(Comment)
        .scalar_subquery()
    )

    last_comment_creation_time = sa_orm.column_property(
        sa.sql.expression.select(sa.sql.expression.func.max(Comment.creation_time))
        .where(Comment.post_id == post_id)
        .correlate_except(Comment)
        .scalar_subquery()
    )

    last_comment_edit_time = sa_orm.column_property(
        sa.sql.expression.select(sa.sql.expression.func.max(Comment.last_edit_time))
        .where(Comment.post_id == post_id)
        .correlate_except(Comment)
        .scalar_subquery()
    )

    note_count = sa_orm.column_property(
        sa.sql.expression.select(sa.sql.expression.func.count(PostNote.post_id))
        .where(PostNote.post_id == post_id)
        .correlate_except(PostNote)
        .scalar_subquery()
    )

    relation_count = sa_orm.column_property(
        sa.sql.expression.select(sa.sql.expression.func.count(PostRelation.child_id))
        .where((PostRelation.parent_id == post_id) | (PostRelation.child_id == post_id))
        .correlate_except(PostRelation)
        .scalar_subquery()
    )

    __mapper_args__ = {
        "version_id_col": version,
        "version_id_generator": False,
    }
