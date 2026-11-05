# 0001: One server; every upload is an asset with a kind

- Status: Accepted
- Date: 2026-11-04

## Context

Lithica started as an image booru with a cards module beside it. The plans
reach further: cards as data, lorebooks, presets, a booru client and a card
client using each other's content. A second server for text content was
considered.

## Decision

Lithica stays one server. Every upload is an asset with a kind:

- media: image, video;
- JSON documents: card now; lorebook, preset and others later, each kind
  registered by a module with its own schema.

Text fields inside documents stay as they are (text, Markdown, HTML or a
mix); the clients already show them as Readable, Source and Styled.

## Consequences

- Users, login, privileges, search, the visibility modes and signed links
  stay in one place; clients talk to one API.
- The post model grows into an asset model; existing posts become media
  or card assets.
- A module adds a kind with its schema, validation and search tokens, as
  the cards module does today.
