"""Add typed relations and external IDs."""

import sqlalchemy as sa
from alembic import op

revision = "b7c3d4e5f6a8"
down_revision = "a6b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "post_typed_relation",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "from_post_id",
            sa.Integer,
            sa.ForeignKey("post.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "to_post_id",
            sa.Integer,
            sa.ForeignKey("post.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("type", sa.Unicode(32), nullable=False),
        sa.Column("label", sa.Unicode(128)),
        sa.Column("creation_time", sa.DateTime, nullable=False),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("user.id", ondelete="SET NULL")),
        sa.UniqueConstraint(
            "from_post_id",
            "to_post_id",
            "type",
            name="uq_post_typed_relation_ends_type",
        ),
        sa.CheckConstraint(
            "from_post_id != to_post_id", name="ck_post_typed_relation_distinct_ends"
        ),
    )
    op.create_index(
        "ix_post_typed_relation_from_type",
        "post_typed_relation",
        ["from_post_id", "type"],
    )
    op.create_index(
        "ix_post_typed_relation_to_type", "post_typed_relation", ["to_post_id", "type"]
    )
    op.create_table(
        "post_external_id",
        sa.Column(
            "post_id",
            sa.Integer,
            sa.ForeignKey("post.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("host", sa.Unicode(64), primary_key=True),
        sa.Column("external_id", sa.Unicode(256), primary_key=True),
        sa.Column("creation_time", sa.DateTime, nullable=False),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("user.id", ondelete="SET NULL")),
    )
    op.create_index("ix_post_external_id_post_id", "post_external_id", ["post_id"])


def downgrade() -> None:
    op.drop_table("post_external_id")
    op.drop_table("post_typed_relation")
