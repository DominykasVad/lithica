"""Store current JSON documents and compressed full versions."""

import sqlalchemy as sa
from alembic import op

from lithica.model.types import json_type

revision = "b4c9d0e1f2a3"
down_revision = "a3b8c9d0e1f2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("post_document",
        sa.Column("post_id", sa.Integer, sa.ForeignKey("post.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("kind", sa.Unicode(32), nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("schema_version", sa.Integer, nullable=False),
        sa.Column("hash", sa.Unicode(64), nullable=False),
        sa.Column("size", sa.Integer, nullable=False),
        sa.Column("data", json_type(), nullable=False),
        sa.Column("update_time", sa.DateTime, nullable=False),
    )
    op.create_index("ix_post_document_kind_hash", "post_document", ["kind", "hash"])
    op.create_table("post_document_version",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("post_id", sa.Integer, sa.ForeignKey("post.id", ondelete="CASCADE"), nullable=False),
        sa.Column("number", sa.Integer, nullable=False),
        sa.Column("schema_version", sa.Integer, nullable=False),
        sa.Column("hash", sa.Unicode(64), nullable=False),
        sa.Column("size", sa.Integer, nullable=False),
        sa.Column("data", sa.LargeBinary, nullable=False),
        sa.Column("creation_time", sa.DateTime, nullable=False),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("user.id", ondelete="SET NULL")),
        sa.Column("note", sa.Unicode(256)),
        sa.UniqueConstraint("post_id", "number", name="uq_post_document_version_number"),
    )


def downgrade() -> None:
    op.drop_table("post_document_version")
    op.drop_table("post_document")
