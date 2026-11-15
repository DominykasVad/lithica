"""
Track the images of each current card file

Revision ID: 528f19f28699
Created at: 2026-11-15 19:20:01.823901
"""

import sqlalchemy as sa
from alembic import op


revision = "528f19f28699"
down_revision = "e72a01c42e90"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cards_card_image",
        sa.Column("card_post_id", sa.Integer(), nullable=False),
        sa.Column("uri", sa.String(length=1024), nullable=False),
        sa.Column("post_id", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("asset_type", sa.String(length=64), nullable=True),
        sa.Column("label", sa.String(length=128), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["card_post_id"], ["post.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["post_id"], ["post.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("card_post_id", "uri"),
    )
    op.create_index(
        op.f("ix_cards_card_image_post_id"),
        "cards_card_image",
        ["post_id"],
        unique=False,
    )
    op.add_column(
        "cards_card",
        sa.Column(
            "images_read", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
    )


def downgrade() -> None:
    op.drop_column("cards_card", "images_read")
    op.drop_index(op.f("ix_cards_card_image_post_id"), table_name="cards_card_image")
    op.drop_table("cards_card_image")
