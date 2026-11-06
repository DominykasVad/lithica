# Roadmap after v0.3.0

Order of the next phases. Steps 1–4 are phases 6–9 of PLAN.md, which holds
their sub-phases and done-when criteria; the later steps become phases when
they are planned.

1. **Phase 6, server foundations** (`v0.4.0`) ([0001](decisions/0001-one-server-assets-with-kinds.md),
   [0002](decisions/0002-kind-is-a-field.md), [0003](decisions/0003-relations-and-listing.md),
   [0004](decisions/0004-private-assets-share-links.md), [0008](decisions/0008-site-settings-and-features.md))
   - Assets with kinds (media; JSON documents registered by modules) and relations.
   - The listed flag.
   - Share links.
   - Site settings API with per-feature switches; comments and scores off by default.
   - Background jobs (for archiving and later work).
2. **Phase 7, Sardonyx in sections** (`v0.5.0`) ([0009](decisions/0009-single-user-one-client.md))
   - Library (media, picture-first) and Cards sections in one client,
     sharing login, upload, tags, settings and admin.
   - Settings per account (per page, theme, Show NSFW).
3. **Phase 8, cards as data** (`v0.6.0`) ([0005](decisions/0005-cards-as-data-and-versions.md),
   [0006](decisions/0006-archiving-card-images.md))
   1. Card storage as structured data plus related assets; existing cards
      converted. Versions, with the original as version 0 and the option to
      delete it.
   2. Archiving card images.
   3. CHARX's embedded images as related assets.
   4. Export: original, PNG, CHARX, JSON, with share links or embedded images.
4. **Phase 9, card editor in Sardonyx** (`v0.7.0`) ([0005](decisions/0005-cards-as-data-and-versions.md))
   - Editing card content, with an image picker that searches the booru and
     inserts the image as Markdown, relating the asset to the card.
5. **Library features** ([0008](decisions/0008-site-settings-and-features.md),
   [0009](decisions/0009-single-user-one-client.md))
   - Pools, favourites, star ratings (1–5 per account), notes on pictures,
     each behind its feature switch.
   - Admin screens: tag categories, implications and suggestions.
6. **Retiring the legacy client** ([0009](decisions/0009-single-user-one-client.md))
   - Once Sardonyx covers what's needed: the `legacy` compose profile and
     the `lithica-client-legacy` image go; sites under a path (`BASE_URL`)
     need base-path support in Sardonyx first.

Alongside, small:
- Dependabot version updates.
- WebKit in CI when Playwright runs it reliably on Linux.
- Review of "the first account to sign up becomes administrator", now that
  `lithica-admin create-user` exists.
- Sardonyx under a sub-path (`BASE_URL`), listed under "Later" in PLAN.md.
