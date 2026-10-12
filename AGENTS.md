# AGENTS.md

Rules and facts for any coding agent working in this repository. Read this file
and `PLAN.md` before starting any task. `PLAN.md` says *what* to do next; this
file says *how* to work. If they conflict, stop and ask.

## Project

**Lithica** is a self-hosted image board ("booru") engine. It is a hard fork of
[szurubooru](https://github.com/rr-/szurubooru) taken at upstream commit
`10ac850` (2026-07-25). There is no upstream tracking: do not add an upstream
remote, do not cherry-pick, do not open PRs against `rr-/szurubooru`.

- **Engine** (`Lithica`): generic booru — posts, tags, pools, users, comments,
  search, snapshots. Must stay usable as a plain image booru.
- **Modules**: optional features layered on the engine, switched on in config
  (`modules`). The first real one is `cards` (`lithica/modules/cards`,
  character cards). The module system is
  `lithica/registry.py` (what a module can add) and `lithica/func/post_content.py`
  (the embedded-content pipeline); `lithica/tests/fixtures/modules/dummy` is
  the example module to copy.
- The GitHub repo is `DominykasVad/lithica`. Use the new names everywhere in
  code and docs.

Licence is **GPLv3**. Keep `LICENSE.md` and the original copyright/attribution.
Never relicense, never strip headers or credits.

## Current phase

Phase 4 of PLAN.md: module file types and the `cards` module, server only
(baseline `v0.1.0` is released). Work only on tasks listed there, in order,
unless the owner says otherwise. Anything not listed in PLAN.md — including
any client work — is **out of scope**.

## Layout

```
server/
  pyproject.toml, uv.lock, .python-version
  lithica/              engine package (was szurubooru/)
    api/                HTTP layer (FastAPI routers)
    func/               business logic
    model/              SQLAlchemy models
    search/             query language
    migrations/         Alembic
    modules/            optional modules; engine code never imports from here
    registry.py         the module interface and the loaded modules
    tests/
      fixtures/modules/ modules that exist for the tests (the dummy module)
  lithica-admin         admin CLI (was szuru-admin)
legacy/client/          old vanilla-JS client + nginx config — FROZEN, see below
doc/
PLAN.md, AGENTS.md, ANALYSIS.md
```

Layering on the server is strict: `api → func → model`. `api` handles HTTP
only (parsing, auth, status codes). Business rules live in `func`. Models
contain no HTTP or request logic.

## Toolchain and commands

Python **3.13**, managed by **uv** only. Each command is written for the
directory in the "Run from" column.

| Task | Run from | Command |
|---|---|---|
| Install / sync env | `server/` | `uv sync` |
| Add dependency | `server/` | `uv add <pkg>` (dev: `uv add --dev <pkg>`) |
| Lint | `server/` | `uv run ruff check .` |
| Format | `server/` | `uv run ruff format .` |
| Type check | `server/` | `uv run pyright` |
| Module boundary | `server/` | `uv run lint-imports` (also part of the test suite) |
| Test database | `server/` | `docker compose -f docker-compose.test.yml up -d` (PostgreSQL 17 on `localhost:5433`) |
| Tests (local) | `server/` | `uv run pytest -n auto` — uses `LITHICA_TEST_DATABASE_URL`, default `postgresql://postgres:postgres@localhost:5433/postgres` |
| New migration | `server/` | `uv run alembic revision --autogenerate -m "<what>"`, then review by hand — needs `database:` and `data_dir:` set in a local `server/config.yaml` (git-ignored) |
| Tests (container) | repo root | `scripts/run-server-tests.sh [path]` |
| Dev stack | repo root | `docker compose -f docker-compose.dev.yml up` — needs a `.env` (copy `doc/example.env`) and a `server/config.yaml` that sets `secret` |

Never use `pip`, `pip install`, `requirements.txt`, `poetry` or `conda`.
`uv.lock` is committed; change it only through `uv add` / `uv remove` /
`uv lock`.

No local PostgreSQL install is needed or wanted — the database always runs in
a container. Everything must work on any host with Docker-compatible tooling
and uv; do not assume a specific OS, CPU architecture or machine.

## Definition of done (every task)

1. `ruff check`, `ruff format --check`, `pyright` and the full test suite pass.
2. New or changed behaviour has tests. Do not delete, skip or weaken an
   existing test to make the suite pass; if a test is genuinely wrong, say so
   in the report and explain.
3. The matching checkbox in `PLAN.md` is ticked **in the same commit** as the
   change (never a separate "tick" commit). If you made a real decision —
   a choice between alternatives that later work must respect — add one line
   to the **Decision log** (see the rules there). Everything else (what you
   did, what you left alone, observations) goes in the commit message body.
4. Report: what changed, what you verified and how, what you did not verify.

## Hard rules

### Scope and decisions
- Working notes, scratch scripts and investigation output go in `scratch/`
  at the repo root (git-ignored; create it if missing). Never commit them and
  never leave such files elsewhere in the tree.
- Branches: phases are milestones split into sub-phases; **one sub-phase =
  one branch (`phase-4.3`) = one PR**. Start the next sub-phase only after the
  previous one is merged into `main`. Never commit directly to `main`; the
  owner merges. Keep commits small inside the branch.
- Do one PLAN.md task per change set. No drive-by refactors, renames or
  reformatting outside the task.
- If a task needs a decision PLAN.md does not cover (a new dependency, a
  schema change not described, an API change, a security trade-off), stop and
  ask. Do not pick silently.
- Mechanical changes (renames, reformatting) go in their own commits, never
  mixed with behaviour changes.

### API compatibility
- Through phases 0–3 the HTTP API stays **wire-compatible** with
  `doc/API.md`: same paths, methods, parameter names, JSON shapes, error body
  (`name`, `title`, `description`) and status codes. The legacy client is the
  smoke test for this.
- The only allowed breaking changes are the ones listed under
  "Intentional API changes" in PLAN.md.
- `doc/openapi.json` is the API contract. It is generated from code
  (`uv run python -m lithica.openapi > ../doc/openapi.json`) and CI fails if
  the committed file differs. Never hand-edit it.
- The contract includes the routes of **every module in `lithica/modules/`**,
  each tagged with its module's name, whatever `modules` or `MODULES` say on
  the machine that generates it. Regenerate it after changing a module's
  routes too. A module's router sets no tags of its own.

### Database
- PostgreSQL 17 is the only database tested and shipped, but code must stay
  **database-agnostic**:
  - SQLAlchemy ORM / Core expressions only. No `text()`, no raw SQL strings,
    no `sa.dialects.*` types, no Postgres-only functions — unless listed under
    "Allowed dialect exceptions" in PLAN.md.
  - JSON columns use `sa.JSON().with_variant(JSONB, "postgresql")`.
  - Case-insensitive matching uses `func.lower(col).like(...)`, not `ilike`.
- Migrations: Alembic only. Never edit a migration that has been committed to
  `main`; add a new one. Every migration has a working `downgrade()`.
  Data migrations must be idempotent and batch large tables.
- Timestamps are stored as **naive UTC**. Get "now" only via `util.utcnow()`
  (returns naive UTC). Never call `datetime.utcnow()` or `datetime.now()`
  directly, and do not introduce timezone-aware values into model columns.

### Sessions and concurrency
- `func/` code uses the request-scoped session from `lithica.db`. After phase
  2 the scope is a `ContextVar` set per request, **not** thread-local. Never
  rely on thread identity for request state.
- Endpoints are plain `def` (run in the thread pool), not `async def`, because
  the business layer is synchronous. Do not make an endpoint `async` unless it
  awaits nothing blocking, and say why.
- Background work (upload purge, backfills) creates and closes its own
  session. Never share a session between threads.
- Assume more than one server process may run. Do not add new in-process
  caches or global mutable state.

### Modules (phase 3+)
- The engine must never import from `lithica.modules.*`. Modules register
  themselves through the module registry. `import-linter` enforces this in CI.
- A module may import engine code, never another module.
- A module is the package `lithica/modules/<name>/` with a `registry.Module`
  object named `module`. It adds to the engine and never replaces anything of
  it. New modules, and the files listed under `strict` in `pyproject.toml`,
  are type-checked in pyright's strict mode.
- Everything an extractor reads comes from an uploaded file: untrusted. A
  failing extractor or hook must never fail an upload (the pipeline catches
  it), and payloads are never logged. The one way an extractor refuses an
  upload is on purpose, by raising `registry.FileRejected`, for content that
  cannot be stored and must not go missing silently.
- A payload may be 1 MiB of JSON unless its kind asks for more
  (`ContentKind.max_payload_size`, at most 32 MiB).
- A module's file types (`registry.FileType`) are asked only about files the
  engine itself does not know. A detector refuses a file of its type by
  raising `registry.FileRejected` with a message for the uploader; anything
  else it raises counts as "not mine". The stored file is the upload, byte
  for byte. A MIME type is at most 32 characters (the column's size).
- Module tables are created by normal Alembic migrations regardless of
  whether the module is enabled; the config switch only enables behaviour.

### Security
- Never commit `config.yaml`, `.env`, secrets, tokens or real user data.
- The server must refuse to start with the default `secret`.
- Treat all uploaded content — including metadata embedded in files (PNG text
  chunks, EXIF, video metadata) — as untrusted. Never execute it, never
  render it as HTML server-side, never pass it to a shell. Subprocess calls
  (`ffmpeg`, `yt-dlp`) use argument lists, never `shell=True`.
- Use `secrets` for tokens and `hmac.compare_digest` for comparisons.
- Do not log passwords, tokens, reset links or request bodies.

### Legacy client
- `legacy/client/` is **frozen**. Change it only when needed to keep it
  building and talking to the API, or for the rebrand items PLAN.md lists.
  No features, no refactors, no dependency upgrades beyond what a build fix
  needs.

### Style
- ruff defaults as configured in `pyproject.toml`, line length 88.
- Type-annotate all new and changed code. Do not add `# type: ignore` or
  `Any` to silence pyright without a comment saying why.
- No `print()` in server code; use `logging.getLogger(__name__)`.
- Commit messages: `<area>: <imperative summary>` where area is `server`,
  `client`, `ci`, `docker`, `doc`, or a module name. Body explains *why*.

## Reference

- `PLAN.md` — phases, tasks, decisions, open questions.
- `ANALYSIS.md` — snapshot analysis of the codebase at the fork point. Local only (git-ignored); may be absent in a fresh clone.
- `doc/openapi.json` — the API contract (generated; see "API compatibility").
- `doc/API.md` — how the API works: authentication, uploads, errors, resources, search syntax.
- `server/config.yaml.dist` — all settings and the privilege matrix.
