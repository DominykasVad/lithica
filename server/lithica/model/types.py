"""Column types that more than one model, or none of SQLAlchemy's own, covers."""

import sqlalchemy as sa

# The one dialect-specific type in the models (PLAN.md, "Allowed dialect
# exceptions"): on PostgreSQL a JSON column is JSONB, which can be indexed
# and compared; everywhere else it is the database's plain JSON type.
from sqlalchemy.dialects.postgresql import JSONB


def json_type() -> sa.types.TypeEngine[object]:
    """
    The type of a column that holds a JSON document. Python's None is
    stored as SQL NULL, not as the JSON value `null`, so that NOT NULL means
    what it says.
    """
    return sa.JSON(none_as_null=True).with_variant(
        JSONB(none_as_null=True), "postgresql"
    )
