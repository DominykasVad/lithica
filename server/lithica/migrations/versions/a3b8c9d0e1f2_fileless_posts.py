"""Permit posts without a file, with file identity fields null together."""

import sqlalchemy as sa
from alembic import op

revision = "a3b8c9d0e1f2"
down_revision = "f2a7b8c9d0e1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for name in ("type", "mime-type", "checksum"):
        op.alter_column("post", name, nullable=True)
    columns = [sa.column(name) for name in ("type", "mime-type", "checksum")]
    op.create_check_constraint(
        "ck_post_file_fields_together", "post",
        sa.or_(sa.and_(*(c.is_(None) for c in columns)),
               sa.and_(*(c.is_not(None) for c in columns))),
    )


def downgrade() -> None:
    post = sa.table("post", sa.column("type"))
    if op.get_bind().execute(sa.select(post).where(post.c.type.is_(None)).limit(1)).first():
        raise RuntimeError("Cannot downgrade while posts without a file exist.")
    op.drop_constraint("ck_post_file_fields_together", "post", type_="check")
    for name in ("type", "mime-type", "checksum"):
        op.alter_column("post", name, nullable=False)
