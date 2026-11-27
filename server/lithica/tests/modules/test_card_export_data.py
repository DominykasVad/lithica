"""Unit tests for pure card export data conversion and lorebook composition."""

import datetime

from lithica.modules.cards import card as card_format
from lithica.modules.cards import export_data
from lithica.tests.modules import cards

CREATED = datetime.datetime(2026, 3, 1, 12, 0, 0)
MODIFIED = datetime.datetime(2026, 3, 2, 15, 30, 0)
CREATED_TS = int(CREATED.replace(tzinfo=datetime.UTC).timestamp())
MODIFIED_TS = int(MODIFIED.replace(tzinfo=datetime.UTC).timestamp())


def test_v1_to_v3_and_v2() -> None:
    v3 = export_data.build_v3(
        card_format.KIND_V1,
        cards.V1_CARD,
        creation_time=CREATED,
        modification_time=MODIFIED,
        books=[],
        assets=[{"type": "icon", "uri": "ccdefault:", "name": "main", "ext": "png"}],
    )
    assert v3["spec"] == "chara_card_v3"
    assert v3["spec_version"] == "3.0"
    data = v3["data"]
    for key, value in cards.V1_CARD.items():
        assert data[key] == value
    assert data["creator_notes"] == ""
    assert data["system_prompt"] == ""
    assert data["post_history_instructions"] == ""
    assert data["alternate_greetings"] == []
    assert data["tags"] == []
    assert data["creator"] == ""
    assert data["character_version"] == ""
    assert data["extensions"] == {}
    assert data["group_only_greetings"] == []
    assert "creator_notes_multilingual" not in data
    assert "character_book" not in data
    assert data["creation_date"] == CREATED_TS
    assert data["modification_date"] == MODIFIED_TS
    assert data["assets"] == [
        {"type": "icon", "uri": "ccdefault:", "name": "main", "ext": "png"}
    ]

    v2 = export_data.to_v2(v3)
    assert v2["spec"] == "chara_card_v2"
    assert v2["spec_version"] == "2.0"
    for key in export_data.V3_ONLY_FIELDS:
        assert key not in v2["data"]
    assert v2["data"]["name"] == cards.V1_CARD["name"]


def test_v2_to_v3_adds_v3_fields_and_preserves_extensions() -> None:
    source = cards.v2_card(extensions={"app": {"url": "https://example.test/a.png"}})
    source["data"].pop("character_book")
    v3 = export_data.build_v3(
        card_format.KIND_V2,
        source,
        creation_time=CREATED,
        modification_time=MODIFIED,
        books=[],
    )
    assert v3["spec"] == "chara_card_v3"
    assert v3["data"]["group_only_greetings"] == []
    assert "creator_notes_multilingual" not in v3["data"]
    assert v3["data"]["assets"] == []
    assert v3["data"]["extensions"] == {"app": {"url": "https://example.test/a.png"}}
    assert v3["data"]["creation_date"] == CREATED_TS
    assert v3["data"]["modification_date"] == MODIFIED_TS


def test_v3_to_v2_drops_all_v3_only_fields() -> None:
    source = cards.v3_card(
        nickname="Keeper",
        creator_notes_multilingual={"en": "hi"},
        source=["https://example.test/card"],
        group_only_greetings=["Group hi"],
        creation_date=1,
        modification_date=2,
    )
    source["data"].pop("character_book")
    v2 = export_data.build_v2(
        card_format.KIND_V3,
        source,
        creation_time=CREATED,
        modification_time=MODIFIED,
        books=[],
    )
    assert v2["spec"] == "chara_card_v2"
    assert v2["spec_version"] == "2.0"
    for key in (
        "assets",
        "nickname",
        "creator_notes_multilingual",
        "source",
        "group_only_greetings",
        "creation_date",
        "modification_date",
    ):
        assert key not in v2["data"]
    assert v2["data"]["name"] == "Ada"
    assert v2["data"]["extensions"] == {"some_app": {"depth": 4}}


def test_single_book_exported_unchanged() -> None:
    book = {
        "name": "The coast",
        "description": "Original description",
        "entries": [{"id": 42, "keys": ["lamp"], "content": "Bright."}],
        "extensions": {"x": 1},
    }
    v3 = export_data.build_v3(
        card_format.KIND_V2,
        cards.v2_card(),
        creation_time=CREATED,
        modification_time=MODIFIED,
        books=[book],
    )
    assert v3["data"]["character_book"] == book
    assert v3["data"]["character_book"] is not book


def test_multiple_books_merged_renumbered_and_annotated() -> None:
    first = {
        "name": "Alpha",
        "description": "First book.",
        "entries": [
            {"id": 10, "keys": ["a"], "content": "One"},
            {"id": 20, "keys": ["b"], "content": "Two"},
        ],
    }
    second = {
        "name": "Beta",
        "description": "Second book.",
        "entries": [{"id": 5, "keys": ["c"], "content": "Three"}],
    }
    merged = export_data.export_book([first, second])
    assert merged is not None
    assert [entry["id"] for entry in merged["entries"]] == [0, 1, 2]
    assert [entry["content"] for entry in merged["entries"]] == ["One", "Two", "Three"]
    assert merged["description"] == (
        "First book.\nMerged from 2 Lithica lorebooks: Alpha, Beta"
    )
    # Source books are not mutated.
    assert first["entries"][0]["id"] == 10
    assert second["entries"][0]["id"] == 5


def test_multiple_books_with_empty_description() -> None:
    first = {"name": "One", "entries": [{"id": 7, "keys": ["k"], "content": "x"}]}
    second = {"name": "Two", "entries": [{"id": 8, "keys": ["m"], "content": "y"}]}
    merged = export_data.export_book([first, second])
    assert merged is not None
    assert merged["description"] == "Merged from 2 Lithica lorebooks: One, Two"


def test_marker_cleanup_replaces_markers_outside_assets() -> None:
    marker = {"embedded": {"type": "image/png", "name": "avatar", "size": 123}}
    source = cards.v3_card(
        avatar=marker,
        creator_notes=marker,
        nested={"keep": "ok", "drop": marker, "items": [marker, "text"]},
        not_a_marker={"embedded": {"other": 1}},
    )
    source["data"].pop("character_book")
    asset_with_marker = {"type": "icon", "uri": marker, "name": "main", "ext": "png"}
    v3 = export_data.build_v3(
        card_format.KIND_V3,
        source,
        creation_time=CREATED,
        modification_time=MODIFIED,
        books=[],
        assets=[asset_with_marker],
    )
    data = v3["data"]
    assert data["avatar"] == ""
    assert data["creator_notes"] == ""
    assert data["nested"] == {"keep": "ok", "drop": "", "items": ["", "text"]}
    assert data["not_a_marker"] == {"embedded": {"other": 1}}
    # Assets are left untouched by marker cleanup (resolved separately).
    assert data["assets"] == [asset_with_marker]
