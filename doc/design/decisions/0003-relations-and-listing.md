# 0003: Relations between assets; the listed flag

- Status: Accepted
- Date: 2026-11-04

## Context

Cards bring images with them: their avatar, images archived from their
greetings and notes, the images inside a CHARX file. A card with 30
greeting images would flood a library that shows every image.

## Decision

- Assets can be related, with a type of relation (e.g. avatar of,
  archived from, embedded in).
- Each asset has a "listed" flag: whether it shows in the general library.
- A card's related images default to unlisted; any of them can be listed
  one by one.
- Related images inherit the card's safety rating and NSFW status.

## Consequences

- Searches leave unlisted assets out unless asked for.
- The NSFW visibility rules (nsfw-login) also hold for a card's images.
