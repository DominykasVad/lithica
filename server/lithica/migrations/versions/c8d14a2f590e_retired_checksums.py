"""Reserve former post files.

Revision ID: c8d14a2f590e
Revises: aa29ed2f410b
"""

import sqlalchemy as sa
from alembic import op

revision = "c8d14a2f590e"
down_revision = "aa29ed2f410b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "post_retired_checksum",
        sa.Column("checksum", sa.Unicode(64), nullable=False),
        sa.Column("post_id", sa.Integer(), nullable=False),
        sa.Column("reason", sa.Unicode(32), nullable=False),
        sa.Column("creation_time", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("checksum"),
        sa.ForeignKeyConstraint(["post_id"], ["post.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_post_retired_checksum_post_id", "post_retired_checksum", ["post_id"])


def downgrade() -> None:
    op.drop_table("post_retired_checksum")
