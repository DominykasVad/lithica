# 0002: The kind is a server field, not a tag

- Status: Accepted
- Date: 2026-11-04

## Context

Each client shows its own view: Sardonyx cards, the booru client media.
Marking assets with a tag was considered; tags are edited freely by
anyone with the tag privilege, so a slip could move an asset out of its
client's view.

## Decision

The kind is a field of the asset, derived from its content by the server.
It changes only through its own API call, under its own privilege. Tags
stay for describing assets.

## Consequences

- Clients select their view by kind, not by tag.
- A mistyped tag edit cannot change which client an asset belongs to.
