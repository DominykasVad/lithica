"""
A card as a viewer shows it: one shape for every version and both file
formats. The stored payload is the card as its file had it; this is the
reading of it that a client can rely on. Every field is there, of the type
it should be, whatever the card left out or got wrong.
"""

from typing import Any, cast

from lithica.modules.cards import card as card_format


def _flag(value: object) -> bool | None:
    return value if isinstance(value, bool) else None


def _number(value: object) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value


def _extensions(value: object) -> dict[str, Any]:
    return cast(dict[str, Any], value) if isinstance(value, dict) else {}


def _entry(entry: dict[str, Any]) -> dict[str, Any]:
    identifier = entry.get("id")
    return {
        "keys": card_format.as_texts(entry.get("keys")),
        "secondaryKeys": card_format.as_texts(entry.get("secondary_keys")),
        "content": card_format.as_text(entry.get("content")),
        "enabled": _flag(entry.get("enabled")),
        "order": _number(entry.get("insertion_order")),
        "name": card_format.as_text(entry.get("name")),
        "comment": card_format.as_text(entry.get("comment")),
        "constant": _flag(entry.get("constant")),
        "selective": _flag(entry.get("selective")),
        "caseSensitive": _flag(entry.get("case_sensitive")),
        "useRegex": _flag(entry.get("use_regex")),
        "position": card_format.as_text(entry.get("position")) or None,
        "priority": _number(entry.get("priority")),
        # a number in V2, a number or a text in V3
        "id": identifier if isinstance(identifier, str) else _number(identifier),
        "extensions": _extensions(entry.get("extensions")),
    }


def _lorebook(fields: dict[str, Any]) -> dict[str, Any] | None:
    book = fields.get("character_book")
    if not isinstance(book, dict):
        return None
    book = cast(dict[str, Any], book)
    return {
        "name": card_format.as_text(book.get("name")),
        "description": card_format.as_text(book.get("description")),
        "scanDepth": _number(book.get("scan_depth")),
        "tokenBudget": _number(book.get("token_budget")),
        "recursiveScanning": _flag(book.get("recursive_scanning")),
        "extensions": _extensions(book.get("extensions")),
        "entries": [_entry(entry) for entry in card_format.lorebook_entries(fields)],
    }


def normalised(post_id: int, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    """The card of a post, from what is stored for it."""
    card = payload.get("card")
    fields = card_format.fields_of(
        kind, cast(dict[str, Any], card) if isinstance(card, dict) else {}
    )
    return {
        "postId": post_id,
        "spec": card_format.SPEC_NAMES[kind],
        "format": card_format.as_text(payload.get("format")),
        "name": card_format.as_text(fields.get("name")),
        "description": card_format.as_text(fields.get("description")),
        "personality": card_format.as_text(fields.get("personality")),
        "scenario": card_format.as_text(fields.get("scenario")),
        "firstMessage": card_format.as_text(fields.get("first_mes")),
        "alternateGreetings": card_format.as_texts(fields.get("alternate_greetings")),
        "exampleMessages": card_format.as_text(fields.get("mes_example")),
        "creatorNotes": card_format.as_text(fields.get("creator_notes")),
        "systemPrompt": card_format.as_text(fields.get("system_prompt")),
        "postHistoryInstructions": card_format.as_text(
            fields.get("post_history_instructions")
        ),
        "tags": card_format.as_texts(fields.get("tags")),
        "creator": card_format.as_text(fields.get("creator")),
        "characterVersion": card_format.as_text(fields.get("character_version")),
        "lorebook": _lorebook(fields),
    }
