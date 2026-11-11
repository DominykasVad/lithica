# Roadmap after v0.3.0

Order of the next phases. Steps 1–4 are phases 6–9 of PLAN.md, which holds
their sub-phases and done-when criteria; the later steps become phases when
they are planned.

Cards as data comes before the sections because the first big import
(1000+ cards from Lumiverse, through the plugin) needs it, and importing
into the current card model would mean converting everything twice.

1. **Phase 6, server foundations** (`v0.4.0`) ([0001](decisions/0001-one-server-assets-with-kinds.md),
   [0002](decisions/0002-kind-is-a-field.md), [0003](decisions/0003-relations-and-listing.md),
   [0004](decisions/0004-private-assets-share-links.md), [0008](decisions/0008-site-settings-and-features.md),
   [0011](decisions/0011-cards-created-from-data.md))
   - Login tokens hashed; app tokens with limited rights, for the plugins.
   - Assets with kinds and typed relations with labels; external IDs.
   - The listed flag.
   - Share links.
   - Site settings API with per-feature switches; comments and scores off by default.
   - Background jobs.
2. **Phase 7, cards as data** (`v0.5.0`) ([0005](decisions/0005-cards-as-data-and-versions.md),
   [0006](decisions/0006-archiving-card-images.md), [0010](decisions/0010-lorebooks-as-their-own-kind.md),
   [0011](decisions/0011-cards-created-from-data.md),
   [0013](decisions/0013-versioned-documents-and-module-tables.md))
   - Card and lorebook data with versions; lorebooks as their own kind,
     linked to cards; existing cards converted.
   - Cards created from data, JSON uploads, duplicates by content; what the
     Lumiverse plugin's import needs.
   - A card's own images as related assets; archiving card images.
   - Export: original, PNG, CHARX, JSON, with books and images embedded or
     linked.
3. **Phase 8, Sardonyx in sections** (`v0.6.0`) ([0009](decisions/0009-single-user-one-client.md))
   - Library (media, picture-first) and Cards sections in one client,
     sharing login, upload, tags, settings and admin.
   - Settings per account (per page, theme, Show NSFW).
   - Site settings page polish (from the 6.6 review): Save sticky at the
     bottom of the view while there are unsaved changes, and a warning
     before leaving with them; no separator under the last row of a card;
     readable labels for choices and restart settings instead of raw
     values, names and JSON ("not set" for an empty value).
4. **Phase 9, card editor in Sardonyx** (`v0.7.0`) ([0005](decisions/0005-cards-as-data-and-versions.md),
   [0010](decisions/0010-lorebooks-as-their-own-kind.md))
   - Making and editing cards and lorebooks, with an image picker that
     searches the library and inserts the image as Markdown.
5. **Sync** (for the SillyTavern and Lumiverse plugins)
   - A change feed since a cursor for cards, lorebooks and their assets,
     deletions included; version checks on every write (in place from
     phase 7).
6. **Library features** ([0008](decisions/0008-site-settings-and-features.md),
   [0009](decisions/0009-single-user-one-client.md))
   - Pools, favourites, star ratings (1–5 per account), notes on pictures,
     each behind its feature switch.
   - Admin screens: tag categories, implications and suggestions.

Alongside, small:
- Dependabot version updates.
- WebKit in CI when Playwright runs it reliably on Linux.
- Review of "the first account to sign up becomes administrator", now that
  `lithica-admin create-user` exists.
- Sardonyx under a sub-path (`BASE_URL`), listed under "Later" in PLAN.md.
