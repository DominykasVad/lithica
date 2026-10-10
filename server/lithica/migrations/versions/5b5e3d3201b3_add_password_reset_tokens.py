"""
Add password reset tokens

Revision ID: 5b5e3d3201b3
Created at: 2026-10-10 21:58:49.639188
"""

import sqlalchemy as sa
from alembic import op

revision = "5b5e3d3201b3"
down_revision = "5b5c940b4e78"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "password_reset_token",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.Unicode(length=64), nullable=False),
        sa.Column("creation_time", sa.DateTime(), nullable=False),
        sa.Column("expiration_time", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_password_reset_token_user_id"),
        "password_reset_token",
        ["user_id"],
        unique=False,
    )


def downgrade():
    op.drop_index(
        op.f("ix_password_reset_token_user_id"),
        table_name="password_reset_token",
    )
    op.drop_table("password_reset_token")
