# Upgrading

- [From 0.1.0 to 0.2.0](#from-010-to-020)
- [From szurubooru to Lithica 0.1.0](#from-szurubooru-to-lithica-010)

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
