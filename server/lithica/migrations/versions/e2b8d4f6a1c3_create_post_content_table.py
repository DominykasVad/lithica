"""
Create the post_content table

Content that the extractors of modules read out of uploaded files: one row
per thing found, a JSON payload of some kind per row.

Revision ID: e2b8d4f6a1c3
Created at: 2026-10-11 12:00:00.000000
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "e2b8d4f6a1c3"
down_revision = "d1a7c3e5f9b2"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "post_content",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("post_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.Unicode(length=64), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column(
            "payload",
            sa.JSON().with_variant(JSONB(), "postgresql"),
            nullable=False,
        ),
        sa.Column("extracted_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["post_id"], ["post.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_post_content_post_id_kind",
        "post_content",
        ["post_id", "kind"],
        unique=False,
    )


def downgrade():
    op.drop_index("ix_post_content_post_id_kind", table_name="post_content")
    op.drop_table("post_content")
