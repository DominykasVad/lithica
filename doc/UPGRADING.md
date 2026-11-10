# Upgrading

- [From 0.3.0 to 0.4.0](#from-030-to-040)
- [From 0.2.0 to 0.3.0](#from-020-to-030)
- [From 0.1.0 to 0.2.0](#from-010-to-020)
- [From szurubooru to Lithica 0.1.0](#from-szurubooru-to-lithica-010)

## From 0.3.0 to 0.4.0

0.4.0 adds app tokens, post metadata, share links, database-backed site
settings and background jobs. Sardonyx is now the only shipped web client.

### Steps

1. **Back up** uploads (`MOUNT_DATA`), the database, `server/config.yaml`
   and `.env` before changing anything.
2. **Remove the legacy client setup.** The `client-legacy` service, `legacy`
   profile, release image for new versions and `LEGACY_PORT` are gone
   ([decision 0012](design/decisions/0012-legacy-client-removed.md)). Remove
   `COMPOSE_PROFILES=legacy`, `LEGACY_PORT` and `BASE_URL` from `.env`.
   Published v0.3.0 images stay on GHCR for sites staying on that version.
   While still using the 0.3.0 compose file, stop and remove its container
   if you ran it: `docker compose --profile legacy rm -sf client-legacy`.
   **A site under a path must move to its own host or subdomain first:**
   for example, move `https://example.com/lithica/` to
   `https://booru.example.com/`. Point that host's reverse proxy at
   Sardonyx's `PORT`, forwarding the whole root `/` (including `/api/`,
   `/data/` and `/share/`), rather than stripping a `/lithica/` prefix.
   Set `domain` in `config.yaml` to the new public address and update any
   external links. See [Deployment notes](INSTALL.md#deployment-notes).
3. **Get the release:**

    ```console
    user@host:lithica$ git fetch --tags && git checkout v0.4.0
    ```

    Reapply local compose customisations to the new `docker-compose.yml`:
    it has only `server`, `client` (Sardonyx) and `sql`; the legacy service
    and profile have been removed. Compare `.env` with `doc/example.env`.
4. **Build or pull, and start:**

    ```console
    user@host:lithica$ docker compose build     # or: docker compose pull
    user@host:lithica$ docker compose up -d
    ```

    For published images, replace the `build` sections with `image` lines
    tagged `v0.4.0` for both server and client first
    ([instructions](INSTALL.md#using-published-images)). Server startup runs
    `alembic upgrade head` before serving. Existing login tokens are hashed
    in place and keep working, including Sardonyx sessions from 0.3.0:
    **nobody has to log in again because of the upgrade.**

    Logging out of such an old session in Sardonyx forgets it in the browser
    but cannot revoke its token on the site, because the session has no token
    ID. That token stays valid until its expiry unless revoked separately.
    Sardonyx sessions always have an expiry: 24 hours for a normal session
    or 90 days with "remember me". Tokens made by the legacy client or
    scripts may have no expiry. In v0.3.0, the legacy client's normal
    login token had no expiry; "remember me" set a 365-day expiry. Its
    token-management page also allowed tokens without an expiry.

    Sardonyx does not list login tokens. List them with
    `GET /user-tokens/{name}` and revoke unneeded ones with
    `DELETE /user-token/{name}/{id}` (through the client image, prefix these
    paths with `/api`). See [Token authentication](API.md#user-token-authentication)
    and the [user token fields](API.md#user-token).

    **To go back to 0.3.0, restore the backup from step 1 (database and
    configuration).** The 0.3.0 server does not run on the 0.4.0 schema.
5. **With `cards` enabled, derive existing post kinds once, immediately
   after upgrading:**

    ```console
    user@host:lithica$ docker compose run --rm server ./lithica-admin backfill kinds
    ```

    The migration initially makes every existing post `media`. This command
    derives `card` from stored extracted card rows, in batches without reading
    files. It resets kinds set by hand, so run it before curating kinds.
    **No `reextract` is needed for this upgrade from 0.3.0:** the cards payload
    schema is unchanged. If you are enabling cards for the first time or
    skipped an earlier extraction, follow [The cards module](INSTALL.md#the-cards-module)
    to extract those files first; the kinds backfill cannot discover missing
    card rows.

### What is new

- **App tokens** with `read`, `write` and `upload` rights limited by the
  owner's privileges; login and app token values are stored hashed, shown
  only on creation, and addressed by ID. See [App tokens](INSTALL.md#app-tokens).
- **Post kinds** (`media`, and `card` with cards enabled), with kind search
  and a privileged kind endpoint. See [Post kinds](API.md#post-kinds-and-content-kinds).
- **Typed, directed relations** with labels and file URLs, and **external
  IDs** with exact lookup. See [Relations and IDs](API.md#typed-relations-and-external-ids).
- **Listed posts**: unlisted posts stay out of default searches, but remain
  accessible by URL, pool and relation. See [Listed posts](API.md#listed-posts).
- **Share links**: create and revoke file links on the post or account page.
  Delivery needs the client image's nginx at `/share/`; the server alone
  delivers no file, and `/api/share/` returns 404. See [Share links](INSTALL.md#share-links).
- **Site settings in the database**, an administrator settings page and
  **feature switches**. See [Site settings](INSTALL.md#site-settings).
- **Background jobs**, with a database queue and one worker thread per server
  process when enabled. Keep `WORKERS=1`: several server processes have not
  been verified as a whole; the job queue has been verified to claim each
  job once across processes. See [Background jobs](INSTALL.md#background-jobs).

### New and changed settings

**Comments and scores are off after the upgrade** unless explicitly enabled.
Their data is kept. Turn them back on in Sardonyx's administrator settings
page (`/admin/settings`), or in `server/config.yaml`:

```yaml
features:
    comments: true
    scores: true
```

**A value saved through the settings page wins over `config.yaml`**, even
after a restart. Inspect overrides with `lithica-admin settings list`; remove
one with `lithica-admin settings reset <name>`, or all with
`lithica-admin settings reset --all`, to use the file's values again.
Run these commands in a server container as described in
[Administration](INSTALL.md#administration-from-the-command-line).

Defaults below apply when not overridden in your file or database.
Privileges are minimum ranks, set under `privileges:` in `config.yaml`.

| Setting | Default | Effect after upgrading |
|---|---|---|
| `features.pools`, `features.favorites`, `features.notes` | `true` | Keep existing features available. |
| `features.comments`, `features.scores` | `false` | Disable comments and up/down votes, retaining data. These are not star ratings. |
| `share_links_nsfw` | `false` | Refuse creation and delivery of NSFW shares; enabling permits anonymous access even on a `nsfw-login` site. |
| `jobs.worker` | `true` | Start one job worker thread per server process. |
| `jobs.poll_interval` | `5` | Seconds between worker polls. |
| `jobs.keep_done_days` | `7` | Retain completed jobs this many days; failed jobs remain. |
| `app_tokens:list:self`, `app_tokens:create:self`, `app_tokens:edit:self`, `app_tokens:delete:self` | `regular` | Let users manage their own app tokens. |
| `app_tokens:list:any`, `app_tokens:create:any`, `app_tokens:edit:any`, `app_tokens:delete:any` | `administrator` | Manage other users' app tokens. |
| `share_links:create`, `share_links:list:self`, `share_links:delete:self` | `regular` | Create and manage own share links. |
| `share_links:list:any`, `share_links:delete:any` | `administrator` | List and revoke others' links. |
| `posts:edit:typed_relations`, `posts:edit:external_ids`, `posts:edit:listed` | `regular` | Edit new post metadata; included in app-token `write`. Existing posts start listed. |
| `posts:edit:kind` | `power` | Change to a kind supported by the content; unavailable to app tokens. |
| `site_settings:view`, `site_settings:edit` | `administrator` | Read and edit site settings; unavailable to app tokens. |
| `jobs:list`, `jobs:view` | `administrator` | Inspect jobs; unavailable to app tokens. |

Runtime changes: `visibility`, `nsfw_tag`, `nsfw_hide_names`,
`share_links_nsfw`, `password_reset_mail_interval`, `name`, `contact_email`,
`default_rank`, and all five `features.*` switches. File values keep their
previous defaults for the existing settings. The settings page applies
changes without a restart across server processes.

Restart required: `jobs.*`, `modules`, `max_upload_size`, `api_docs`,
`domain`, `cors_origins`, `allow_private_downloads`, privileges and other
file-only configuration. Restart-only settings exposed on the settings page
are read-only; `jobs.keep_done_days` is file-only. After editing config.yaml,
restart the server (`docker compose restart server`); after editing `.env`,
recreate affected containers (`docker compose up -d`).

### API changes for scripts and other clients

Paths below are server paths; through the client image prefix API routes
with `/api`, except share delivery. See the generated [contract](openapi.json).

1. Login and app token `token` values are returned only by creation; lists,
   updates and `fields` selections return null. See [Token authentication](API.md#user-token-authentication).
2. Update and delete token routes use numeric `id`: `PUT`/`DELETE
   /user-token/{name}/{id}` and `/app-token/{name}/{id}`. A token value in
   place of the ID gives 404 on PUT; DELETE of an unknown token still gives
   `{}`. Log out by ID. See [User token](API.md#user-token).
3. New login token values are 43 URL-safe base64 characters rather than
   UUIDs; existing UUID values still authenticate. See [Token authentication](API.md#user-token-authentication).
4. User tokens gain `id`; app tokens add `GET /app-tokens/{name}`, `POST
   /app-token/{name}` and PUT/DELETE by ID, with `app_tokens:*` privileges.
   `/info` adds `appTokenRights`. See [App tokens](API.md#app-tokens).
5. Authenticated API routes never redirect. See [No redirects](API.md#no-redirects).
6. `GET`/`PUT /site-settings` expose administrator settings; `/info` reports
   effective values and `features`. See [Site settings](API.md#site-settings).
7. Disabled pools, favorites, scores, notes and comments give 404
   `FeatureDisabledError`; related fields are omitted even when requested,
   and their search tokens give `SearchError`. Comments and scores default
   off. See [Feature switches](API.md#feature-switches).
8. `GET /jobs` and `GET /job/{id}` expose jobs to administrators.
   See [Jobs](API.md#jobs).

Other additions: posts gain `kind`, `listed` and `externalIds`; kind editing,
typed-relation CRUD, external-ID replacement/lookup and share-link
creation/listing/revocation routes are new. `/info` adds `postKinds`,
`typedRelationTypes`, and `shareLinksNsfw`. See [Kinds](API.md#post-kinds-and-content-kinds),
[Relations and IDs](API.md#typed-relations-and-external-ids),
[Listed posts](API.md#listed-posts) and [Share links](API.md#share-links).

## From 0.2.0 to 0.3.0

0.3.0 brings a new web client, **Sardonyx**, and makes it the site's client
in `docker-compose.yml`. The legacy client is still there, as an optional
service. The database has no change to make.

Coming from szurubooru? Do the [upgrade to 0.1.0](#from-szurubooru-to-lithica-010)
below with `v0.3.0` in the place of `v0.1.0`, then read this section for what
your client and `.env` need.

> **Is your site served under a path (`BASE_URL` set, e.g.
> `https://example.com/lithica/`)?** Sardonyx cannot do that: it is served
> at the root of its host. Choose one before you upgrade:
>
> - **Keep the legacy client as the site's client.** In `.env`, add
>   `COMPOSE_PROFILES=legacy` and `LEGACY_PORT=` with the value your `PORT`
>   has now, and give `PORT` another free port, e.g. `127.0.0.1:8082`.
>   Keep `BASE_URL`. `docker compose up -d` then starts the `client-legacy`
>   service where your client was, and your reverse proxy needs no change;
>   Sardonyx runs beside it on the new `PORT`, which nothing points at.
> - **Move the site to a host or subdomain of its own**
>   (`https://booru.example.com/`) to use Sardonyx, and drop the path from
>   your reverse proxy and `BASE_URL`.
>
> Sardonyx's image says in its log at start when it is given a `BASE_URL`
> with a path, which it ignores.

### Steps

1. **Back up** the uploads directory, the database and `server/config.yaml`.

2. **Get the release.** `docker-compose.yml` has changed: if you edited
   yours, put your changes into the new one (the `client` service is
   Sardonyx now; the legacy client is `client-legacy`).

    ```console
    user@host:lithica$ git fetch --tags && git checkout v0.3.0
    ```

3. **Look at `.env`** (compare with `doc/example.env`): `PORT` is where
   Sardonyx listens now. Add `FILE_LINK_SECRET` if you want signed file
   links, and the legacy client's lines if you run it (see the note above
   and [The web clients](INSTALL.md#the-web-client)).

4. **Build or pull, and start:**

    ```console
    user@host:lithica$ docker compose build     # or: docker compose pull
    user@host:lithica$ docker compose up -d
    ```

    If you run the published images, set the tag to `v0.3.0` in
    `docker-compose.yml` for the server and the client, and for
    `client-legacy` if you run it. The client's image is new:
    `ghcr.io/dominykasvad/lithica-client` is Sardonyx;
    `lithica-client-legacy` is the legacy client, as before.

5. **With the `cards` module on**, have it read the cards again, once (see
   [below](#the-cards-module-stores-more-about-a-picture)):

    ```console
    user@host:lithica$ docker compose run --rm server ./lithica-admin reextract
    ```

Accounts, posts and settings carry over: users log in to Sardonyx with the
name and password they had.

### What is new

- **Sardonyx**, the web client, on `PORT`: browsing, search with card
  filters, the card viewer with greetings and large lorebooks, upload,
  editing of tags, safety and source, deleting, password reset by mail and
  changing one's password. It has no sign-up page and no pages for pools,
  comments, users or administration: use the legacy client for those. See
  [The web clients](INSTALL.md#the-web-client).
- **The legacy client** is the `client-legacy` service, started only with
  the `legacy` profile, on `LEGACY_PORT` (8081 by default).
- **`lithica-admin create-user`** makes an account from the command line,
  whatever the site allows: the way to make an account on a site without
  sign-up. See [Administration from the command
  line](INSTALL.md#administration-from-the-command-line).
- **`lithica-admin import <folder>`** makes a post of every file in a
  folder, as an upload would. See [Importing a
  folder](INSTALL.md#importing-a-folder).

### New settings

Each one leaves the site as it was until you set it, but the last.

| Setting | Default | What it does |
|---|---|---|
| `visibility` | `open` | What visitors who are not logged in see: `open`, `nsfw-login` (NSFW posts need a login) or `login` (everything needs a login; sign-up is closed). See [Who sees what](INSTALL.md#who-sees-what). |
| `nsfw_tag` | `nsfw` | The tag that marks a post as NSFW, for `nsfw-login` and for clients that blur NSFW posts. |
| `nsfw_hide_names` | `false` | Asks clients to hide a NSFW card's name and creator as well as its picture. |
| `file_link_secret`, or `FILE_LINK_SECRET` in `.env` | empty | Signed file links: the files of posts are served only to addresses the server signed. |
| `password_reset_mail_interval` | `300` | At most one password reset mail per account in this many seconds. The one that acts by default: a request within the window is answered as any other and sends nothing. `0` turns it off. |

**`FILE_LINK_SECRET` goes to the server and to both client images**, the
same value: the server signs the addresses, the client's nginx checks them.
`docker-compose.yml` gives it to all three from `.env`. If you run the
images some other way, give it to each, to the legacy client as well when
you run it: a client image without the secret serves files without
checking, and one with a different secret refuses every file. The
[README](../README.md#signed-file-links) says what signed links protect and
what not.

### API changes

For clients of the API other than the two web clients:

- A login token that does not work (unknown, disabled, expired, or of a
  user who does not exist) is refused with the error name
  `InvalidTokenError`, a kind of `AuthError` (was `AuthError`), and the
  token of a user who does not exist is 403 like any other (was 404
  `UserNotFoundError`). Basic authentication is unchanged.
- Password reset tells no account from another. `GET /password-reset/{name}`
  answers 200 `{}` for an unknown account and one without an email (was
  404 and 400), and for an account mailed within
  `password_reset_mail_interval`, which is sent nothing; the mail is sent
  after the answer. `POST /password-reset/{name}` refuses an unknown
  account with 400 `InvalidPasswordResetTokenError` (was 404), the error of
  a wrong, used or expired token. See [Password
  reset](API.md#password-reset).
- Added, nothing removed: `GET /info` has `visibility`, `nsfwTag`,
  `nsfwHidesNames`, `maxUploadSize` and `acceptedTypes`; posts have the
  field `nsfw`, and with `cards` the card summary `card` (by `fields`).
  With `file_link_secret` set, `contentUrl` and `thumbnailUrl` end with
  `?e=…&s=…`. In `nsfw-login` and `login`, what a visitor may not see
  answers as [API.md](API.md#visibility) says.

### For development

The development stack (`docker-compose.dev.yml`) reloads the server on file
events, watching only the `lithica` package: it no longer polls every file
under `server/`, virtual environment included, which kept the idle server at
about half a CPU core on Docker Desktop. It needs the dev dependencies
(`watchfiles`), which the development image installs; rebuild it once
(`docker compose -f docker-compose.dev.yml build server`). The stack also
runs Sardonyx's image on port 8082 (`SARDONYX_PORT`) beside the legacy
client.

### The cards module stores more about a picture

A card picture often carries more than one card chunk; sites that host
cards leave the chunk of the uploaded picture behind their own. The module
now lists the chunks it did not use with each card (`ignoredChunks`), and
where the first chunk of a kind cannot be read it tries the next one.

Cards stored by 0.2.0 do not have the list, and a picture whose first chunk
was unreadable was stored without a card. Nothing else about them changes:
they are shown, found and downloaded as before. To bring them up to date,
have the module read the files again, once:

```console
user@host:lithica$ docker compose run --rm server ./lithica-admin reextract
```

## From 0.1.0 to 0.2.0

0.2.0 adds the first module, `cards`, for character cards: see
[The cards module](INSTALL.md#the-cards-module). The engine without modules
behaves as in 0.1.0. Nothing needs your hands unless you switch the module
on.

Coming from szurubooru? Do the [upgrade to 0.1.0](#from-szurubooru-to-lithica-010)
below with `v0.2.0` in the place of `v0.1.0`; it is the same procedure.

### Steps

1. **Back up** the uploads directory, the database and `server/config.yaml`.

2. **Get the release:**

    ```console
    user@host:lithica$ git fetch --tags && git checkout v0.2.0
    user@host:lithica$ docker compose build     # or: docker compose pull
    user@host:lithica$ docker compose up -d
    ```

    If you run the published images, set the tag in `docker-compose.yml` to
    `v0.2.0` for both the server and the client first.

That is all for a site without modules. The database has no change to make:
its tables are those of 0.1.0.

### What is new

- **`MODULES`**: an environment variable of the server that names the
  modules to switch on, comma-separated. When set, it replaces `modules` of
  `config.yaml`. See [Modules](INSTALL.md#modules).
- **The `cards` module**, off by default.
- **The API** gained, and lost nothing: `GET /info` lists the enabled
  modules (`modules`); a module may add kinds of files, whose posts have a
  `type` of their own; the routes of modules are part of `doc/openapi.json`.
  A client written for 0.1.0 keeps working. One that shows posts should
  expect a post `type` it does not know on a site with modules, and treat
  such a post as a file to download.

No setting was renamed or removed, and `server/config.yaml.dist` has no new
setting.

### Switching the cards module on

On a site that already has posts, follow the three steps under
[The cards module](INSTALL.md#the-cards-module): create the tag category
`creator`, switch the module on, and then have it read the existing posts:

```console
user@host:lithica$ docker compose run --rm server ./lithica-admin reextract
```

Until that has run, cards that were uploaded as pictures before the module
was on are not found by the `card-` search tokens and have no card to show.
The command takes one kind per run if you want to limit it:
`./lithica-admin reextract --kind card_v2` (`card_v1`, `card_v2`,
`card_v3`).

Posts that were uploaded before the module was on do not get the tags of
their cards: tags are added when a file is uploaded or replaced.

### If you ran a development build of 0.2.0

A site that had the `cards` module on with a build from before the release
(the `phase-4.4` or `phase-4.5` branches) holds cards without the summary
that the search and the `card` post field read. They show as cards, but the
`card-creator:`, `card-lorebook:` and `card-greetings:` tokens do not find
them, and their `card` field has no name. Run the same command once:

```console
user@host:lithica$ docker compose run --rm server ./lithica-admin reextract
```

### Going back to 0.1.0

Check out `v0.1.0` and start it. The database is the same. Posts made of
CHARX files stay in it, and 0.1.0 does not know their type: it fails on
every request that returns such a post, a page of the post list included.
Delete those posts while still on 0.2.0 if you mean to go back.

## From szurubooru to Lithica 0.1.0

Lithica is a fork of szurubooru and takes over a szurubooru site as it is:
the same uploads directory, the same database, the same `config.yaml`. Three
things need your hands: the database files (PostgreSQL 11 to 17), `secret`
if you never changed it, and the names in your compose setup. The rest
happens when the server starts.

The database is brought forward step by step from whatever version of
szurubooru you run. The upgrade was tested from the last one, commit
`10ac850` (July 2026).

### Before you start

- **Back up** the uploads directory, the database and `server/config.yaml`.
  The dump in the PostgreSQL steps below is your database backup; do not
  skip it.
- Lithica has images for `linux/amd64` and `linux/arm64`. There is none for
  32-bit ARM (`linux/arm/v7`) any more.
- Expect downtime: the database has to be dumped and restored.

### What changes for you

| | szurubooru | Lithica 0.1.0 |
|---|---|---|
| Source | `github.com/rr-/szurubooru` | `github.com/DominykasVad/lithica` |
| Server image | `szurubooru/server` (Docker Hub) | `ghcr.io/dominykasvad/lithica-server` |
| Client image | `szurubooru/client` (Docker Hub) | `ghcr.io/dominykasvad/lithica-client-legacy` |
| Database | PostgreSQL 11 | PostgreSQL 17 |
| Admin script | `szuru-admin` | `lithica-admin` |
| Client source | `client/` | `legacy/client/` |

What does **not** change: the names of the compose services (`server`,
`client`, `sql`), the variables in `.env`, the paths inside the containers
(`/data`, `/opt/app/config.yaml`), the user the server runs as (1000), the
layout of the uploads directory, and the settings in `config.yaml`. No
setting was renamed or removed. You can keep your database user and your
directories under their old names; nothing depends on them being called
`lithica`.

### Steps

1. **Stop the site and take the database dump** while your old setup is
   still in place: steps 1 to 3 of [PostgreSQL 11 to 17](#postgresql-11-to-17)
   below, run in your szurubooru checkout.

2. **Get Lithica** next to your old checkout and carry your two files over:

    ```console
    user@host:~$ git clone --branch v0.1.0 https://github.com/DominykasVad/lithica.git lithica
    user@host:~$ cp szuru/server/config.yaml lithica/server/config.yaml
    user@host:~$ cp szuru/.env lithica/.env
    user@host:~$ cp szuru/lithica-pg11.dump lithica/
    user@host:~$ cd lithica
    ```

    `MOUNT_DATA` and `MOUNT_SQL` in `.env` keep pointing at your existing
    directories. If your old `docker-compose.yml` had changes of your own,
    make them again in the new one rather than copying the old file: the
    images are different.

3. **Check `config.yaml`** against the list under
   [Settings to look at](#settings-to-look-at). If `secret` is still
   `change`, the server will not start; see
   [If you never changed `secret`](#if-you-never-changed-secret).

4. **Restore the database into PostgreSQL 17**: steps 4 and 5 of
   [PostgreSQL 11 to 17](#postgresql-11-to-17), run in the Lithica checkout.

5. **Build or pull the images and start** ([INSTALL.md](INSTALL.md) explains
   the two ways):

    ```console
    user@host:lithica$ docker compose build     # or: docker compose pull
    user@host:lithica$ docker compose up -d
    user@host:lithica$ docker compose logs -f server
    ```

    On its first start the server updates the database tables. On a large
    site this takes a while: the data behind the similar-image search is
    copied into a new table. The API answers once the log says
    `Application startup complete`.

    If the update stops with `pool name(s) are longer than 128 characters`,
    shorten those names in the database and start the server again. The
    API never accepted names that long, so this only happens to names that
    were written some other way.

6. **Read the log.** If it warns that posts have no image signature or no
   MD5 checksum, compute them. szurubooru did this in the background at
   every start; Lithica leaves it to you, once:

    ```console
    user@host:lithica$ docker compose run --rm server ./lithica-admin backfill all
    ```

7. Check that your posts, tags, users and uploads are there, and that you
   can log in and upload.

### Settings to look at

Nothing in `config.yaml` was renamed, but some defaults are stricter than
what szurubooru did, and they may apply to you:

- **`secret`** must not be the template's `change`. See below.
- **`domain`** is required when `smtp` is configured: password reset mails
  link to it and to nothing else. Without it the server does not start and
  says so. Set it to the public address of the site, e.g.
  `https://booru.example.com`.
- **`name`**: if you never set it, the site was called `szurubooru`; the
  default is now `lithica`. Set `name` to keep the old one.
- **`cors_origins`**: szurubooru let every website call the API from a
  browser. Lithica lets none but the site itself. If you run a web client on
  another address than the API, list that address here.
- **`allow_private_downloads`**: "upload from URL" no longer fetches from
  private network addresses (`localhost`, `192.168.x.x` and the like). Set
  it to `true` only if you import from your own network on purpose.
- **`max_upload_size`**: new, 1 GiB by default. The client image allows the
  same.
- **`modules`** and the privilege `posts:view:content:private`: new, for
  optional modules. 0.1.0 ships none; leave them alone.
- If you run the server **without Docker** and set `database` yourself: the
  address must start with `postgresql://`. `postgres://` is no longer
  understood.

Settings your file does not have get their value from `config.yaml.dist`,
as before, so new privileges need no editing.

### If you never changed `secret`

szurubooru ran with the template's `secret: change`; Lithica refuses to. The
value is public, and it protects the passwords and the addresses of the
uploaded files. Set `secret` in `config.yaml` to your own long random string
(`openssl rand -hex 32`) and start the stack. Changing it has two
consequences, each of which you deal with once:

1. **The stored files have to be renamed**, because their names are derived
   from the secret. Until then no post shows its picture:

    ```console
    user@host:lithica$ docker compose run --rm server ./lithica-admin --reset-filenames
    ```

2. **Every password stops working**, because the hashes are salted with the
   secret. Give your own account a new one with the command below. The
   other users can use "Forgot your password?" if mail is set up;
   otherwise set theirs the same way:

    ```console
    user@host:lithica$ docker compose run --rm server ./lithica-admin --change-password <user>
    ```

If your `secret` was already your own, keep it and none of this applies.

### The uploads directory

Nothing is converted and nothing needs to move: Lithica reads and writes the
directory as szurubooru left it. One folder is new,
`temporary-uploads/.tmp`, where a file is kept while it is being uploaded,
so the volume now needs room for the uploads in flight as well. Leftovers in
it are cleaned up when the server starts.

### If you use the API from your own programs

The API is the one szurubooru had; `doc/API.md` still describes it and
`doc/openapi.json` is its exact contract. These are the differences:

- Password reset tokens are random, work once and expire (one hour by
  default). The two endpoints are the same; a link from an old mail is not.
- `Access-Control-Allow-Origin: *` is no longer sent; see `cors_origins`.
- A request larger than `max_upload_size` is answered with 413 and the error
  `RequestTooLargeError`.
- Some requests that ended in a 500 get a proper error: an id in the path
  that is not a number (400 for posts and comments, 404 for pools) and a
  JSON body that is not an object (400).
- An unknown path is 404 whatever the `Accept` header says; it used to be
  406 without `Accept: application/json`.
- New, and safe to ignore: posts have a `contentKinds` field, and
  `GET /post/<id>/content` exists. Both are empty without modules.

### Going back to szurubooru

The database changes are not undone by starting an old image. To go back,
restore the dump you took in step 1 into PostgreSQL 11 with your old setup
(see "Going back to PostgreSQL 11" below). The uploads directory needs
nothing, unless you ran `--reset-filenames`: then run szurubooru's
`szuru-admin --reset-filenames` with the old `secret` in place.

### PostgreSQL 11 to 17

The compose files now run PostgreSQL 17. A data directory created by
PostgreSQL 11 cannot be opened by 17: the server stops at startup with
`database files are incompatible with server`. The data has to be dumped
from 11 and restored into 17. Nothing in the data directory is converted in
place, so the old directory stays intact until you delete it.

The commands assume the layout from [INSTALL.md](INSTALL.md): you are in the
repository root, `.env` holds `POSTGRES_USER`, `POSTGRES_PASSWORD` and
`MOUNT_SQL`, and the database service is called `sql`. If you set
`POSTGRES_DB`, use it wherever `$POSTGRES_USER` is given as the database
name below.

1. Load the settings into your shell and stop everything except the
   database. Do this **before** updating `docker-compose.yml`, while the
   `sql` service is still PostgreSQL 11:

    ```console
    user@host:lithica$ set -a; . ./.env; set +a
    user@host:lithica$ docker compose stop server client
    user@host:lithica$ docker compose up -d sql
    ```

2. Dump the database to a file outside the data directory and check that
   the file is not empty:

    ```console
    user@host:lithica$ docker compose exec -T sql pg_dump -U "$POSTGRES_USER" -Fc "$POSTGRES_USER" > lithica-pg11.dump
    user@host:lithica$ ls -lh lithica-pg11.dump
    ```

3. Stop the stack and move the old data directory aside. Keep it until the
   upgrade is verified:

    ```console
    user@host:lithica$ docker compose down
    user@host:lithica$ sudo mv "$MOUNT_SQL" "$MOUNT_SQL.pg11"
    user@host:lithica$ sudo mkdir "$MOUNT_SQL"
    ```

4. Update the source (or edit `docker-compose.yml` so that the `sql` service
   uses `image: postgres:17`), then start only the database. It initialises
   an empty PostgreSQL 17 data directory:

    ```console
    user@host:lithica$ docker compose up -d sql
    user@host:lithica$ docker compose exec -T sql pg_isready -U "$POSTGRES_USER"
    ```

5. Restore the dump:

    ```console
    user@host:lithica$ docker compose exec -T sql pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_USER" --no-owner < lithica-pg11.dump
    ```

6. Start everything and check that your posts, tags and users are there:

    ```console
    user@host:lithica$ docker compose up -d
    ```

7. Once you are satisfied, delete `"$MOUNT_SQL.pg11"`. Keep
   `lithica-pg11.dump` as a backup for as long as you like.

#### If you already started PostgreSQL 17 on the old directory

PostgreSQL 17 refuses to start and does not modify the old files. Stop the
stack and take the dump with a temporary PostgreSQL 11 container instead of
steps 1 and 2, then continue from step 3:

```console
user@host:lithica$ set -a; . ./.env; set +a
user@host:lithica$ docker compose down
user@host:lithica$ docker run -d --name lithica-pg11 -v "$MOUNT_SQL:/var/lib/postgresql/data" postgres:11-alpine
user@host:lithica$ docker exec lithica-pg11 pg_dump -U "$POSTGRES_USER" -Fc "$POSTGRES_USER" > lithica-pg11.dump
user@host:lithica$ docker rm -f lithica-pg11
```

#### Going back to PostgreSQL 11

Stop the stack, put the `postgres:11-alpine` image back in
`docker-compose.yml`, and move `"$MOUNT_SQL.pg11"` back to `"$MOUNT_SQL"`.
