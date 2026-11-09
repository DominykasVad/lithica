# Sardonyx

Sardonyx is the web client for Lithica with the cards module. It is licensed
under the MIT licence (see [LICENSE](LICENSE) in this folder). No code, styles
or assets from szurubooru's client (upstream, or this repository's history),
which is GPL, may be used here.

It is a single-page app (Vite, React, TypeScript) that talks to the Lithica
server only through its HTTP API, as `doc/openapi.json` describes it.

## Working on it

You need Node 26 (see `.nvmrc`) and pnpm; pnpm switches itself to the
version `package.json` names. All commands are run from this folder.

```console
user@host:sardonyx$ pnpm install
user@host:sardonyx$ pnpm dev
```

`pnpm dev` serves the app on `http://localhost:5173` and passes `/api` and
`/data` on to a running Lithica: by default the dev stack's Sardonyx on
`http://localhost:8082` (start the stack from the repository's root with
`docker compose -f docker-compose.dev.yml up`). To use another site, set
`LITHICA_URL`:

```console
user@host:sardonyx$ LITHICA_URL=http://localhost:8090 pnpm dev
```

| Task                     | Command                                               |
| ------------------------ | ----------------------------------------------------- |
| Install                  | `pnpm install` (CI: `pnpm install --frozen-lockfile`) |
| Dev server               | `pnpm dev`                                            |
| Build                    | `pnpm build` (into `dist/`)                           |
| Lint                     | `pnpm lint`                                           |
| Format                   | `pnpm format`                                         |
| Lint and format check    | `pnpm check`                                          |
| Type check               | `pnpm typecheck`                                      |
| Tests                    | `pnpm test`                                           |
| Regenerate the API types | `pnpm api:generate`                                   |
| Check the API types      | `pnpm api:check`                                      |

## The API types

`src/api/schema.ts` holds the types of every route and resource of the API,
generated from `../../doc/openapi.json` by `pnpm api:generate`. Never edit it
by hand: after a change of the server's API, regenerate the contract on the
server and then this file. CI fails when it is out of date.

Every field of a resource is optional in these types, as in the contract: a
request may ask for some fields only (`fields=`). Code that shows a resource
says what to show when a field is not there.

Requests go through `src/api/client.ts`, which adds `Accept:
application/json` (the API answers nothing else) and the credentials of the
user who is logged in.

## The image

`Dockerfile` builds the app and serves it with nginx: `/api/` is passed on to
the server (the container named by `BACKEND_HOST`, `server` by default) and
`/data/` is read from the data volume, mounted read-only at `/data`. Every
other app path is answered with the app, which finds its page from there. The dev
stack runs it on port 8082.

### Signed file links

Set `FILE_LINK_SECRET` to the server's `file_link_secret` to require nginx's
secure_link signatures for post content and thumbnails under `/data/`. Avatars
are unsigned. Without a secret, file delivery stays unsigned. This is separate
from the site's `secret` and from the share route below.

### Share links

`/share/<token>` proxies to the server, which checks the link on every request
and asks nginx to deliver the current file through an internal `/_share/`
location. Direct requests to that internal location return 404. Share links
work without login and remain separate from signed file links. They carry the
upload CSP, `nosniff`, `no-referrer` and `private, no-cache`. The share route's
access log is disabled. Without this nginx (when reaching the server directly),
a successful share request has an empty body and delivers no file.

The server's `share_links_nsfw` setting defaults to false; changing the site's
`secret` invalidates all share links. The management UI follows in phase 6.5b.
