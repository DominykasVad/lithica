# 0010: Lorebooks as their own kind

- Status: Accepted
- Date: 2026-11-08

## Context

A card carries its lorebook inside its data. Lumiverse keeps lorebooks
("world books") as separate records, linked to characters many to many,
and allows books that belong to no character. With books inside cards, a
book shared by N characters becomes N copies, a standalone book can't be
imported, an edit to one copy doesn't reach the others, and two-way sync
can't tell a shared book from a card's own. Requested by the plugins
project (R7, 2026-11-08); 0001 had lorebooks as a later kind.

## Decision

- `lorebook` is a kind of its own (0001): a JSON document with its own
  versions, like a card's data (0005), and its own version check on writes.
- Cards link lorebooks, many to many, in order. A lorebook may be linked to
  no card.
- A card's data no longer contains its book: the converted card links the
  book instead. When existing cards are converted, a book embedded in
  several cards with the same content becomes one lorebook linked to all
  of them.
- Export embeds the linked books, so a downloaded PNG or CHARX card is
  complete. The card formats hold one book: with several linked, their
  entries are merged in link order into the exported book, and the export
  says so.
- Clients show a lorebook as its own page (the existing lorebook view),
  reachable from each card that links it.

## Consequences

- Phase 7 (cards as data) converts cards and books together, once.
- Search and sync see lorebooks as assets: they can be found, listed,
  shared and synced on their own.
