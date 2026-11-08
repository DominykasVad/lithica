# 0005: Cards as data, with versions; the original as version 0

- Status: Accepted; amended by [0011](0011-cards-created-from-data.md); its lorebook part changed by [0010](0010-lorebooks-as-their-own-kind.md)
- Date: 2026-11-04

## Context

A card is stored as its uploaded file plus the data read from it. Archiving
images and editing cards change a card's content; the original should not
be lost, and editing needs a card that is data first, file second.

## Decision

- A card is structured data plus related assets (0003). Links in its text
  point to assets.
- The uploaded file is version 0, the "prime" copy, stored untouched.
- Archiving and editing create new versions, stored as full compressed
  JSON (not diffs), with a retention setting (all, or the last N plus the
  original).
- Any version can be viewed and restored; a restore is a new version.
- The original can be deleted, under a privilege, with a warning and a
  typed confirmation. Afterwards there is no byte-for-byte original
  download and no re-extraction from the file; the file's checksum is kept
  for duplicate detection.
- Export builds the card on demand: the original file (while kept), or
  PNG / CHARX / JSON with share links to its assets (0004), or with the
  images embedded.
- Sardonyx gets a card editor, with an image picker that searches the
  booru and inserts an image as Markdown, relating it to the card.

## Consequences

- Existing cards are converted once (reextract).
- Storage grows with versions; the retention setting bounds it.
