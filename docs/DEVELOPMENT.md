# Development Guide

> Monorepo: Python 3.11 backend (FastAPI), TypeScript frontend (React 18 + Vite),
> and an optional Python MCP server. Two runtime containers, driven from
> `Makefile` + `docker-compose.yml`. `./bnkscope up` is the supported entry point.

Everything below is tool-neutral: build, test, architecture, style, and workflow
conventions for anyone working on this repo. Contribution process lives in
[CONTRIBUTING.md](../CONTRIBUTING.md).

---

## Build / Lint / Test Commands

### Quick Validation (run before every commit)

```bash
make quick-check          # ~15s — ruff + mypy (core/schemas) + openapi types freshness
make pre-push             # ~90s — quick-check + ALL test suites in parallel (mirrors CI)
make push                 # pre-push + git push + gh run watch
```

`make pre-push` is **mandatory** before every push. CI is a validation gate, not a discovery channel.

### Backend (Python — FastAPI + pytest)

```bash
cd backend && source .venv/bin/activate && python -m pytest tests/ --tb=short -q          # all
cd backend && source .venv/bin/activate && python -m pytest tests/unit/test_schemas_system.py -v  # single file
cd backend && source .venv/bin/activate && python -m pytest tests/unit/test_schemas_system.py -k "test_valid_batch_update" -v  # single test

make test-backend-unit        # tests/unit/ — pure functions, schemas, no DB
make test-backend-component   # tests/component/ — service + DB, no HTTP
make test-backend-legacy      # flat tests/test_*.py — route/security tests
make test-contracts           # tests/contract/ — golden response-shape tests

cd backend && source .venv/bin/activate && python -m ruff check . --config pyproject.toml          # lint
cd backend && source .venv/bin/activate && python -m ruff check . --config pyproject.toml --fix    # autofix
cd backend && source .venv/bin/activate && python -m mypy core/ schemas/ --config-file pyproject.toml  # types
```

### Frontend (TypeScript — React + Vitest)

```bash
cd frontend-v2 && npm test -- --run                                              # all
cd frontend-v2 && npx vitest run src/hooks/__tests__/useSystem.test.ts           # single file
cd frontend-v2 && npx vitest run -t "fetches system health status"               # single test
cd frontend-v2 && npx vitest src/hooks/__tests__/useSystem.test.ts               # watch mode

cd frontend-v2 && npm run lint       # eslint
cd frontend-v2 && npx tsc --noEmit   # type check
cd frontend-v2 && npm run build      # build check (catches TS errors tsc may miss)
```

Those assume `node_modules` in the working tree. It can also live in the
`bnkscope-node` docker volume, which `scripts/bnkscope-verify-frontend.sh`
mounts over an empty `frontend-v2/node_modules` — no Node needed on the host.
The `make` targets below detect which you have and run either way; the bare
`cd frontend-v2 && …` lines above only work with a tree install.

```bash
make lint-frontend typecheck-frontend test-frontend   # either layout
make frontend-deps                                    # install into the docker volume
```

### MCP Server (Python — separate package)

```bash
cd mcp-server && PYTHONPATH=src python -m pytest tests/ --tb=short -q            # all
cd mcp-server && PYTHONPATH=src python -m pytest tests/test_tool_catalog.py -v   # single file
```

### Code Generation

```bash
make openapi-types         # regenerate openapi.json + frontend TypeScript types
make openapi-types-check   # CI-style check: fails if types are stale
# MUST run after changing any route, request model, or response model
```

### Running it

```bash
./bnkscope up              # the supported entry point — see below
./bnkscope up --no-build   # skip the build, use the images you have
./bnkscope down [--purge]  # stop; --purge drops the database and key
./bnkscope status          # running state, ports, registered clusters
```

Prefer `./bnkscope up` over a bare `docker compose up`. It picks the right
compose files for the platform, negotiates ports, and creates the read-only host
mounts **as you** — Docker would otherwise create the missing ones as empty
root-owned directories inside your home.

The `make deploy` / `deploy-backend` / `deploy-frontend` / `upgrade-safe`
targets still exist for a long-lived server install.

---

## Architecture

Two containers. No database server, no message broker, no worker pool, no
reverse proxy — a single-user tool watching a handful of clusters needs none of
them.

```
                      your browser
                            │
                  ┌─────────┴─────────┐
                  │  frontend (nginx) │  React 18 + Vite
                  └─────────┬─────────┘
                            │ /api  /ws
                  ┌─────────┴─────────┐
                  │  backend (uvicorn)│  FastAPI, one process:
                  │                   │   HTTP API · WebSockets
                  │  SQLite ◀── data  │   probes · periodic jobs
                  │  thread pool      │   4-thread background pool
                  │  APScheduler      │
                  └─────────┬─────────┘
                            │ kubeconfig (read-only)
                     your BNK clusters
```

An optional third container exposes read-only MCP tools
(`docker compose --profile mcp up`).

Persistence is SQLite in WAL mode with a `busy_timeout`; the schema is created
by `Base.metadata.create_all`, not migrations. Background work runs on a
4-thread pool in `core/background.py` (`submit()` / `run_sync()`); periodic jobs
run under APScheduler in `backend/jobs/`.

### Networking

`network_mode: host`, so the backend can reach clusters on your own networks
without Docker's bridge iptables getting between it and your VPN routes. On
macOS and WSL2 that binds inside Docker Desktop's VM instead, so `bnkscope up`
detects those platforms and layers `docker-compose.local.yml` — a bridge overlay
that publishes to `127.0.0.1` only.

Let `./bnkscope up` pick; it also negotiates ports and creates the read-only
host mounts as you.

---

## Project Structure

```
backend/                   # FastAPI + SQLAlchemy
  routes/                  # 23 route files (thin HTTP handlers)
  services/                # 44 service files (business logic)
  schemas/                 # Pydantic request/response models
  models/                  # SQLAlchemy ORM models
  core/                    # errors, config, encryption, background pool, logging
  jobs/                    # APScheduler periodic jobs
  utils/                   # shared helpers
  data/                    # static data shipped with the image
  tests/unit/              # pure unit tests (no DB)
  tests/component/         # service + DB tests
  tests/contract/          # golden response-shape tests
frontend-v2/               # React 18 + Vite + TailwindCSS + shadcn/ui
  src/hooks/               # React Query hooks (one per domain)
  src/lib/api/             # Axios API modules (one per domain)
  src/types/               # TypeScript types (hand-written + generated)
  src/components/          # UI components (shadcn/ui + custom)
  src/pages/               # route pages (lazy-loaded)
mcp-server/                # standalone MCP server (read-only tools, /mcp)
scripts/                   # build, verification and doc generation
bin/                       # small maintenance helpers
bnkscope                   # the CLI: up · down · status · open · logs · endpoint
```

### Backend layering

- `routes/` — thin HTTP handlers, one file per domain. **Every route must use `@handle_route_errors("description")`** and specify `response_model=` for typed responses.
- `services/` — business logic. Services take `db: Session` in `__init__`. Routes delegate here.
- `schemas/` — Pydantic v2 request/response models. **Schemas live in TWO places**: `backend/schemas/*.py` AND inline in `backend/routes/*.py` — check both.
- `models/` — SQLAlchemy ORM models.
- `core/` — domain errors, config, encryption, the background thread pool,
  structured logging. **mypy is strict here and in `schemas/`** — everywhere
  else is gradual. There is no auth middleware: bnkscope has no authentication,
  and the bind address is the access control.
- `jobs/` — APScheduler periodic work (cluster probes, refreshes).

### Frontend layering

- `hooks/use*.ts` — React Query hook per domain; the canonical data-fetch layer.
- `lib/api/*.ts` — Axios functions called by hooks; all share the `apiClient` in `lib/api/client.ts`.
- `types/` — hand-written types + `api-generated.ts` (regenerated from `backend/openapi.json`).
- `components/ui/` — shadcn/ui primitives (Radix + Tailwind). Feature components live alongside pages.
- `pages/` — route pages, lazy-loaded via `router.tsx`.
- State: `@tanstack/react-query` for server state, `zustand` for client state.

### Other services

- `mcp-server/` — a standalone MCP server exposing **read-only** backend routes
  as AI-callable tools at `/mcp`. Thin REST wrapper with its own `pyproject.toml`
  and test suite. Started only with `docker compose --profile mcp up`.

---

## Code Style

### Python (Backend + MCP Server)

- **Formatter/linter:** ruff (line-length 120, target Python 3.11)
- **Rules:** E, F, I (isort), N (pep8-naming), W, UP (pyupgrade)
- **Type checking:** mypy on `core/` and `schemas/` (strict); gradual elsewhere
- **Imports:** stdlib → third-party → first-party (`core`, `database`, `models`, `routes`,
  `services`, `schemas`, `tasks`, `modules`, `utils`) → relative
- **Naming:** files `snake_case.py`, classes `UpperCamelCase`, functions/vars `snake_case`,
  constants `SCREAMING_SNAKE_CASE`
- **Type hints:** Required on `core/` and `schemas/`. Use `X | None` (not `Optional[X]`),
  `dict[str, ...]`, `list[...]` (lowercase builtins, not `Dict`/`List`)
- **Error handling:** Use domain errors from `core.errors` (`NotFoundError`, `ValidationError`,
  `BadRequestError`, `UnauthorizedError`, `ForbiddenError`, `InternalError`).
  Every route must use `@handle_route_errors("description")` decorator.
- **Route pattern:** Thin HTTP handlers in `routes/`, delegate to service classes in `services/`.
  Services take `db: Session` in `__init__`. Routes use `response_model=` for typed responses.
- **Schemas:** Pydantic v2 `BaseModel`. Live in `backend/schemas/` AND inline in route files.
  Check BOTH locations. Request models often inline; response models in `schemas/`.

### TypeScript (Frontend)

- **Formatter/linter:** ESLint 9 (flat config) + Prettier + prettier-plugin-tailwindcss
- **Strict mode:** `"strict": true`, `noUnusedLocals`, `noUnusedParameters`
- **`no-explicit-any`:** ERROR level — no `any` types allowed
- **Unused vars:** `_` prefix to suppress (`argsIgnorePattern: "^_"`)
- **Imports:** Path alias `@/` → `src/`. Use `@/hooks/useSystem` not relative paths.
  Order: external packages → `@/...` internal → relative → types
- **Naming:** files `kebab-case.ts` / `PascalCase.tsx`, components `PascalCase`,
  hooks `useCamelCase`, functions/vars `camelCase`, constants `SCREAMING_SNAKE_CASE`,
  types/interfaces `PascalCase`
- **State:** `@tanstack/react-query` for server state, `zustand` for client state
- **API layer:** Hooks in `src/hooks/use*.ts` → API functions in `src/lib/api/*.ts`
  → shared `apiClient` (axios) from `src/lib/api/client.ts`
- **Components:** shadcn/ui (Radix primitives) + TailwindCSS in `src/components/ui/`
- **Mutation + polling pattern:** When a mutation triggers an async backend process whose status is tracked by a polling `refetchInterval` hook, the mutation's `onSuccess` MUST use `await queryClient.refetchQueries({ queryKey: ... })` (not `invalidateQueries`) for the query key that the polling hook reads. This ensures the fresh transitional status (e.g., "pending", "deploying") is in cache before the interval evaluator decides whether to poll. `invalidateQueries` is fine for other keys that don't feed polling hooks.

---

## Testing Conventions

### Backend Tests

- **Naming:** `test_{unit}_{condition}_{expectedResult}` (e.g. `test_build_failsWhenSchemeNotFound`)
- **Structure:** Arrange–Act–Assert. One behavior per test.
- **Markers:** `@pytest.mark.unit`, `@pytest.mark.component`, `@pytest.mark.full`
- **Unit** (`tests/unit/`): No DB. Pure functions, validators, schemas.
- **Component** (`tests/component/`): Service + in-memory DB. Use `tests/factories.py`.
- **Contract** (`tests/contract/`): Verify response shapes match Pydantic models.

### Frontend Tests

- **Stack:** Vitest + @testing-library/react + MSW 2.x for API mocking
- **Location:** Co-located as `__tests__/*.test.ts` next to source
- **CT-012 pattern (MANDATORY for hook tests):**
  1. Read the backend route file for the real response shape
  2. Read the Pydantic schema (check `backend/schemas/` AND inline in routes)
  3. MSW handlers must return the REAL response shape (not made-up data)
  4. Capture `request.json()` in MSW handlers and assert payload matches backend schema
- **QueryClient wrapper:** Every hook test needs `createWrapper()` with `retry: false, gcTime: 0`

---

## Key Gotchas

- **`response_model` silently drops fields** — Pydantic strips anything not in the declared schema, even if the route returns it. When adding a field to a response, update the schema.
- **Schemas live in TWO places** — always check both `backend/schemas/*.py` AND inline definitions in `backend/routes/*.py`.
- **K8s API returns `null`, not missing keys** — defensively use `(spec.get("ports") or [])` rather than truthy chaining.
- **OpenAPI + generated TS types must stay in sync** — run `make openapi-types` after any route/schema change; `make openapi-types-check` fails CI otherwise.
- **MCP body vs. query drift** — backend routes may require query params where the MCP server sends JSON body. Read the route signature before writing MCP wiring.
- **Docs are generated where they can drift** — `docs/API_REFERENCE.md` comes
  from `backend/openapi.json` via `scripts/gen-api-reference.py`; edit the code,
  then `make api-docs`. `make api-docs-check` fails CI otherwise.
- **A shortcut or nav entry can outlive its route** — `NAV_SHORTCUTS` in
  `hooks/useKeyboardShortcuts.ts` is checked against `router.tsx` by test. Nine
  shortcuts once pointed at deleted pages while the help modal advertised them.
- **`./bnkscope up` is not `docker compose up`** — see *Running it* above.
- **`invalidateQueries` + polling `refetchInterval` race condition** — When a mutation triggers an async backend process (deploy, discover, flash, etc.) and a polling hook uses a data-dependent `refetchInterval`, using `invalidateQueries` in `onSuccess` creates a race: the interval evaluator fires on stale cached data (old terminal status) and returns `false`, so polling never starts. Fix: use `await queryClient.refetchQueries()` for the specific key that feeds the polling hook. `invalidateQueries` is fine for non-polling queries.

---

## Git Workflow

- **`main` is the only long-lived branch.** It is where work lands and what CI
  builds on every push; `origin` carries nothing else. There is no `staging` —
  the `staging → main` promotion path went with bnk-forge's release process.
- Small changes go straight onto `main`. Anything worth reviewing as a unit
  gets a short-lived local branch — `feat/<topic>`, `agent/<topic>` — merged
  back into `main` once it is green. Never force-push `main`.
- **Commit subjects are prose, in the imperative**: "Retire the tunnel's port",
  not `fix: retire tunnel port`. Say what changes for the reader and leave the
  evidence for the body. Conventional-commit prefixes are not used here.
- **Regenerate what is generated, in the same commit as the code.**
  `backend/openapi.json`, the frontend types and `docs/API_REFERENCE.md` are
  built from the routes (`make openapi-types`, `make api-docs`), and
  `make quick-check` fails on drift. The hand-written docs — TESTING.md,
  USER_GUIDE.md, this file — are yours to keep current.

```bash
make quick-check           # before every commit (~15s)
make pre-push              # before every push (~90s) — mirrors CI
make push                  # pre-push + git push + watch CI status
```
