# 0008: Site settings API and feature switches; comments off

- Status: Accepted
- Date: 2026-11-04

## Context

Site settings live only in config.yaml, so no admin screen can change
them. Some features (pools, favourites, scores, notes, comments) are not
wanted on every site.

## Decision

- A settings API lets an administrator read and change site settings;
  which settings can change at runtime and which need a restart is decided
  per setting.
- Optional features get switches. A feature that is off: the server
  refuses its API, GET /info reports it, clients hide it.
- Comments are dropped from the plan. The existing comment API is switched
  off by default; it is deleted in a later cleanup if never needed. An
  external comment system stays possible.

## Consequences

- Admin screens become possible in any client.
- Per-account settings (per page, theme, Show NSFW) can follow on the same
  ground.
