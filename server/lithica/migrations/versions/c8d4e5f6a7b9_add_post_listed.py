"""List all existing posts; future posts are listed by default in the ORM."""

import sqlalchemy as sa
from alembic import op

revision = "c8d4e5f6a7b9"
down_revision = "b7c3d4e5f6a8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "post",
        sa.Column("listed", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.alter_column("post", "listed", server_default=None)
    op.create_index("ix_post_listed", "post", ["listed"])


def downgrade() -> None:
    op.drop_index("ix_post_listed", table_name="post")
    op.drop_column("post", "listed")
