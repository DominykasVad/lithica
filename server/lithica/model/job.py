from datetime import datetime
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from lithica.model.base import Base
from lithica.model.types import json_type
from lithica.registry import Payload

if TYPE_CHECKING:
    from lithica.model.user import User


class Job(Base):
    __tablename__ = "job"
    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[str] = mapped_column(sa.Unicode(32))
    payload: Mapped[Payload] = mapped_column(json_type())
    status: Mapped[str] = mapped_column(sa.Unicode(16))
    attempts: Mapped[int] = mapped_column(default=0)
    max_attempts: Mapped[int]
    run_after: Mapped[datetime] = mapped_column(sa.DateTime)
    claimed_by: Mapped[str | None] = mapped_column(sa.Unicode(512))
    lease_until: Mapped[datetime | None] = mapped_column(sa.DateTime)
    creation_time: Mapped[datetime] = mapped_column(sa.DateTime)
    start_time: Mapped[datetime | None] = mapped_column(sa.DateTime)
    finish_time: Mapped[datetime | None] = mapped_column(sa.DateTime)
    last_error: Mapped[str | None] = mapped_column(sa.UnicodeText)
    user_id: Mapped[int | None] = mapped_column(
        sa.ForeignKey("user.id", ondelete="SET NULL")
    )
    user: Mapped["User | None"] = relationship("User")
    __table_args__ = (sa.Index("ix_job_status_run_after", "status", "run_after"),)
