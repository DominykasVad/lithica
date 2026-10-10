"""
Drop post signature words array

Revision ID: b7d2e9a4c1f3
Created at: 2026-10-10 23:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "b7d2e9a4c1f3"
down_revision = "8f3a1c2d4e5b"
branch_labels = None
depends_on = None

BATCH_SIZE = 1000


def upgrade():
    op.drop_column("post_signature", "words")


def downgrade():
    # sa.ARRAY is the one type here that only some databases have; it is what
    # the column was before, so restoring it needs a database that has it.
    op.add_column(
        "post_signature",
        sa.Column("words", sa.ARRAY(sa.Integer), nullable=True),
    )

    signature_table = sa.table(
        "post_signature",
        sa.column("post_id", sa.Integer),
        sa.column("words", sa.ARRAY(sa.Integer)),
    )
    word_table = sa.table(
        "post_signature_word",
        sa.column("post_id", sa.Integer),
        sa.column("position", sa.Integer),
        sa.column("word", sa.Integer),
    )
    connection = op.get_bind()
    last_post_id = 0
    while True:
        post_ids = [
            row[0]
            for row in connection.execute(
                sa.select(signature_table.c.post_id)
                .where(signature_table.c.post_id > last_post_id)
                .where(signature_table.c.words.is_(None))
                .order_by(signature_table.c.post_id)
                .limit(BATCH_SIZE)
            )
        ]
        if not post_ids:
            break
        words = {post_id: [] for post_id in post_ids}
        for post_id, word in connection.execute(
            sa.select(word_table.c.post_id, word_table.c.word)
            .where(word_table.c.post_id.in_(post_ids))
            .order_by(word_table.c.post_id, word_table.c.position)
        ):
            words[post_id].append(word)
        connection.execute(
            signature_table.update()
            .where(signature_table.c.post_id == sa.bindparam("target_post_id"))
            .values(words=sa.bindparam("target_words")),
            [
                {"target_post_id": post_id, "target_words": post_words}
                for post_id, post_words in words.items()
            ],
        )
        last_post_id = post_ids[-1]

    op.alter_column(
        "post_signature",
        "words",
        existing_type=sa.ARRAY(sa.Integer),
        nullable=False,
    )
