from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from lithica.model.base import Base


class ShareLink(Base):
    __tablename__ = "share_link"
    id: Mapped[int] = mapped_column(primary_key=True)
    post_id: Mapped[int] = mapped_column(
        sa.ForeignKey("post.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int] = mapped_column(
        sa.ForeignKey("user.id", ondelete="CASCADE"), index=True
    )
    salt: Mapped[bytes] = mapped_column(sa.LargeBinary(32))
    token_hash: Mapped[str] = mapped_column(sa.Unicode(64), unique=True, index=True)
    note: Mapped[str | None] = mapped_column(sa.Unicode(128))
    creation_time: Mapped[datetime] = mapped_column(sa.DateTime)
    expires_at: Mapped[datetime | None] = mapped_column(sa.DateTime)
    user = relationship("User")
