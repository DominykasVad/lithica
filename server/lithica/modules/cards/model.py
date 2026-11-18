"""Current card summaries and ordered links; documents retain their history."""

from datetime import datetime
from typing import Literal

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from lithica.model import Base


class Card(Base):
    __tablename__ = "cards_card"

    post_id: Mapped[int] = mapped_column(
        sa.ForeignKey("post.id", ondelete="CASCADE"), primary_key=True
    )
    images_read: Mapped[bool] = mapped_column(
        sa.Boolean, default=False, server_default=sa.false()
    )
    archive_queued: Mapped[bool] = mapped_column(
        sa.Boolean, default=False, server_default=sa.false()
    )
    spec: Mapped[str] = mapped_column(sa.Unicode(32))
    name: Mapped[str] = mapped_column(sa.Unicode(200))
    creator: Mapped[str] = mapped_column(sa.Unicode(200))
    greetings: Mapped[int] = mapped_column(sa.Integer)
    data_hash: Mapped[str | None] = mapped_column(sa.String(64), index=True)
    avatar_post_id: Mapped[int | None] = mapped_column(
        sa.ForeignKey("post.id", ondelete="SET NULL")
    )


class Lorebook(Base):
    __tablename__ = "cards_lorebook"

    post_id: Mapped[int] = mapped_column(
        sa.ForeignKey("post.id", ondelete="CASCADE"), primary_key=True
    )
    name: Mapped[str] = mapped_column(sa.Unicode(200))
    entries: Mapped[int] = mapped_column(sa.Integer)


class CardLorebook(Base):
    __tablename__ = "cards_card_lorebook"
    __table_args__ = (
        sa.UniqueConstraint(
            "card_post_id", "lorebook_post_id", name="uq_cards_card_lorebook"
        ),
    )

    card_post_id: Mapped[int] = mapped_column(
        sa.ForeignKey("post.id", ondelete="CASCADE"), primary_key=True
    )
    lorebook_post_id: Mapped[int] = mapped_column(
        sa.ForeignKey("post.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(sa.Integer, primary_key=True)


class CardImage(Base):
    __tablename__ = "cards_card_image"

    card_post_id: Mapped[int] = mapped_column(
        sa.ForeignKey("post.id", ondelete="CASCADE"), primary_key=True
    )
    uri: Mapped[str] = mapped_column(sa.String(1024), primary_key=True)
    post_id: Mapped[int] = mapped_column(
        sa.ForeignKey("post.id", ondelete="CASCADE"), index=True
    )
    type: Mapped[str] = mapped_column(sa.String(32))
    asset_type: Mapped[str | None] = mapped_column(sa.String(64))
    label: Mapped[str | None] = mapped_column(sa.String(128))
    position: Mapped[int] = mapped_column(sa.Integer)


ArchiveStatus = Literal["archived", "failed"]
ArchiveReason = Literal["failed", "too-large", "not-media", "unavailable"]


class ArchivedLink(Base):
    __tablename__ = "cards_archived_link"

    card_post_id: Mapped[int] = mapped_column(
        sa.ForeignKey("post.id", ondelete="CASCADE"), primary_key=True
    )
    url_hash: Mapped[str] = mapped_column(sa.String(64), primary_key=True, index=True)
    url: Mapped[str] = mapped_column(sa.String(2048))
    post_id: Mapped[int | None] = mapped_column(
        sa.ForeignKey("post.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[ArchiveStatus] = mapped_column(sa.String(8))
    reason: Mapped[ArchiveReason | None] = mapped_column(sa.String(16))
    attempts: Mapped[int] = mapped_column(sa.Integer)
    last_attempt_time: Mapped[datetime] = mapped_column(sa.DateTime)
