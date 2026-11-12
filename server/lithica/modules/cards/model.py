"""Current card summaries and ordered links; documents retain their history."""

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from lithica.model import Base


class Card(Base):
    __tablename__ = "cards_card"

    post_id: Mapped[int] = mapped_column(
        sa.ForeignKey("post.id", ondelete="CASCADE"), primary_key=True
    )
    spec: Mapped[str] = mapped_column(sa.Unicode(32))
    name: Mapped[str] = mapped_column(sa.Unicode(200))
    creator: Mapped[str] = mapped_column(sa.Unicode(200))
    greetings: Mapped[int] = mapped_column(sa.Integer)


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
