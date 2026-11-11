# Design

Design decisions and the roadmap of Lithica, kept with the code so that
people and the coding agent work from the same text.

- [roadmap.md](roadmap.md): what comes next, in order. Changes freely;
  points to the decisions below.
- [decisions/](decisions/): one file per decision, numbered. A decision is
  never rewritten once accepted: a later one supersedes it, and both say
  so.

PLAN.md stays the plan of the current phase and its decision log (small,
implementation-level decisions). These records hold the larger ones that
shape several phases.

## Writing a decision

Copy the shape of an existing one: `NNNN-short-name.md` with Status
(Proposed, Accepted, Superseded by NNNN), Date, Context, Decision,
Consequences. Keep it short; link instead of repeating.

## Decisions

| # | Decision | Status |
|---|---|---|
| [0001](decisions/0001-one-server-assets-with-kinds.md) | One server; every upload is an asset with a kind | Accepted |
| [0002](decisions/0002-kind-is-a-field.md) | The kind is a server field, not a tag | Accepted |
| [0003](decisions/0003-relations-and-listing.md) | Relations between assets; the listed flag | Accepted |
| [0004](decisions/0004-private-assets-share-links.md) | Assets stay private; share links | Accepted |
| [0005](decisions/0005-cards-as-data-and-versions.md) | Cards as data, with versions; the original as version 0 | Accepted; amended by 0010, 0011 |
| [0006](decisions/0006-archiving-card-images.md) | Archiving card images on the server | Accepted |
| [0007](decisions/0007-shared-client-core.md) | A shared client core; no copies of whole apps | Superseded by 0009 |
| [0008](decisions/0008-site-settings-and-features.md) | Site settings API and feature switches; comments off | Accepted |
| [0009](decisions/0009-single-user-one-client.md) | Single user, one client with sections | Accepted |
| [0010](decisions/0010-lorebooks-as-their-own-kind.md) | Lorebooks as their own kind | Accepted |
| [0011](decisions/0011-cards-created-from-data.md) | Cards created from data, with no file | Accepted |
| [0013](decisions/0013-versioned-documents-and-module-tables.md) | Versioned documents in the engine; tables of modules | Accepted |
