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
| Push | `main` | Post-merge validation — and Release, unless the push is docs-only |
| Manual | — | `workflow_dispatch` on Release, for an explicit bump/notes override |

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
| `.github/workflows/release.yml` | Release pipeline | **Push to `main`** (non-docs), or manual |

## Release process

> **Releases are automatic.** Every push to `main` that touches something other
> than docs runs Release alongside CI. There is no button to press and no
> confirmation step — merging is the release. The `paths-ignore` list decides
> what counts as docs, and it **must stay identical to `ci.yml`'s**: Release's
> preflight matches its CI run by SHA, so a push that releases without a
> matching CI run just times out waiting for one.
>
> This bites on a first push. Recreating the repository on 2026-08-27 pushed all
> 24 commits at once, which fired Release; it was cancelled before it cut a tag.
> If you are importing history, expect it and cancel the run.

On a normal push to `main`, Release will:

- ✅ Verify CI has passed for the same SHA
- ✅ Derive the bump from conventional commits since the last final `vX.Y.Z` tag
      (`feat!`/`BREAKING CHANGE` → major, `feat` → minor, anything else → patch)
- ✅ Bump the `VERSION` file
- ✅ Update `CHANGELOG.md` (inserted after its first `---`)
- ✅ Commit `release: vX.Y.Z [skip ci]`, tag, push
- ✅ Create a GitHub Release

The commit it pushes starts with `release: ` and carries `[skip ci]`, which is
what stops it from triggering itself.

### Manual override

**Actions → Release → Run workflow** takes an explicit bump type and release
notes, for when the derived version is not what you want.
