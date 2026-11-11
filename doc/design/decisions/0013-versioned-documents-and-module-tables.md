# 0013: Versioned documents in the engine; tables of modules

- Status: Accepted
- Date: 2026-11-11
- Refines: [0005](0005-cards-as-data-and-versions.md), [0010](0010-lorebooks-as-their-own-kind.md)

## Context

0005 and 0010 make cards and lorebooks data with versions. Where that data
lives decides how later kinds (presets) and sync (roadmap step 5) are built.
Cards also need state of their own (the books a card links, archiving
records) that means nothing to the engine. A lorebook made from a card, and
a card created from data (0011), have no file; until now every post had one.

## Decision

- A post may have no file. Its file fields are empty; whatever needs a file
  refuses or skips such a post.
- The engine stores documents: at most one JSON document per post, of a
  kind a module registers. The engine keeps the current data and every
  version as a full compressed copy, numbered from 0, with a content hash,
  a note, its time and user; it applies the retention setting, refuses
  stale writes, restores a version as a new one, and serves one versions
  API for every kind.
- The module owns the meaning: what valid data is, how it is shown and
  searched, and what follows from a write.
- A module may own tables for state only it understands. Its models live in
  the module; their migrations are normal Alembic migrations in the
  engine's folder and run whether or not the module is on. The engine never
  reads them.

## Consequences

- Every document kind gets versions, retention and the version check
  without code of its own; sync can follow one table.
- Card data stops living in `post_content`, which stays what was read from
  the file.
- Clients must expect posts without file URLs.
