"""A module-owned table; no migration because this module is test-only."""

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from lithica.model import Base


class DummyText(Base):
    __tablename__ = "dummy_text"

    post_id: Mapped[int] = mapped_column(
        sa.ForeignKey("post.id", ondelete="CASCADE"), primary_key=True
    )
    text: Mapped[str] = mapped_column(sa.UnicodeText)


class DummyHook(Base):
    __tablename__ = "dummy_hook"

    post_id: Mapped[int] = mapped_column(
        sa.ForeignKey("post.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[int | None] = mapped_column(sa.Integer)
    kind: Mapped[str] = mapped_column(sa.Unicode(32))
