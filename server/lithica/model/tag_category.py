import sqlalchemy as sa
import sqlalchemy.orm as sa_orm

from lithica.model.base import Base
from lithica.model.tag import Tag


class TagCategory(Base):
    __tablename__ = "tag_category"

    tag_category_id: sa_orm.Mapped[int] = sa_orm.mapped_column(
        "id", sa.Integer, primary_key=True
    )
    version: sa_orm.Mapped[int] = sa_orm.mapped_column(
        "version", sa.Integer, default=1, nullable=False
    )
    name: sa_orm.Mapped[str] = sa_orm.mapped_column(
        "name", sa.Unicode(32), nullable=False
    )
    color: sa_orm.Mapped[str] = sa_orm.mapped_column(
        "color", sa.Unicode(32), nullable=False, default="#000000"
    )
    default: sa_orm.Mapped[bool] = sa_orm.mapped_column(
        "default", sa.Boolean, nullable=False, default=False
    )
    order: sa_orm.Mapped[int] = sa_orm.mapped_column(
        "order", sa.Integer, nullable=False, default=1
    )

    def __init__(self, name: str | None = None) -> None:
        self.name = name

    tag_count = sa_orm.column_property(
        sa.sql.expression.select(sa.sql.expression.func.count("Tag.tag_id"))
        .where(Tag.category_id == tag_category_id)
        .correlate_except(sa.table("Tag"))
        .scalar_subquery()
    )

    __mapper_args__ = {
        "version_id_col": version,
        "version_id_generator": False,
    }
