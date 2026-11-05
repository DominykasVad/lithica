# 0007: A shared client core; no copies of whole apps

- Status: Accepted
- Date: 2026-11-04

## Context

A second, booru-only client will replace the legacy client. Sardonyx
already holds login, session, search, upload, themes and the
security-sensitive styled-text frame.

## Decision

- `clients/` becomes a pnpm workspace. What more than one client needs
  moves into packages: API client, session, search and completion,
  components and themes, upload, the styled-text frame.
- Sardonyx stays card-focused; the booru client is a separate app on the
  same core.
- A new client starts from a copy of an app shell (routes, pages,
  navigation) only after the core is extracted; never from a copy of a
  whole app, so a security fix is made once.
- The repository stays one; the core, the apps and the API change
  together.

## Consequences

- The extraction comes first and changes nothing visible; Sardonyx's
  unit and browser tests must stay green throughout.
