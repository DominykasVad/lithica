"""
Reconcile the schema with the models

The migrations and the models had drifted apart: the tests build their tables
from the models, a real database is built by the migrations, and the two were
not the same schema. After this revision autogenerate finds no difference.

Revision ID: d1a7c3e5f9b2
Created at: 2026-10-11 10:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "d1a7c3e5f9b2"
down_revision = "c4e8f1a2b3d5"
branch_labels = None
depends_on = None

# indexes the models declare with index=True that no migration created
MISSING_INDEXES = [
    ("ix_pool_category_id", "pool", "category_id"),
    ("ix_pool_name_pool_id", "pool_name", "pool_id"),
    ("ix_pool_post_pool_id", "pool_post", "pool_id"),
    ("ix_post_signature_post_id", "post_signature", "post_id"),
]

# (table, column, referred table, ON DELETE before, ON DELETE in the models)
FOREIGN_KEYS = [
    ("comment", "user_id", "user", None, "SET NULL"),
    ("post_feature", "user_id", "user", None, "SET NULL"),
    ("pool_post", "pool_id", "pool", "CASCADE", None),
    ("pool_post", "post_id", "post", "CASCADE", None),
]

POOL_NAME_LENGTH_BEFORE = 256
POOL_NAME_LENGTH = 128


def _replace_foreign_key(table, column, referred_table, ondelete):
    name = "%s_%s_fkey" % (table, column)
    op.drop_constraint(name, table, type_="foreignkey")
    op.create_foreign_key(
        name, table, referred_table, [column], ["id"], ondelete=ondelete
    )


def _refuse_too_long_pool_names():
    # the API never accepted more than the models' 128 characters, so this
    # only fires on rows written past it
    name = sa.column("name")
    too_long = (
        op.get_bind()
        .execute(
            sa.select(sa.func.count())
            .select_from(sa.table("pool_name", name))
            .where(sa.func.length(name) > POOL_NAME_LENGTH)
        )
        .scalar()
    )
    if too_long:
        raise RuntimeError(
            "%d pool name(s) are longer than %d characters. Shorten them and "
            "run the upgrade again." % (too_long, POOL_NAME_LENGTH)
        )


def upgrade():
    for table, column, referred_table, _before, after in FOREIGN_KEYS:
        _replace_foreign_key(table, column, referred_table, after)

    for index_name, table, column in MISSING_INDEXES:
        op.create_index(index_name, table, [column], unique=False)

    _refuse_too_long_pool_names()
    op.alter_column(
        "pool_name",
        "name",
        existing_type=sa.Unicode(POOL_NAME_LENGTH_BEFORE),
        type_=sa.Unicode(POOL_NAME_LENGTH),
        existing_nullable=False,
    )


def downgrade():
    op.alter_column(
        "pool_name",
        "name",
        existing_type=sa.Unicode(POOL_NAME_LENGTH),
        type_=sa.Unicode(POOL_NAME_LENGTH_BEFORE),
        existing_nullable=False,
    )

    for index_name, table, _column in reversed(MISSING_INDEXES):
        op.drop_index(index_name, table_name=table)

    for table, column, referred_table, before, _after in reversed(FOREIGN_KEYS):
        _replace_foreign_key(table, column, referred_table, before)
