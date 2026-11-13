"""Index card data identity without rewriting document history.

Revision ID: d72a01c42e90
Revises: c8d14a2f590e
"""

import sqlalchemy as sa
from alembic import op

revision = "d72a01c42e90"
down_revision = "c8d14a2f590e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("cards_card", sa.Column("data_hash", sa.String(64), nullable=True))
    op.create_index("ix_cards_card_data_hash", "cards_card", ["data_hash"])


def downgrade() -> None:
    op.drop_index("ix_cards_card_data_hash", table_name="cards_card")
    op.drop_column("cards_card", "data_hash")
