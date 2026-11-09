"""
Store login tokens as hashes; add app tokens

The token table keeps a SHA-256 hash (hex) of each value instead of the
value. Existing values are hashed here, in Python, in batches; the tokens
keep working, as the value a client presents is hashed the same way. Rows
get a kind (`login` for all of them now; `app` for app tokens from now on)
and app tokens their rights.

downgrade() cannot give the values back: it brings back the column of the
values and deletes every token row, so everyone logs in again.

Revision ID: f3a9c1d27b64
Created at: 2026-11-08 12:00:00.000000
"""

import hashlib

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "f3a9c1d27b64"
down_revision = "e2b8d4f6a1c3"
branch_labels = None
depends_on = None

BATCH_SIZE = 1000

# the table as this migration sees it, whatever the models say later
_tokens = sa.table(
    "user_token",
    sa.column("id", sa.Integer),
    sa.column("token", sa.Unicode(36)),
    sa.column("token_hash", sa.Unicode(64)),
    sa.column("kind", sa.Unicode(16)),
)


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf8")).hexdigest()


def upgrade():
    op.add_column(
        "user_token", sa.Column("token_hash", sa.Unicode(length=64), nullable=True)
    )
    op.add_column("user_token", sa.Column("kind", sa.Unicode(length=16), nullable=True))
    op.add_column(
        "user_token",
        sa.Column(
            "rights",
            sa.JSON(none_as_null=True).with_variant(
                JSONB(none_as_null=True), "postgresql"
            ),
            nullable=True,
        ),
    )

    # Only rows not hashed yet, so a run that stopped part-way picks up
    # where it was; by id, so that each batch moves on.
    connection = op.get_bind()
    last_id = 0
    while True:
        rows = connection.execute(
            sa.select(_tokens.c.id, _tokens.c.token)
            .where(_tokens.c.token_hash.is_(None))
            .where(_tokens.c.id > last_id)
            .order_by(_tokens.c.id)
            .limit(BATCH_SIZE)
        ).all()
        if not rows:
            break
        for row_id, value in rows:
            connection.execute(
                sa.update(_tokens)
                .where(_tokens.c.id == row_id)
                .values(token_hash=_hash(value))
            )
        last_id = rows[-1][0]
    connection.execute(
        sa.update(_tokens).where(_tokens.c.kind.is_(None)).values(kind="login")
    )

    op.alter_column("user_token", "token_hash", nullable=False)
    op.alter_column("user_token", "kind", nullable=False)
    op.create_index(
        "ix_user_token_token_hash", "user_token", ["token_hash"], unique=True
    )
    op.drop_column("user_token", "token")


def downgrade():
    # The values are gone for good: without them no row can be used, and the
    # old column cannot be filled. Every token is deleted; everyone logs in
    # again.
    op.execute(sa.delete(_tokens))
    op.add_column(
        "user_token",
        sa.Column("token", sa.Unicode(length=36), nullable=False),
    )
    op.drop_index("ix_user_token_token_hash", table_name="user_token")
    op.drop_column("user_token", "rights")
    op.drop_column("user_token", "kind")
    op.drop_column("user_token", "token_hash")
