"""Durable background queue."""

import sqlalchemy as sa
from alembic import op

from lithica.model.types import json_type

revision = "f2a7b8c9d0e1"
down_revision = "e1f6a7b8c9d0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "job",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("type", sa.Unicode(32), nullable=False),
        sa.Column("payload", json_type(), nullable=False),
        sa.Column("status", sa.Unicode(16), nullable=False),
        sa.Column("attempts", sa.Integer, nullable=False),
        sa.Column("max_attempts", sa.Integer, nullable=False),
        sa.Column("run_after", sa.DateTime, nullable=False),
        sa.Column("claimed_by", sa.Unicode(512)),
        sa.Column("lease_until", sa.DateTime),
        sa.Column("creation_time", sa.DateTime, nullable=False),
        sa.Column("start_time", sa.DateTime),
        sa.Column("finish_time", sa.DateTime),
        sa.Column("last_error", sa.UnicodeText),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("user.id", ondelete="SET NULL")),
    )
    op.create_index("ix_job_status_run_after", "job", ["status", "run_after"])


def downgrade() -> None:
    op.drop_table("job")
