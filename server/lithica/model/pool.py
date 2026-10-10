from datetime import datetime

import sqlalchemy as sa
import sqlalchemy.orm as sa_orm
from sqlalchemy.ext.associationproxy import association_proxy
from sqlalchemy.ext.orderinglist import ordering_list

from lithica.model.base import Base


class PoolName(Base):
    __tablename__ = "pool_name"

    pool_name_id: sa_orm.Mapped[int] = sa_orm.mapped_column(
        "pool_name_id", sa.Integer, primary_key=True
    )
    pool_id: sa_orm.Mapped[int] = sa_orm.mapped_column(
        "pool_id",
        sa.Integer,
        sa.ForeignKey("pool.id"),
        nullable=False,
        index=True,
    )
    name: sa_orm.Mapped[str] = sa_orm.mapped_column(
        "name", sa.Unicode(128), nullable=False, unique=True
    )
    order: sa_orm.Mapped[int] = sa_orm.mapped_column(
        "ord", sa.Integer, nullable=False, index=True
    )

    def __init__(self, name: str, order: int) -> None:
        self.name = name
        self.order = order


# searches compare lower(name), see lithica.search.configs.util
sa.Index("ix_pool_name_name_lower", sa.func.lower(PoolName.name))


class PoolPost(Base):
    __tablename__ = "pool_post"

    pool_id: sa_orm.Mapped[int] = sa_orm.mapped_column(
        "pool_id",
        sa.Integer,
        sa.ForeignKey("pool.id"),
        nullable=False,
        primary_key=True,
        index=True,
    )
    post_id: sa_orm.Mapped[int] = sa_orm.mapped_column(
        "post_id",
        sa.Integer,
        sa.ForeignKey("post.id"),
        nullable=False,
        primary_key=True,
        index=True,
    )
    order: sa_orm.Mapped[int] = sa_orm.mapped_column(
        "ord", sa.Integer, nullable=False, index=True
    )

    pool = sa_orm.relationship("Pool", back_populates="_posts")
    post = sa_orm.relationship("Post", back_populates="_pools")

    def __init__(self, post) -> None:
        self.post_id = post.post_id


class Pool(Base):
    __tablename__ = "pool"

    pool_id: sa_orm.Mapped[int] = sa_orm.mapped_column(
        "id", sa.Integer, primary_key=True
    )
    category_id: sa_orm.Mapped[int] = sa_orm.mapped_column(
        "category_id",
        sa.Integer,
        sa.ForeignKey("pool_category.id"),
        nullable=False,
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
    description: sa_orm.Mapped[str | None] = sa_orm.mapped_column(
        "description", sa.UnicodeText, default=None
    )

    category = sa_orm.relationship("PoolCategory", lazy="joined")
    names = sa_orm.relationship(
        "PoolName",
        cascade="all,delete-orphan",
        lazy="joined",
        order_by="PoolName.order",
    )
    _posts = sa_orm.relationship(
        "PoolPost",
        cascade="all,delete-orphan",
        lazy="joined",
        back_populates="pool",
        order_by="PoolPost.order",
        collection_class=ordering_list("order"),
    )
    posts = association_proxy("_posts", "post")

    post_count = sa_orm.column_property(
        (
            sa.sql.expression.select(sa.sql.expression.func.count(PoolPost.post_id))
            .where(PoolPost.pool_id == pool_id)
            .scalar_subquery()
        ),
        deferred=True,
    )

    first_name = sa_orm.column_property(
        (
            sa.sql.expression.select(PoolName.name)
            .where(PoolName.pool_id == pool_id)
            .order_by(PoolName.order)
            .limit(1)
            .scalar_subquery()
        ),
        deferred=True,
    )

    __mapper_args__ = {
        "version_id_col": version,
        "version_id_generator": False,
    }
