# 0012: The legacy client is removed now

- Status: Accepted
- Date: 2026-11-09
- Amends: [0009](0009-single-user-one-client.md) (when the legacy client is retired)

## Context

0009 kept the legacy client until Sardonyx covers what is needed (phase 8).
Nobody uses Lithica until its design is close to final, so the legacy
client protects no one. It still costs: a second image in CI and releases,
its nginx in the file-link tests, a dev stack built around it, frozen-client
rules, and compatibility steps for it in API changes (6.1's token page).

## Decision

- `legacy/client/` is removed, with its compose service and `legacy`
  profile, its place in the dev stack, its image in releases, and its CI
  paths. Images already published (up to v0.3.0) stay on GHCR.
- Until Sardonyx has them (6.6, phase 8), pools, notes, favourites, user
  management, tag categories, implications and suggestions are reached
  through the API only.
- Serving the site under a path (`BASE_URL`) is gone until Sardonyx
  supports it (PLAN.md, "Later").
- The licensing rule stays: nothing from szurubooru's client (upstream, or
  this repository's history) goes into `clients/`, which is MIT.

## Consequences

The API's compatibility is judged by `doc/openapi.json` and Sardonyx's
tests alone. Roadmap step "Retiring the legacy client" is done.
