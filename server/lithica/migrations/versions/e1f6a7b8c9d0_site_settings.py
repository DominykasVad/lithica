"""Store site settings and their shared optimistic version."""

import sqlalchemy as sa
from alembic import op

from lithica.model.types import json_type

revision = "e1f6a7b8c9d0"
down_revision = "d9e5f6a7b8c0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "site_setting",
        sa.Column("name", sa.Unicode(64), primary_key=True),
        sa.Column("value", json_type(), nullable=False),
        sa.Column("last_edit_time", sa.DateTime, nullable=False),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("user.id", ondelete="SET NULL")),
    )
    table = op.create_table(
        "site_settings_version",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("version", sa.Integer, nullable=False),
        sa.CheckConstraint("id = 1"),
    )
    op.bulk_insert(table, [{"id": 1, "version": 1}])


def downgrade() -> None:
    op.drop_table("site_settings_version")
    op.drop_table("site_setting")
