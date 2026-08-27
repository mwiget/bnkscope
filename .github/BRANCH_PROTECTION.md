# Branch Protection Setup

## Required GitHub Settings

Go to: **Settings → Branches → Branch protection rules**

### Protect `main`

`main` is the only long-lived branch — there is no second rule to add.

| Setting | Value |
|---------|-------|
| Branch name pattern | `main` |
| Require a pull request before merging | ✅ |
| Required approvals | 1 (adjust as needed) |
| Require status checks to pass before merging | ✅ |
| **Required status checks** | **`CI Gate`** |
| Require branches to be up to date | ✅ |
| Require conversation resolution | ✅ |
| Do not allow bypassing | ✅ (optional) |

### How to configure required status checks

1. Go to **Settings → Branches → Add rule**
2. Enter branch name pattern
3. Check "Require status checks to pass before merging"
4. In the search box, type `CI Gate` — this is the job name from `ci.yml`
5. Select it as required
6. Save

> **Important:** The `CI Gate` job won't appear in the search until the workflow
> has run at least once. Push a commit to trigger CI first, then configure protection.

## Status checks

`CI Gate` aggregates every job below and is the **only** check you need to
require. It treats `skipped` as acceptable — the path filter decided that job
was irrelevant to the diff — and fails on `failure` or `cancelled`.

| Job name (as it appears in GitHub) | Runs |
|---|---|
| `CI Gate` | the aggregate — **require this one** |
| `Detect Changes` | `dorny/paths-filter`, decides which jobs run |
| `Lint` | `make lint-backend` (ruff), `make lint-frontend` (eslint), `make shellcheck` |
| `TypeCheck · Backend (mypy)` | `make typecheck-backend`, plus `make openapi-check` and `make api-docs-check` freshness gates |
| `TypeCheck · Frontend (tsc)` | `make typecheck-frontend` |
| `Tests · Backend` | `make test-backend` |
| `Tests · Frontend` | `make test-frontend`, `make build-frontend-check` |
| `MCP Server Tests (advisory)` | `make test-mcp` — **advisory**, not in the gate's `needs` |
| `Security Audit` | `make security-audit` (pip-audit + npm audit) |
| `Docker Build + Scan` | builds all three images, asserts `VERSION` is baked in, checks image sizes, Trivy scan (CRITICAL gate, HIGH reported) |

## Makefile is the source of truth

All lint/test/build commands live in `Makefile` targets. The CI YAML only does
checkout, runtime setup (setup-python / setup-node with caching), and
`make <target>`.

This means **`make pre-push` locally ≡ the CI pipeline** — if pre-push passes,
CI passes.

### Key Makefile targets

| Target | Description |
|--------|-------------|
| `make quick-check` | Fast ~15s: lint + mypy + openapi types |
| `make pre-push` | Full ~90s parallel: quick-check + all test suites |
| `make test-backend` | Backend pytest (unit + component + contract + integration) |
| `make test-frontend` | Vitest |
| `make test-mcp` | MCP server tests (advisory in CI) |
| `make security-audit` | pip-audit + npm audit |
| `make docker-check` | Docker build + size threshold verification |

## CI triggers

| Event | Branches | Notes |
|-------|----------|-------|
| Pull Request | `main` | The merge gate |
| Push | `main` | Post-merge validation |
| Manual | — | Release — the only way to cut one |

### Path-based change detection

CI uses `dorny/paths-filter` to skip irrelevant jobs. The filters, verbatim from
`ci.yml`:

| Filter | Paths |
|--------|-------|
| `backend` | `backend/**`, `requirements*.txt`, `openapi.json` |
| `frontend` | `frontend-v2/**` |
| `mcp` | `mcp-server/**` |
| `docker` | `backend/Dockerfile`, `frontend-v2/Dockerfile`, `docker-compose*.yml` |
| `scripts` | `scripts/**` |
| `ci` | `.github/workflows/**`, `Makefile` |

## Workflow files

| File | Purpose | Trigger |
|------|---------|---------|
| `.github/workflows/ci.yml` | All jobs + `CI Gate` | Push, PR |
| `.github/workflows/release.yml` | Release pipeline | `workflow_dispatch` **only** |

## Release process

> **Releases are dispatched, never automatic.** Merging to `main` does not cut
> one. This changed on 2026-08-27 — the workflow used to fire on every non-docs
> push to `main`, which is how bnk-forge shipped. See
> [D-038](../docs/adr/D-038-releases-are-dispatched-not-pushed.md).

1. Push your work to `main` and let `CI Gate` go green.
2. **Actions → Release → Run workflow.**
3. Choose the bump (`patch`/`minor`/`major`) and enter release notes.

Release will then:

- ✅ Verify CI passed **for that exact commit SHA**
- ✅ Apply the bump you chose to the `VERSION` file
- ✅ Update `CHANGELOG.md` (inserted after its first `---`, so leave that separator alone)
- ✅ Commit, tag `vX.Y.Z`, push
- ✅ Create a GitHub Release
- ✅ Publish images to GHCR

### It must be a commit CI ran on

Preflight matches its CI run by SHA, so you cannot release on top of a
**docs-only commit** — `ci.yml` skips those via `paths-ignore`, that SHA has no
CI run, and none is coming. Preflight says so after five minutes rather than
polling the full 45-minute timeout. Push a code commit, or re-run CI for that
SHA, then dispatch again.
