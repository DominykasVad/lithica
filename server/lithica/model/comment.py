from datetime import datetime

import sqlalchemy as sa
import sqlalchemy.orm as sa_orm

from lithica.db import get_session
from lithica.model.base import Base


class CommentScore(Base):
    __tablename__ = "comment_score"

    comment_id: sa_orm.Mapped[int] = sa_orm.mapped_column(
        "comment_id",
        sa.Integer,
        sa.ForeignKey("comment.id"),
        nullable=False,
        primary_key=True,
    )
    user_id: sa_orm.Mapped[int] = sa_orm.mapped_column(
        "user_id",
        sa.Integer,
        sa.ForeignKey("user.id"),
        nullable=False,
        primary_key=True,
        index=True,
    )
    time: sa_orm.Mapped[datetime] = sa_orm.mapped_column(
        "time", sa.DateTime, nullable=False
    )
    score: sa_orm.Mapped[int] = sa_orm.mapped_column(
        "score", sa.Integer, nullable=False
    )

    comment = sa_orm.relationship("Comment", back_populates="scores")
    user = sa_orm.relationship(
        "User",
        backref=sa_orm.backref("comment_scores", cascade="all, delete-orphan"),
    )


class Comment(Base):
    __tablename__ = "comment"

    comment_id: sa_orm.Mapped[int] = sa_orm.mapped_column(
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
    version: sa_orm.Mapped[int] = sa_orm.mapped_column(
        "version", sa.Integer, default=1, nullable=False
    )
    creation_time: sa_orm.Mapped[datetime] = sa_orm.mapped_column(
        "creation_time", sa.DateTime, nullable=False
    )
    last_edit_time: sa_orm.Mapped[datetime | None] = sa_orm.mapped_column(
        "last_edit_time", sa.DateTime
    )
    text: sa_orm.Mapped[str | None] = sa_orm.mapped_column(
        "text", sa.UnicodeText, default=None
    )

    user = sa_orm.relationship("User", back_populates="comments")
    post = sa_orm.relationship("Post", back_populates="comments")
    scores = sa_orm.relationship(
        "CommentScore",
        cascade="all, delete-orphan",
        lazy="joined",
        back_populates="comment",
    )

    @property
    def score(self) -> int:
        return (
            get_session()
            .query(sa.sql.expression.func.sum(CommentScore.score))
            .filter(CommentScore.comment_id == self.comment_id)
            .one()[0]
            or 0
        )

    __mapper_args__ = {
        "version_id_col": version,
        "version_id_generator": False,
    }
