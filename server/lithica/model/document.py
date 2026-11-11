"""Current documents and their independent immutable version history."""

from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from lithica.model.base import Base
from lithica.model.types import json_type
from lithica.model.user import User


class PostDocument(Base):
    __tablename__ = "post_document"
    post_id: Mapped[int] = mapped_column(
        sa.ForeignKey("post.id", ondelete="CASCADE"), primary_key=True
    )
    kind: Mapped[str] = mapped_column(sa.Unicode(32))
    version: Mapped[int] = mapped_column(sa.Integer)
    schema_version: Mapped[int] = mapped_column(sa.Integer)
    hash: Mapped[str] = mapped_column(sa.Unicode(64))
    size: Mapped[int] = mapped_column(sa.Integer)
    # Any: the JSON object shape is defined by the owning module.
    data: Mapped[dict[str, Any]] = mapped_column(json_type(), deferred=True)
    update_time: Mapped[datetime] = mapped_column(sa.DateTime)
    __table_args__ = (sa.Index("ix_post_document_kind_hash", "kind", "hash"),)


class PostDocumentVersion(Base):
    __tablename__ = "post_document_version"
    id: Mapped[int] = mapped_column(primary_key=True)
    post_id: Mapped[int] = mapped_column(sa.ForeignKey("post.id", ondelete="CASCADE"))
    number: Mapped[int] = mapped_column(sa.Integer)
    schema_version: Mapped[int] = mapped_column(sa.Integer)
    hash: Mapped[str] = mapped_column(sa.Unicode(64))
    size: Mapped[int] = mapped_column(sa.Integer)
    data: Mapped[bytes] = mapped_column(sa.LargeBinary, deferred=True)
    creation_time: Mapped[datetime] = mapped_column(sa.DateTime)
    user_id: Mapped[int | None] = mapped_column(
        sa.ForeignKey("user.id", ondelete="SET NULL")
    )
    user: Mapped[User | None] = relationship()
    note: Mapped[str | None] = mapped_column(sa.Unicode(256))
    __table_args__ = (
        sa.UniqueConstraint(
            "post_id", "number", name="uq_post_document_version_number"
        ),
    )
