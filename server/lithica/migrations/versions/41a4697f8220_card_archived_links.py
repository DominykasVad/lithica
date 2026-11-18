"""Keep card image archives independently of document versions."""

import sqlalchemy as sa
from alembic import op

revision = "41a4697f8220"
down_revision = "528f19f28699"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "cards_card",
        sa.Column("archive_queued", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.create_table(
        "cards_archived_link",
        sa.Column("card_post_id", sa.Integer(), nullable=False),
        sa.Column("url_hash", sa.String(64), nullable=False),
        sa.Column("url", sa.String(2048), nullable=False),
        sa.Column("post_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(8), nullable=False),
        sa.Column("reason", sa.String(16), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_attempt_time", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["card_post_id"], ["post.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["post_id"], ["post.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("card_post_id", "url_hash"),
    )
    op.create_index(
        op.f("ix_cards_archived_link_url_hash"), "cards_archived_link", ["url_hash"]
    )
    op.create_index(
        op.f("ix_cards_archived_link_post_id"), "cards_archived_link", ["post_id"]
    )


def downgrade() -> None:
    op.drop_table("cards_archived_link")
    op.drop_column("cards_card", "archive_queued")
