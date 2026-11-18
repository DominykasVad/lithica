# 0014: Card text keeps its URLs

- Status: Accepted
- Date: 2026-11-18
- Amends: [0006](0006-archiving-card-images.md) and the archiving described
  in [0005](0005-cards-as-data-and-versions.md)

## Context

Decision 0006 called for a new card version pointing to each archived
image. Changing the imported data would also change its duplicate hash
([0011](0011-cards-created-from-data.md)). Every repeated import would
then appear to change the card.

## Decision

- Card text keeps its URLs. Each card maps a URL in its text to the
  archived post or records why archiving failed. Clients and export
  use this map to resolve URLs.
- Card text can also name a post directly as `lithica:post/<id>`. The
  scheme lets Lithica resolve the post without an outside HTTP request.
- An explicit per-card action replaces archived URLs with these references
  in one new document version.
- Automatic archiving applies to cards matching a configured creator or
  tag. With no rules configured, it archives nothing.

## Consequences

- Archiving alone creates no version. Repeated imports and duplicate
  checks are unaffected until the replacement action changes the text.
- Sardonyx, export and the plugins all apply the map and resolve direct
  references.
