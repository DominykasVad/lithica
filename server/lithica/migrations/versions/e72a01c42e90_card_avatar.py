"""Project the main avatar independently of alternate avatar relations.

Revision ID: e72a01c42e90
Revises: d72a01c42e90
"""

import sqlalchemy as sa
from alembic import op

revision = "e72a01c42e90"
down_revision = "d72a01c42e90"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("cards_card", sa.Column("avatar_post_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_cards_card_avatar_post", "cards_card", "post", ["avatar_post_id"], ["id"], ondelete="SET NULL")


def downgrade() -> None:
    op.drop_constraint("fk_cards_card_avatar_post", "cards_card", type_="foreignkey")
    op.drop_column("cards_card", "avatar_post_id")
