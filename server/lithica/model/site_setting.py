from datetime import datetime
from typing import Any

import sqlalchemy as sa
import sqlalchemy.event as sa_event
from sqlalchemy.orm import Mapped, mapped_column

from lithica.model.base import Base
from lithica.model.types import json_type


class SiteSetting(Base):
    __tablename__ = "site_setting"
    name: Mapped[str] = mapped_column(sa.Unicode(64), primary_key=True)
    # Any: values are JSON scalars or lists, validated by the settings registry.
    value: Mapped[Any] = mapped_column(json_type(), nullable=False)
    last_edit_time: Mapped[datetime] = mapped_column(sa.DateTime)
    user_id: Mapped[int | None] = mapped_column(
        sa.ForeignKey("user.id", ondelete="SET NULL")
    )


class SiteSettingsVersion(Base):
    __tablename__ = "site_settings_version"
    id: Mapped[int] = mapped_column(primary_key=True)
    version: Mapped[int] = mapped_column(default=1)
    __table_args__ = (
        sa.CheckConstraint(id == 1, name="ck_site_settings_version_singleton"),
    )


@sa_event.listens_for(SiteSettingsVersion.__table__, "after_create")
def _seed_version(
    target: sa.Table, connection: sa.Connection, **kwargs: object
) -> None:
    connection.execute(target.insert().values(id=1, version=1))
