from datetime import datetime
from typing import Any

import sqlalchemy as sa
import sqlalchemy.orm as sa_orm

from lithica.model.base import Base


class Snapshot(Base):
    __tablename__ = "snapshot"

    OPERATION_CREATED = "created"
    OPERATION_MODIFIED = "modified"
    OPERATION_DELETED = "deleted"
    OPERATION_MERGED = "merged"

    snapshot_id: sa_orm.Mapped[int] = sa_orm.mapped_column(
        "id", sa.Integer, primary_key=True
    )
    creation_time: sa_orm.Mapped[datetime] = sa_orm.mapped_column(
        "creation_time", sa.DateTime, nullable=False
    )
    operation: sa_orm.Mapped[str] = sa_orm.mapped_column(
        "operation", sa.Unicode(16), nullable=False
    )
    resource_type: sa_orm.Mapped[str] = sa_orm.mapped_column(
        "resource_type", sa.Unicode(32), nullable=False, index=True
    )
    resource_pkey: sa_orm.Mapped[int] = sa_orm.mapped_column(
        "resource_pkey", sa.Integer, nullable=False, index=True
    )
    resource_name: sa_orm.Mapped[str] = sa_orm.mapped_column(
        "resource_name", sa.Unicode(128), nullable=False
    )
    user_id: sa_orm.Mapped[int | None] = sa_orm.mapped_column(
        "user_id",
        sa.Integer,
        sa.ForeignKey("user.id", ondelete="set null"),
        nullable=True,
    )
    data: sa_orm.Mapped[Any | None] = sa_orm.mapped_column("data", sa.PickleType)

    user = sa_orm.relationship("User")
