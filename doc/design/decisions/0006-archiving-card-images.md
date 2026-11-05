# 0006: Archiving card images on the server

- Status: Accepted
- Date: 2026-11-04

## Context

Images linked from card greetings and notes disappear as their hosts drop
them. A browser cannot fetch most of them (other sites don't allow it) and
must not (the app never fetches URLs from card data, to keep the viewer's
address from card authors' hosts).

## Decision

- The server fetches card images, through the SSRF-safe downloader, with
  size and type limits.
- Archived images become related, unlisted assets of the card (0003) and
  a new card version points to them (0005).
- An admin setting chooses manual or automatic archiving, with rules
  (automatic only for given creators or tags). A per-card "Archive images"
  button works either way.

## Consequences

- Archiving is never done by a viewer's browser.
- Automatic archiving makes the server contact outside hosts on upload;
  it is off unless the admin turns it on.
