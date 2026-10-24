# Sardonyx

Sardonyx is the web client for Lithica with the cards module. It is licensed
under the MIT licence (see [LICENSE](LICENSE) in this folder). No code, styles
or assets from `legacy/client/`, which is GPL, may be used here.

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
`/data` on to a running Lithica: by default the dev stack's client on
`http://localhost:8080` (start the stack from the repository's root with
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
other path is answered with the app, which finds its page from there. The dev
stack runs it on port 8082 next to the legacy client.
