# Roadmap after v0.3.0

Order of the next phases. The steps are phases 6–9 of PLAN.md, which holds
their sub-phases and done-when criteria. The booru client is planned
separately and joins this list when its plan is written.

1. **Phase 6, server foundations** (`v0.4.0`) ([0001](decisions/0001-one-server-assets-with-kinds.md),
   [0002](decisions/0002-kind-is-a-field.md), [0003](decisions/0003-relations-and-listing.md),
   [0004](decisions/0004-private-assets-share-links.md), [0008](decisions/0008-site-settings-and-features.md))
   - Assets with kinds (media; JSON documents registered by modules) and relations.
   - The listed flag.
   - Share links.
   - Site settings API with per-feature switches; comments off by default.
   - Background jobs (for archiving and later work).
2. **Phase 7, shared client core** (no release) ([0007](decisions/0007-shared-client-core.md))
   - `clients/` as a pnpm workspace; Sardonyx moved onto it with no visible
     change, its unit and browser tests green throughout; CI and the e2e
     stack learn the workspace.
3. **Phase 8, cards as data** (`v0.5.0`) ([0005](decisions/0005-cards-as-data-and-versions.md),
   [0006](decisions/0006-archiving-card-images.md))
   1. Card storage as structured data plus related assets; existing cards
      converted. Versions, with the original as version 0 and the option to
      delete it.
   2. Archiving card images.
   3. CHARX's embedded images as related assets.
   4. Export: original, PNG, CHARX, JSON, with share links or embedded images.
4. **Phase 9, card editor in Sardonyx** (`v0.6.0`) ([0005](decisions/0005-cards-as-data-and-versions.md))
   - Editing card content, with an image picker that searches the booru and
     inserts the image as Markdown, relating the asset to the card.

Alongside, small:
- Dependabot version updates.
- Per-account settings (per page, theme, Show NSFW) once the settings API exists.
- WebKit in CI when Playwright runs it reliably on Linux.
- Review of "the first account to sign up becomes administrator", now that
  `lithica-admin create-user` exists.
- Sardonyx under a sub-path (`BASE_URL`), listed under "Later" in PLAN.md.
