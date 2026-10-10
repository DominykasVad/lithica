"""
Add post signature words

Revision ID: 8f3a1c2d4e5b
Created at: 2026-10-10 22:40:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "8f3a1c2d4e5b"
down_revision = "5b5e3d3201b3"
branch_labels = None
depends_on = None

BATCH_SIZE = 1000


def upgrade():
    word_table = op.create_table(
        "post_signature_word",
        sa.Column("post_id", sa.Integer(), nullable=False),
        sa.Column(
            "position", sa.Integer(), autoincrement=False, nullable=False
        ),
        sa.Column("word", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["post_id"], ["post_signature.post_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("post_id", "position"),
    )
    op.create_index(
        "ix_post_signature_word_word_position",
        "post_signature_word",
        ["word", "position"],
        unique=False,
    )

    # Copy the words out of the post_signature.words array, a batch of
    # signatures at a time. Signatures that already have their words are
    # skipped, so the copy can be repeated.
    signature_table = sa.table(
        "post_signature",
        sa.column("post_id", sa.Integer),
        sa.column("words", sa.ARRAY(sa.Integer)),
    )
    connection = op.get_bind()
    last_post_id = 0
    while True:
        already_copied = (
            sa.select(word_table.c.post_id)
            .where(word_table.c.post_id == signature_table.c.post_id)
            .exists()
        )
        signatures = connection.execute(
            sa.select(signature_table.c.post_id, signature_table.c.words)
            .where(signature_table.c.post_id > last_post_id)
            .where(~already_copied)
            .order_by(signature_table.c.post_id)
            .limit(BATCH_SIZE)
        ).fetchall()
        if not signatures:
            break
        rows = [
            {"post_id": post_id, "position": position, "word": word}
            for post_id, words in signatures
            for position, word in enumerate(words or [])
        ]
        if rows:
            connection.execute(word_table.insert(), rows)
        last_post_id = signatures[-1][0]


def downgrade():
    op.drop_index(
        "ix_post_signature_word_word_position",
        table_name="post_signature_word",
    )
    op.drop_table("post_signature_word")
