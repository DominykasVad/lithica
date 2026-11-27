"""Pure card data conversion, lorebook merging and marker cleanup for export."""

import datetime
from copy import deepcopy
from typing import Any, cast

from lithica.modules.cards import card as card_format
from lithica.modules.cards import reading

V3_ONLY_FIELDS = (
    "assets",
    "nickname",
    "creator_notes_multilingual",
    "source",
    "group_only_greetings",
    "creation_date",
    "modification_date",
)

_V2_TEXT_DEFAULTS = (
    "name",
    "description",
    "personality",
    "scenario",
    "first_mes",
    "mes_example",
    "creator_notes",
    "system_prompt",
    "post_history_instructions",
    "creator",
    "character_version",
)

_EMBEDDED_KEYS = frozenset({"type", "name", "size"})


def _unix_seconds(value: datetime.datetime) -> int:
    return int(value.replace(tzinfo=datetime.UTC).timestamp())


def _is_embedded_marker(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    mapping = cast(dict[object, object], value)
    if len(mapping) != 1 or "embedded" not in mapping:
        return False
    inner = mapping["embedded"]
    return (
        isinstance(inner, dict)
        and frozenset(cast(dict[object, object], inner).keys()) == _EMBEDDED_KEYS
    )


def clean_markers(value: object, *, skip_assets: bool = False) -> object:
    """Replace any remaining `{"embedded": ...}` marker with an empty string."""
    if _is_embedded_marker(value):
        return ""
    if isinstance(value, list):
        return [clean_markers(item) for item in cast(list[object], value)]
    if isinstance(value, dict):
        mapping = cast(dict[str, object], value)
        return {
            key: (item if skip_assets and key == "assets" else clean_markers(item))
            for key, item in mapping.items()
        }
    return value


def export_book(books: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Compose visible lorebooks for export; annotate and renumber when merged."""
    merged = reading.merge_books(books)
    if merged is None or len(books) == 1:
        return deepcopy(merged) if merged is not None else None
    merged = deepcopy(merged)
    entries = merged.get("entries")
    if isinstance(entries, list):
        next_id = 0
        for entry in cast(list[object], entries):
            if isinstance(entry, dict):
                cast(dict[str, Any], entry)["id"] = next_id
                next_id += 1
    names = ", ".join(card_format.as_text(book.get("name")) for book in books)
    note = f"Merged from {len(books)} Lithica lorebooks: {names}"
    description = card_format.as_text(merged.get("description"))
    if description:
        merged["description"] = (
            f"{description}{note}"
            if description.endswith("\n")
            else f"{description}\n{note}"
        )
    else:
        merged["description"] = note
    return merged


def build_v3(
    source_spec: str,
    source_card: dict[str, Any],
    *,
    creation_time: datetime.datetime,
    modification_time: datetime.datetime,
    books: list[dict[str, Any]],
    assets: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a CCv3 card object from a stored V1, V2 or V3 card document."""
    fields = deepcopy(card_format.fields_of(source_spec, source_card))
    fields.pop("character_book", None)
    for key in _V2_TEXT_DEFAULTS:
        fields.setdefault(key, "")
    fields.setdefault("alternate_greetings", [])
    fields.setdefault("tags", [])
    fields.setdefault("extensions", {})
    fields.setdefault("group_only_greetings", [])
    fields["creation_date"] = _unix_seconds(creation_time)
    fields["modification_date"] = _unix_seconds(modification_time)
    if assets is not None:
        fields["assets"] = deepcopy(assets)
    else:
        fields.setdefault("assets", [])
    book = export_book(books)
    if book is not None:
        fields["character_book"] = book
    cleaned = cast(dict[str, Any], clean_markers(fields, skip_assets=True))
    return {
        "spec": "chara_card_v3",
        "spec_version": "3.0",
        "data": cleaned,
    }


def to_v2(v3_card: dict[str, Any]) -> dict[str, Any]:
    """Derive a CCv2 card object from a built CCv3 card by dropping V3-only fields."""
    fields = deepcopy(cast(dict[str, Any], v3_card["data"]))
    for key in V3_ONLY_FIELDS:
        fields.pop(key, None)
    return {
        "spec": "chara_card_v2",
        "spec_version": "2.0",
        "data": fields,
    }


def build_v2(
    source_spec: str,
    source_card: dict[str, Any],
    *,
    creation_time: datetime.datetime,
    modification_time: datetime.datetime,
    books: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build a CCv2 card object from a stored V1, V2 or V3 card document."""
    return to_v2(
        build_v3(
            source_spec,
            source_card,
            creation_time=creation_time,
            modification_time=modification_time,
            books=books,
            assets=[],
        )
    )
