# Installing Lithica

Lithica runs as three containers: the **server** (the API, Python 3.13 on
Debian), the **client** (nginx serving the web client and passing `/api/` on
to the server) and **PostgreSQL 17**. Uploaded files live in one directory on
the host, the database in another.

Coming from szurubooru? Read [UPGRADING.md](UPGRADING.md) instead; it starts
from your existing data.

- [Requirements](#requirements)
- [Install](#install)
- [Using published images](#using-published-images)
- [Configuration](#configuration)
- [Modules](#modules)
- [Administration from the command line](#administration-from-the-command-line)
- [Deployment notes](#deployment-notes)
- [Updating](#updating)
- [Running the server from source](#running-the-server-from-source)

## Requirements

- Docker Engine with the Compose plugin (`docker compose`, Compose v2), or
  compatible tooling.
- A 64-bit host: images are published for `linux/amd64` and `linux/arm64`.
  32-bit ARM is not supported.
- Disk space for the uploads, plus room for the uploads that are in flight:
  a file is written to the data directory while it arrives.

## Install

1. Get the source of the release you want. It holds the compose file and the
   configuration template, also when you run published images:

    ```console
    user@host:~$ git clone --branch v0.2.0 https://github.com/DominykasVad/lithica.git lithica
    user@host:~$ cd lithica
    ```

2. Configure the application:

    ```console
    user@host:lithica$ cp server/config.yaml.dist server/config.yaml
    user@host:lithica$ edit server/config.yaml
    ```

    You can delete every line whose default suits you; see
    [Configuration](#configuration). One setting has no usable default:

    - `secret`: the server refuses to start while it has the value from the
      template. Set it to your own long random string, for example the
      output of `openssl rand -hex 32`, and keep it safe. Changing it later
      invalidates every password and the names of all stored files.

3. Configure Docker Compose:

    ```console
    user@host:lithica$ cp doc/example.env .env
    user@host:lithica$ edit .env
    ```

    `.env` must be in the root of the repository. Set at least
    `POSTGRES_PASSWORD`, and `MOUNT_DATA` and `MOUNT_SQL`, the two host
    directories for the uploads and the database. The server runs as user
    and group 1000 inside its container and must be able to write to
    `MOUNT_DATA`.

4. Build the images:

    ```console
    user@host:lithica$ docker compose build
    ```

    To run the published release images instead of building, see
    [Using published images](#using-published-images).

5. Start it. The first time, start the database on its own and give it a
   moment to initialise:

    ```console
    user@host:lithica$ docker compose up -d sql
    user@host:lithica$ docker compose up -d
    ```

    The server creates and updates its database tables by itself every time
    it starts. Watch the log with:

    ```console
    user@host:lithica$ docker compose logs -f
    ```

6. Open `http://<host>:<PORT>/` and register. **The first account that is
   registered becomes the administrator.**

## Using published images

Release images are published to the GitHub Container Registry when a release
is made, tagged with the release version:

- `ghcr.io/dominykasvad/lithica-server:<version>`
- `ghcr.io/dominykasvad/lithica-client-legacy:<version>`

`latest` points at the newest release that is not a pre-release. To use the
images, edit `docker-compose.yml`: in the `server` and `client` services,
comment out the `build` section and uncomment the `image` line below it,
setting the version you want. Then pull instead of building:

```console
user@host:lithica$ docker compose pull
user@host:lithica$ docker compose up -d
```

Use the same version for both images, and the `docker-compose.yml` and
`server/config.yaml.dist` of that version's source.

## Configuration

There are two places to configure things.

**`server/config.yaml`** holds the settings of the application. It is laid
over `server/config.yaml.dist`, which documents every setting and holds the
defaults, so your file only needs the settings you change. The ones most
sites touch:

| Setting | What it is |
|---|---|
| `secret` | Required. See [Install](#install). |
| `name` | The name of the site, shown in the client and in mails. |
| `domain` | The public address of the site, e.g. `https://booru.example.com`. Required when `smtp` is set: password reset mails link to it. |
| `smtp` | The mail server for password reset mails. Without it, users are shown `contact_email` instead. |
| `privileges` | Which rank may do what; `default_rank` is the rank of a new account. |
| `max_upload_size` | The largest request, 1 GiB by default. The nginx of the client image allows the same; a reverse proxy in front must allow it too. |
| `cors_origins` | Other websites that may call the API from a browser. Leave empty when you use the bundled client. |
| `allow_private_downloads` | Whether "upload from URL" may fetch from private network addresses. Off by default. |
| `modules` | The optional modules to switch on. See [Modules](#modules). |
| `api_docs` | Serves the API's OpenAPI document and browsable documentation under `/api/docs`. Off by default. |

In the containers, `data_dir`, `data_url` and `database` are set from the
environment and anything you write for them in `config.yaml` is ignored.

**`.env`** holds what Docker Compose needs:

| Variable | What it is |
|---|---|
| `POSTGRES_USER`, `POSTGRES_PASSWORD` | Database credentials. The database is created with them on first start. |
| `MOUNT_DATA`, `MOUNT_SQL` | Host directories for the uploads and for the database files. |
| `PORT` | Where the client listens, e.g. `8080`, or `127.0.0.1:8080` behind a reverse proxy. |
| `BASE_URL` | The path the site is served under, `/` by default. See [Deployment notes](#deployment-notes). |
| `THREADS` | How many requests one server process works on at once. Default 4. |
| `WORKERS` | How many server processes to start. Leave at 1: running several has not been verified yet. |
| `BUILD_INFO` | A text shown on the home page when you build the client yourself. |

Further variables can be set on the `server` service in `docker-compose.yml`:
`POSTGRES_HOST`, `POSTGRES_PORT` and `POSTGRES_DB` for a database elsewhere,
`DATA_URL`, `HOST`, `LOG_SQL=1` for SQL in the log, `API_DOCS=1` and
`MODULES` (see [Modules](#modules)).

After changing either file, restart: `docker compose up -d`.

## Modules

The engine is a plain image board. Optional features are **modules**:
packages that are part of the server and do nothing until they are switched
on. A module can read content embedded in uploaded files (PNG text chunks,
EXIF, video metadata), tag posts from it, accept kinds of files the engine
does not know, add search tokens, fields and routes to the API, and bring its
own `lithica-admin` commands.

Lithica ships one module, [`cards`](#the-cards-module), for character cards.
You switch modules on by name in `server/config.yaml`:

```yaml
modules: [cards]
```

and restart the server. In the containers you can name them in the
environment instead, comma-separated, on the `server` service in
`docker-compose.yml`:

```yaml
    environment:
      MODULES: cards
```

When `MODULES` is set, it replaces the `modules` setting of the config files
altogether; set to nothing (`MODULES: ""`), it switches every module off.
`lithica-admin` must see the same value, which it does when you run it with
`docker compose run --rm server`. Things to know:

- A name that is not a module is a configuration error, and the server does
  not start. The log names the module.
- `GET /api/info` lists the modules that are switched on (`modules`).
- Switching a module on does not touch the posts that are already there.
  To have it read their files too, run
  `docker compose run --rm server ./lithica-admin reextract`
  ([see below](#administration-from-the-command-line)).
- Switching a module off hides what it added. What it extracted from files is
  kept in the database and is back when the module is switched on again;
  tags it added to posts are ordinary tags and stay.
- A module's own kinds of files are accepted only while it is on. Posts made
  from them stay when it is switched off: their files are served and their
  posts can be edited and deleted as before. New files of that kind are
  refused until the module is on again.
- A module may mark parts of what it extracts as private. Those are shown
  only to ranks that have the `posts:view:content:private` privilege
  (moderators and up, by default).
- Every module's database tables exist whether the module is on or not, so
  switching modules never needs a database change.

### The cards module

`cards` turns the site into a library of character cards for AI chat
programs. With it on:

- **Card pictures.** A PNG picture that carries a card (Character Card V1,
  V2 or V3) is still an ordinary picture post; the card in it is read and
  kept with the post.
- **CHARX files** can be uploaded, which the plain engine refuses. A post
  made of one has the type `charx` and the card's main icon as its
  thumbnail. A CHARX file is a ZIP archive and is read with limits: at most
  1000 entries, 512 MiB unpacked, a `card.json` of 8 MiB, no encrypted
  entries; one that breaks a limit is refused with a message that says
  which. It is never unpacked to disk.
- **Tags.** A post gets its card's creator and the card's own tags as tags.
- **Search.** `card-creator:`, `card-spec:`, `card-format:`,
  `card-lorebook:` and `card-greetings:` find posts by their card.
- **Download.** `api/modules/cards/post/<id>/download` hands out the stored
  file under the character's name.

A card may be 16 MiB of text once the pictures embedded in it are taken
out; a larger one is refused. The API of the module is described in
[API.md](API.md#the-cards-module).

To switch it on:

1. **Create the tag category `creator`** on the tag categories page of the
   web client, with the colour you like. Creators of cards are tagged in
   it. If the category is not there when a card is uploaded, its creator is
   created in your default category instead and stays there until you move
   the tag.

2. **Switch the module on:** `modules: [cards]` in `server/config.yaml`, or
   `MODULES: cards` on the `server` service in `docker-compose.yml`. Then
   `docker compose up -d`.

3. **Have it read the posts that are already there**, if there are any:

    ```console
    user@host:lithica$ docker compose run --rm server ./lithica-admin reextract
    ```

    This reads the file of every post that can hold a card and stores the
    cards it finds. Without it, cards uploaded before the module was on are
    plain pictures to the site: they are not found by the `card-` search
    tokens and have no card to show. It can run while the server is up and
    can be repeated. To read one kind only, name it:
    `./lithica-admin reextract --kind card_v2` (the kinds are `card_v1`,
    `card_v2` and `card_v3`; one per run). Re-extraction does not tag: the
    tags of a card are added when its file is uploaded or replaced.

    Run it too after an update of the server, when the notes in
    [UPGRADING.md](UPGRADING.md) say that the module stores more than it
    did.

Uploads of CHARX files are as large as any upload may be (`max_upload_size`,
and the limit of a reverse proxy in front). The files are stored with the
extension `.charx` in the uploads directory, beside the pictures.

## Administration from the command line

`lithica-admin` does what cannot be done from the web client. Run it in a
one-off server container:

```console
user@host:lithica$ docker compose run --rm server ./lithica-admin --help
```

| Command | What it does |
|---|---|
| `--change-password <user>` | Sets a new password for a user, e.g. when mail is not set up. |
| `backfill signatures`, `backfill md5`, `backfill all` | Computes data that older posts lack: image signatures for the similar-image search, MD5 checksums. |
| `import <folder> --user <user> --safety <safety>` | Makes a post of every file in a folder. See [Importing a folder](#importing-a-folder). |
| `reextract [--kind <kind>]` | Has the modules that are switched on read the files of the existing posts again. For after switching a module on or updating it. |
| `--regenerate-thumbnails` | Recreates missing thumbnail files. |
| `--check-all-audio` | Reports videos whose sound flag does not match the file. Changes nothing. |
| `--reset-filenames` | Renames the stored files after `secret` was changed. |

`backfill`, `reextract` and `import` can be repeated and can run while the
server is up. The server never rewrites existing posts on its own: when posts wait for
a backfill, it says so in its log at startup and names the command.

### Importing a folder

`lithica-admin import` brings a collection that is on disk into the site: a
post per file, for every file in the folder and the folders in it, in the
order of their names. A file goes the way an upload goes, so it gets its
thumbnail, and the modules that are switched on read it and tag the post:
with `cards` on, a folder of card pictures and CHARX files becomes posts
with their cards, creators and tags.

The server runs in a container, so the folder has to be shown to it. Mount
it read-only for the one run:

```console
user@host:lithica$ docker compose run --rm -v /path/to/collection:/import:ro \
    server ./lithica-admin import /import --user <user> --safety safe --dry-run
```

- `--user` (required): the account the posts are uploaded as. It must exist.
- `--safety` (required): `safe`, `sketchy` or `unsafe`, for every post.
- `--tags a,b`: tags to put on every post; they are created if missing.
- `--dry-run`: says what would happen to each file and creates nothing. Run
  it first. It finds files that are posts already, files of a type nobody
  knows and files a module refuses; a picture that is broken is only found
  by the import itself.

What it prints: a line per file as it goes, then a summary (created,
skipped, refused, failed) and the files with a problem.

- **Skipped** is a file that is a post already, byte for byte. That makes
  the command safe to repeat: a second run over the same folder creates
  nothing, and a run that was interrupted is continued by running it again.
- **Refused** is a file the site does not take: not a picture, a video or a
  kind of file a module knows, or one a module refuses. It is reported and
  the import goes on.
- **Failed** is a file that should have worked and did not; the log says
  why. Only this makes the command end with an error.

The files are copied into the site; the folder is not changed. Files and
folders whose names start with a dot are left out. Nothing asks for
privileges: the command is yours, whatever rank `--user` has.

## Deployment notes

1. **Behind a reverse proxy.** For anything public, put a reverse proxy with
   TLS in front. Make the client listen on localhost only by setting
   `PORT=127.0.0.1:8080` in `.env` and pass everything on to it. With nginx:

    ```nginx
    server {
        server_name booru.example.com;
        listen 443 ssl;
        # ssl_certificate and ssl_certificate_key go here

        # as large as max_upload_size in config.yaml
        client_max_body_size 1G;

        location / {
            proxy_http_version 1.1;
            proxy_pass http://127.0.0.1:8080;
            proxy_set_header Host              $http_host;
            proxy_set_header X-Real-IP         $remote_addr;
            proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
        }
    }
    ```

    Set `domain` in `config.yaml` to the public address.

2. **Under a path instead of a domain of its own.** To serve the site at
   `https://example.com/lithica/`, set `BASE_URL=/lithica/` in `.env` and
   have the reverse proxy pass that path on:

    ```nginx
    location /lithica {
        proxy_http_version 1.1;
        proxy_pass http://127.0.0.1:8080/;
        proxy_set_header Host              $http_host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Script-Name     /lithica;
    }
    ```

3. **Uploads on another domain.** To serve the site at `http://example.com/`
   and the uploaded files from `http://static.example.com/`, run the server
   container with the environment variable
   `DATA_URL=http://static.example.com/` and have that host serve the
   contents of `MOUNT_DATA`.

4. **Hosts with IPv6 disabled.** The server container listens on `::`, which
   is every address of the container, IPv4 and IPv6. On a host where IPv6 is
   disabled this fails and the server does not start (`Cannot listen on ::
   ...`). Run the server container with the environment variable
   `HOST=0.0.0.0` there, to listen on IPv4 only.

5. **Backups.** Everything that matters is in three places: the directory
   `MOUNT_DATA`, the database (`docker compose exec -T sql pg_dump -U
   "$POSTGRES_USER" -Fc "$POSTGRES_USER" > lithica.dump`), and
   `server/config.yaml`, whose `secret` the first two are useless without.

## Updating

To move to a newer release, read its notes in [UPGRADING.md](UPGRADING.md)
first, then:

```console
user@host:lithica$ git fetch --tags && git checkout <version>
user@host:lithica$ docker compose build     # or: docker compose pull
user@host:lithica$ docker compose up -d
```

The server brings the database up to date when it starts. Back up first:
the database changes are not undone by going back to an older image.

## Running the server from source

For development, or to run without Docker. You need
[uv](https://docs.astral.sh/uv/), `ffmpeg` on the `PATH`, and a PostgreSQL 17
database. uv installs Python 3.13 and the dependencies, pinned by `uv.lock`;
do not use `pip`.

```console
user@host:lithica$ cd server
user@host:server$ uv sync --no-dev
user@host:server$ cp config.yaml.dist config.yaml
user@host:server$ edit config.yaml
```

Besides `secret`, set the three settings at the end of the file, which the
containers otherwise set for you: `database`
(`postgresql://user:password@host:5432/name`), `data_dir` (an absolute path
the server can write to) and `data_url` (where a web server serves that
directory). Then create the tables and start:

```console
user@host:server$ uv run alembic upgrade head
user@host:server$ uv run python -m lithica.serve
```

The API listens on port 6666 (`PORT`). It serves no web pages and no
uploaded files: a web server in front does that, as the client image's
`legacy/client/nginx.conf.docker` shows.

A development stack with live reload, the test suite and the rules of the
code base are described in [AGENTS.md](../AGENTS.md):
`docker compose -f docker-compose.dev.yml up` starts the stack, and
`uv run pytest -n auto` in `server/` runs the tests against the database of
`server/docker-compose.test.yml`.
