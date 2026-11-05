# 0004: Assets stay private; share links

- Status: Accepted
- Date: 2026-11-04

## Context

A card exported to SillyTavern or Lumiverse fetches its images from the
links in it. Lithica's own file links are signed and expire in 24–48 hours,
and on a login or nsfw-login site an outside app is not logged in.

## Decision

Assets stay private, as the visibility modes and signed links make them.
A separate share link makes one asset reachable by anyone who has it:

- creating one needs a privilege;
- it can be revoked, and can have an expiry;
- the server checks it and nginx delivers the file, so revoking takes
  effect at once.

## Consequences

- Exported cards can link to their assets' share links.
- Share links need their own storage, API and an nginx route, and their
  own tests that a revoked or expired link gets nothing.
