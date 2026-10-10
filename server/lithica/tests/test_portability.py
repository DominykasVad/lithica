"""
Gate for the database rules in AGENTS.md: the engine talks to the database
through SQLAlchemy expressions only, so that it does not depend on one
database. This fails when a construct that only PostgreSQL has, or raw SQL,
comes back.
"""

import re
from pathlib import Path

import pytest

PACKAGE_DIR = Path(__file__).resolve().parent.parent

FORBIDDEN = {
    "raw SQL (sa.text)": re.compile(r"\bsa\.text\b"),
    "raw SQL (text())": re.compile(r"\btext\("),
    "raw SQL (import of text)": re.compile(
        r"from sqlalchemy(\.sql)? import [^\n]*\btext\b"
    ),
    "dialect-specific type or function (sa.dialects)": re.compile(
        r"\b(sa|sqlalchemy)\.dialects\b"
    ),
    "ILIKE (use func.lower(col).like(...))": re.compile(r"\bilike\b"),
}

# Migrations from before the fork are history and are never edited.
HISTORICAL_MIGRATIONS = {
    "52d6ea6584b8_generate_post_signature_table.py",
}


def _checked_files() -> list[Path]:
    files = []
    for path in sorted(PACKAGE_DIR.rglob("*.py")):
        if path == Path(__file__).resolve():
            continue
        if path.parent.name == "versions" and path.name in HISTORICAL_MIGRATIONS:
            continue
        files.append(path)
    files.append(PACKAGE_DIR.parent / "lithica-admin")
    return files


def _find_violations(source: str) -> list[tuple[int, str]]:
    violations = []
    for line_number, line in enumerate(source.splitlines(), start=1):
        for description, pattern in FORBIDDEN.items():
            if pattern.search(line):
                violations.append((line_number, description))
    return violations


def test_no_database_specific_code():
    files = _checked_files()
    assert len(files) > 100
    violations = [
        "%s:%d: %s" % (path.relative_to(PACKAGE_DIR.parent), line_number, what)
        for path in files
        for line_number, what in _find_violations(path.read_text(encoding="utf8"))
    ]
    assert not violations, "\n".join(violations)


@pytest.mark.parametrize(
    "line",
    [
        'db.session.execute(sa.text("SELECT 1"))',
        'session.execute(text("SELECT 1"))',
        "from sqlalchemy import text",
        "from sqlalchemy import select, text",
        "from sqlalchemy.sql import text",
        "words = sa.Column(sa.dialects.postgresql.ARRAY(sa.Integer))",
        "from sqlalchemy.dialects.postgresql import JSONB",
        "import sqlalchemy.dialects.postgresql",
        "expr = column.ilike(value)",
    ],
)
def test_gate_catches(line):
    assert _find_violations(line)


@pytest.mark.parametrize(
    "line",
    [
        "comments.update_comment_text(comment, text)",
        "ctx = _create_context(env)",
        "def serialize_text(self) -> Any:",
        "path.read_text()",
        "sa.func.lower(column).like(sa.func.lower(pattern))",
        "sa.Column(sa.UnicodeText, nullable=False)",
        "query.filter(model.Comment.text == text)",
        "likes = 1",
    ],
)
def test_gate_allows(line):
    assert not _find_violations(line)
