"""
Index lower-cased names

Revision ID: c4e8f1a2b3d5
Created at: 2026-10-10 23:20:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "c4e8f1a2b3d5"
down_revision = "b7d2e9a4c1f3"
branch_labels = None
depends_on = None

INDEXES = [
    ("ix_tag_name_name_lower", "tag_name"),
    ("ix_pool_name_name_lower", "pool_name"),
    ("ix_user_name_lower", "user"),
]


def upgrade():
    for index_name, table_name in INDEXES:
        op.create_index(
            index_name,
            table_name,
            [sa.func.lower(sa.column("name"))],
            unique=False,
        )


def downgrade():
    for index_name, table_name in reversed(INDEXES):
        op.drop_index(index_name, table_name=table_name)
