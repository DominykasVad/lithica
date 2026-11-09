# 0009: Single user, one client with sections

- Status: Accepted; amended by [0012](0012-legacy-client-removed.md)
- Date: 2026-11-06
- Supersedes: [0007](0007-shared-client-core.md)

## Context

0007 planned a shared client core and a second, booru-only client next to
Sardonyx. Planning that client showed how much the two would share: login,
upload, tags, settings, admin, the shell. Lithica is very likely to have a
single user, its owner, so separate apps would buy little and cost a
shared core, a second image, a second CI path and test stack, and awkward
crossings such as the card editor's image picker browsing the booru.

## Decision

- **Design for one user; stay ready for more where it's cheap.** Features
  are built and tested for a single user. Where a feature can be
  multi-user-ready at little extra cost, it is: settings stored per
  account, records keeping who made them, the server still checking
  privileges. Features that only make sense with many users (groups,
  per-user rights, user pages and rank management, social features) are
  not built until there is a real need.
- **One client, Sardonyx, with sections.** A Library section for media
  (picture-first) and a Cards section (what Sardonyx is today), sharing
  login, upload, tags, settings, admin, theme and the shell. Sections can
  have their own layout and density.
- **A section shows when its module and feature switches are on** (0008);
  privileges per rank stay as the server enforces them today. No per-user
  section choices.
- **Library features:** pools, favourites, notes on pictures, and a star
  rating (1–5 per account, stored per account). The engine's up/down
  scores are switched off by default, like comments. Admin screens: site
  settings and switches, tag categories, implications and suggestions.
- **Per-account settings** (per page, theme, Show NSFW) are stored per
  account on the server, with the browser as the fallback when logged out.
- The legacy client is retired once Sardonyx covers what is needed.

## Consequences

- No shared-core extraction and no second app: phase 7 restructures
  Sardonyx into sections instead.
- The second client's planning is obsolete; what it found about shared
  functions applies to the sections.
- Star ratings are a new feature on the server (storage per account and
  post, search and sort by stars); the engine's scores stay in the code,
  switched off.
