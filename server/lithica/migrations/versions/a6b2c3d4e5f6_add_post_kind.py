"""Add the engine post kind, initially media for every existing post."""

import sqlalchemy as sa
from alembic import op

revision = "a6b2c3d4e5f6"
down_revision = "f3a9c1d27b64"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("post", sa.Column("kind", sa.Unicode(32), nullable=False,
                                   server_default="media"))
    op.alter_column("post", "kind", server_default=None)
    op.create_index("ix_post_kind", "post", ["kind"])


def downgrade() -> None:
    op.drop_index("ix_post_kind", table_name="post")
    op.drop_column("post", "kind")
