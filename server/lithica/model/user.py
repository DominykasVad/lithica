from datetime import datetime

import sqlalchemy as sa
import sqlalchemy.orm as sa_orm

from lithica.model.base import Base
from lithica.model.comment import Comment
from lithica.model.post import Post, PostFavorite, PostScore


class User(Base):
    __tablename__ = "user"

    AVATAR_GRAVATAR = "gravatar"
    AVATAR_MANUAL = "manual"

    RANK_ANONYMOUS = "anonymous"
    RANK_RESTRICTED = "restricted"
    RANK_REGULAR = "regular"
    RANK_POWER = "power"
    RANK_MODERATOR = "moderator"
    RANK_ADMINISTRATOR = "administrator"
    RANK_NOBODY = "nobody"  # unattainable, used for privileges

    user_id: sa_orm.Mapped[int] = sa_orm.mapped_column(
        "id", sa.Integer, primary_key=True
    )
    creation_time: sa_orm.Mapped[datetime] = sa_orm.mapped_column(
        "creation_time", sa.DateTime, nullable=False
    )
    last_login_time: sa_orm.Mapped[datetime | None] = sa_orm.mapped_column(
        "last_login_time", sa.DateTime
    )
    version: sa_orm.Mapped[int] = sa_orm.mapped_column(
        "version", sa.Integer, default=1, nullable=False
    )
    name: sa_orm.Mapped[str] = sa_orm.mapped_column(
        "name", sa.Unicode(50), nullable=False, unique=True
    )
    password_hash: sa_orm.Mapped[str] = sa_orm.mapped_column(
        "password_hash", sa.Unicode(128), nullable=False
    )
    password_salt: sa_orm.Mapped[str | None] = sa_orm.mapped_column(
        "password_salt", sa.Unicode(32)
    )
    password_revision: sa_orm.Mapped[int] = sa_orm.mapped_column(
        "password_revision", sa.SmallInteger, default=0, nullable=False
    )
    email: sa_orm.Mapped[str | None] = sa_orm.mapped_column(
        "email", sa.Unicode(64), nullable=True
    )
    rank: sa_orm.Mapped[str] = sa_orm.mapped_column(
        "rank", sa.Unicode(32), nullable=False
    )
    avatar_style: sa_orm.Mapped[str] = sa_orm.mapped_column(
        "avatar_style", sa.Unicode(32), nullable=False, default=AVATAR_GRAVATAR
    )

    comments = sa_orm.relationship("Comment", back_populates="user")

    @property
    def post_count(self) -> int:
        from lithica.db import session

        return (
            session.query(sa.sql.expression.func.sum(1))
            .filter(Post.user_id == self.user_id)
            .one()[0]
            or 0
        )

    @property
    def comment_count(self) -> int:
        from lithica.db import session

        return (
            session.query(sa.sql.expression.func.sum(1))
            .filter(Comment.user_id == self.user_id)
            .one()[0]
            or 0
        )

    @property
    def favorite_post_count(self) -> int:
        from lithica.db import session

        return (
            session.query(sa.sql.expression.func.sum(1))
            .filter(PostFavorite.user_id == self.user_id)
            .one()[0]
            or 0
        )

    @property
    def liked_post_count(self) -> int:
        from lithica.db import session

        return (
            session.query(sa.sql.expression.func.sum(1))
            .filter(PostScore.user_id == self.user_id)
            .filter(PostScore.score == 1)
            .one()[0]
            or 0
        )

    @property
    def disliked_post_count(self) -> int:
        from lithica.db import session

        return (
            session.query(sa.sql.expression.func.sum(1))
            .filter(PostScore.user_id == self.user_id)
            .filter(PostScore.score == -1)
            .one()[0]
            or 0
        )

    __mapper_args__ = {
        "version_id_col": version,
        "version_id_generator": False,
    }


# searches compare lower(name), see lithica.search.configs.util
sa.Index("ix_user_name_lower", sa.func.lower(User.name))


class UserToken(Base):
    __tablename__ = "user_token"

    user_token_id: sa_orm.Mapped[int] = sa_orm.mapped_column(
        "id", sa.Integer, primary_key=True
    )
    user_id: sa_orm.Mapped[int] = sa_orm.mapped_column(
        "user_id",
        sa.Integer,
        sa.ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    token: sa_orm.Mapped[str] = sa_orm.mapped_column(
        "token", sa.Unicode(36), nullable=False
    )
    note: sa_orm.Mapped[str | None] = sa_orm.mapped_column(
        "note", sa.Unicode(128), nullable=True
    )
    enabled: sa_orm.Mapped[bool] = sa_orm.mapped_column(
        "enabled", sa.Boolean, nullable=False, default=True
    )
    expiration_time: sa_orm.Mapped[datetime | None] = sa_orm.mapped_column(
        "expiration_time", sa.DateTime, nullable=True
    )
    creation_time: sa_orm.Mapped[datetime] = sa_orm.mapped_column(
        "creation_time", sa.DateTime, nullable=False
    )
    last_edit_time: sa_orm.Mapped[datetime | None] = sa_orm.mapped_column(
        "last_edit_time", sa.DateTime
    )
    last_usage_time: sa_orm.Mapped[datetime | None] = sa_orm.mapped_column(
        "last_usage_time", sa.DateTime
    )
    version: sa_orm.Mapped[int] = sa_orm.mapped_column(
        "version", sa.Integer, default=1, nullable=False
    )

    user = sa_orm.relationship("User")


class PasswordResetToken(Base):
    """
    A pending password reset. Only a hash of the token is stored; the token
    itself exists in the e-mail sent to the user and nowhere else.
    """

    __tablename__ = "password_reset_token"

    password_reset_token_id: sa_orm.Mapped[int] = sa_orm.mapped_column(
        "id", sa.Integer, primary_key=True
    )
    user_id: sa_orm.Mapped[int] = sa_orm.mapped_column(
        "user_id",
        sa.Integer,
        sa.ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    token_hash: sa_orm.Mapped[str] = sa_orm.mapped_column(
        "token_hash", sa.Unicode(64), nullable=False
    )
    creation_time: sa_orm.Mapped[datetime] = sa_orm.mapped_column(
        "creation_time", sa.DateTime, nullable=False
    )
    expiration_time: sa_orm.Mapped[datetime] = sa_orm.mapped_column(
        "expiration_time", sa.DateTime, nullable=False
    )

    user = sa_orm.relationship("User")
