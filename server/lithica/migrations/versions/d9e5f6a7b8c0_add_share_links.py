"""Store revocable share links without their token values."""

import sqlalchemy as sa
from alembic import op

revision = "d9e5f6a7b8c0"
down_revision = "c8d4e5f6a7b9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "share_link",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "post_id",
            sa.Integer,
            sa.ForeignKey("post.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.Integer,
            sa.ForeignKey("user.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("salt", sa.LargeBinary(32), nullable=False),
        sa.Column("token_hash", sa.Unicode(64), nullable=False),
        sa.Column("note", sa.Unicode(128)),
        sa.Column("creation_time", sa.DateTime, nullable=False),
        sa.Column("expires_at", sa.DateTime),
    )
    for name in ("post_id", "user_id", "token_hash"):
        op.create_index(
            "ix_share_link_" + name, "share_link", [name], unique=name == "token_hash"
        )


def downgrade() -> None:
    op.drop_table("share_link")
