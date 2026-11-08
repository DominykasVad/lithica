# 0011: Cards created from data, with no file

- Status: Accepted
- Date: 2026-11-08
- Amends: [0005](0005-cards-as-data-and-versions.md)

## Context

0005 takes a card's version 0 from its uploaded file and finds duplicates
by the file's checksum. The Lumiverse plugin can't produce a card file:
Lumiverse stores characters as fields, and its extensions can't send
multipart or fetch a CHARX. The first big import (1000+ cards) will come
through that plugin. Requested by the plugins project (R2, R3, R4, R5).

## Decision

- A card can be created through the API from card data (CCv3 JSON) plus
  references to assets uploaded first (avatar, gallery, expressions) and to
  lorebooks (0010). No file is involved.
- Its first data version is version 0. It has no original file: export
  builds every form from data, as after an original is deleted under 0005.
- A source note records where it came from (e.g. "Lumiverse"), shown with
  the card and kept in its versions.
- Duplicates are found by a hash of the card's normalised data (stable
  field order, whitespace kept as is), for cards with and without a file;
  the file checksum stays as a second check for uploaded cards.
- Assets can be uploaded with a JSON body (base64), as a second way into
  the existing temporary upload, for clients that can't send multipart.
- Posts can carry external IDs: (host, the host's ID), several per post,
  searchable and settable through the API, so an import run again updates
  instead of duplicating.

## Consequences

- Phase 9's "creating a card with no uploaded file" moves into phase 7.
- Content-hash duplicates can differ from file duplicates for the same
  card (a file with extra chunks); the content hash decides.
