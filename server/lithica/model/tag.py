from datetime import datetime

import sqlalchemy as sa
import sqlalchemy.orm as sa_orm

from lithica.model.base import Base
from lithica.model.post import PostTag


class TagSuggestion(Base):
    __tablename__ = "tag_suggestion"

    parent_id: sa_orm.Mapped[int] = sa_orm.mapped_column(
        "parent_id",
        sa.Integer,
        sa.ForeignKey("tag.id"),
        nullable=False,
        primary_key=True,
        index=True,
    )
    child_id: sa_orm.Mapped[int] = sa_orm.mapped_column(
        "child_id",
        sa.Integer,
        sa.ForeignKey("tag.id"),
        nullable=False,
        primary_key=True,
        index=True,
    )

    def __init__(self, parent_id: int, child_id: int) -> None:
        self.parent_id = parent_id
        self.child_id = child_id


class TagImplication(Base):
    __tablename__ = "tag_implication"

    parent_id: sa_orm.Mapped[int] = sa_orm.mapped_column(
        "parent_id",
        sa.Integer,
        sa.ForeignKey("tag.id"),
        nullable=False,
        primary_key=True,
        index=True,
    )
    child_id: sa_orm.Mapped[int] = sa_orm.mapped_column(
        "child_id",
        sa.Integer,
        sa.ForeignKey("tag.id"),
        nullable=False,
        primary_key=True,
        index=True,
    )

    def __init__(self, parent_id: int, child_id: int) -> None:
        self.parent_id = parent_id
        self.child_id = child_id


class TagName(Base):
    __tablename__ = "tag_name"

    tag_name_id: sa_orm.Mapped[int] = sa_orm.mapped_column(
        "tag_name_id", sa.Integer, primary_key=True
    )
    tag_id: sa_orm.Mapped[int] = sa_orm.mapped_column(
        "tag_id",
        sa.Integer,
        sa.ForeignKey("tag.id"),
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
sa.Index("ix_tag_name_name_lower", sa.func.lower(TagName.name))


class Tag(Base):
    __tablename__ = "tag"

    tag_id: sa_orm.Mapped[int] = sa_orm.mapped_column(
        "id", sa.Integer, primary_key=True
    )
    category_id: sa_orm.Mapped[int] = sa_orm.mapped_column(
        "category_id",
        sa.Integer,
        sa.ForeignKey("tag_category.id"),
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

    category = sa_orm.relationship("TagCategory", lazy="joined")
    names = sa_orm.relationship(
        "TagName",
        cascade="all,delete-orphan",
        lazy="joined",
        order_by="TagName.order",
    )
    suggestions = sa_orm.relationship(
        "Tag",
        secondary="tag_suggestion",
        primaryjoin=tag_id == TagSuggestion.parent_id,
        secondaryjoin=tag_id == TagSuggestion.child_id,
        lazy="joined",
    )
    implications = sa_orm.relationship(
        "Tag",
        secondary="tag_implication",
        primaryjoin=tag_id == TagImplication.parent_id,
        secondaryjoin=tag_id == TagImplication.child_id,
        lazy="joined",
    )

    post_count = sa_orm.column_property(
        sa.sql.expression.select(sa.sql.expression.func.count(PostTag.post_id))
        .where(PostTag.tag_id == tag_id)
        .correlate_except(PostTag)
        .scalar_subquery()
    )

    first_name = sa_orm.column_property(
        (
            sa.sql.expression.select(TagName.name)
            .where(TagName.tag_id == tag_id)
            .order_by(TagName.order)
            .limit(1)
            .scalar_subquery()
        ),
        deferred=True,
    )

    suggestion_count = sa_orm.column_property(
        (
            sa.sql.expression.select(
                sa.sql.expression.func.count(TagSuggestion.child_id)
            )
            .where(TagSuggestion.parent_id == tag_id)
            .scalar_subquery()
        ),
        deferred=True,
    )

    implication_count = sa_orm.column_property(
        (
            sa.sql.expression.select(
                sa.sql.expression.func.count(TagImplication.child_id)
            )
            .where(TagImplication.parent_id == tag_id)
            .scalar_subquery()
        ),
        deferred=True,
    )

    __mapper_args__ = {
        "version_id_col": version,
        "version_id_generator": False,
    }
