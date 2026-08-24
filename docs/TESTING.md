# bnkscope — Testing Guide

Complete guide to the test infrastructure, patterns, and how to run tests.

> **Last verified: 2026-03-31.** Test counts and coverage evolve frequently; prefer Make targets and CI over hard-coded totals.

---

## Table of Contents

- [Quick Reference](#quick-reference)
- [Test Suite Overview](#test-suite-overview)
- [Running Tests](#running-tests)
- [Backend Tests](#backend-tests)
- [Frontend Tests](#frontend-tests)
- [CI Pipeline](#ci-pipeline)
- [Writing New Tests](#writing-new-tests)
- [Contract Testing (CT-012)](#contract-testing-ct-012)
- [Common Gotchas](#common-gotchas)
- [Keeping This Document Current](#keeping-this-document-current)

---

## Quick Reference

```bash
# Run everything (~90s)
make pre-push

# Quick check before commits (~15s)
make quick-check

# Individual suites
make test-backend-unit       # Backend unit tests only
make test-backend-component  # Backend component tests (with DB)
make test-frontend           # Frontend vitest
make test                    # All suites sequentially

# Coverage
make coverage                # Backend + frontend coverage reports
```

---

## Test Suite Overview

| Suite | Tool | Scope | What It Tests |
|-------|------|-------|---------------|
| Backend Unit | pytest | `backend/tests/unit/` | Pure logic: schemas, services, parsers, validators |
| Backend Component | pytest | `backend/tests/component/` | Services with real SQLite DB, mocked externals |
| Backend Integration | pytest | `backend/tests/integration/` | Full HTTP via FastAPI TestClient |
| Backend Legacy | pytest | flat `backend/tests/test_*.py` | Older tests retained outside the newer split layout |
| Backend Contract | pytest | `backend/tests/contract/` | Golden response-shape verification for Tier-1 APIs |
| Frontend | vitest | `frontend-v2/src/**/*.{test,spec}.{ts,tsx}` | Hooks, components, pages with MSW |
| MCP | pytest | `mcp-server/` | The MCP tool server's own suite |

---

## Running Tests

### Makefile Targets

| Target | Duration | What It Does |
|--------|----------|--------------|
| `make quick-check` | ~15s | Lint (ruff + eslint) + mypy + OpenAPI types freshness |
| `make pre-push` | ~90s | quick-check + 9 parallel test suites + tsc + frontend build |
| `make push` | ~90s + push | pre-push + git push + watch CI |
| `make test` | ~3m | All suites sequentially (lint + all backend + frontend + proxy + operator + db) |
| `make test-backend` | ~60s | All backend pytest tests |
| `make test-backend-unit` | ~15s | `pytest backend/tests/unit/` |
| `make test-backend-component` | ~30s | `pytest backend/tests/component/` |
| `make test-backend-legacy` | ~15s | Legacy tests at `backend/tests/` root |
| `make test-frontend` | ~30s | `npm test -- --run` (vitest) |
| `make test-mcp` | ~10s | The MCP server's own suite |
| `make test-integration` | ~4m | Integration tests, default marker set (everything except `full`) |
| `make test-integration-full` | ~5m | Full-stack integration (`-m full`) |
| `make coverage` | ~2m | Coverage reports for backend + frontend |
| `make lint` | ~10s | Lint backend (ruff) + frontend (eslint) |
| `make typecheck-backend` | ~15s | mypy on `core/` and `schemas/` |
| `make typecheck-frontend` | ~15s | tsc --noEmit |

### Git Hooks

Install with `make install-hooks`:

- **pre-commit** (~5-10s) — Runs ruff/eslint only on changed files
- **pre-push** (~2-3m) — Delegates to `make pre-push`

### Mandatory Workflow

```
Before every commit:   make quick-check     (~15s)
Before every push:     make pre-push        (~90s)
```

**CI is for validation, not discovery.** If it fails in CI, it should have been caught locally first.

---

## Backend Tests

### Directory Structure

```
backend/tests/
├── conftest.py              # Root fixtures: DB engine, client, auth, factories
├── factories.py             # Model factories (User, Project, Module, Task, etc.)
├── mocks/                   # Mock modules
│   ├── kubernetes_mock.py
│   ├── cache_mock.py
│   └── subprocess_mock.py
├── unit/                    # 52 files — pure logic, no DB
│   ├── conftest.py          # temp_encryption_key, mock_settings
│   ├── test_schemas_*.py    # Pydantic schema validation
│   ├── test_core_*.py       # Encryption, config, errors
│   ├── test_bnk_*.py        # BNK health, topology, backends
│   └── test_scanner_*.py    # Cluster scanner components
├── component/               # 24 files — services + real SQLite DB
│   └── test_*_service.py    # Service-level tests
├── integration/             # 14 files — full HTTP via TestClient
│   ├── conftest_full.py     # Live Docker stack fixtures
│   └── test_routes_*.py     # Route-level HTTP tests
├── contract/                # 5 files — golden response shapes
├── migrations/              # 1 file
└── (3 legacy test files)    # Flat test_*.py at root level
```

Roughly 1,770 backend tests and 1,440 frontend tests.

### Configuration

In `backend/pyproject.toml`:

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests", "backend/tests"]
pythonpath = ["backend"]
markers = ["slow", "integration", "unit", "component", "security", "fast", "full"]
addopts = "-v --tb=short -m 'not full'"
```

- Tests marked `full` are excluded by default (require running Docker stack)
- Coverage threshold: 50% (`fail_under = 50`)

### Fixture Architecture

**Root `conftest.py`** — shared across all test categories:

| Fixture | Scope | Description |
|---------|-------|-------------|
| `engine` | session | SQLite in-memory with `StaticPool`, foreign keys ON |
| `db` | function | Transactional session (rolls back after each test) |
| `client` | function | FastAPI `TestClient` with the DB overridden |
| `db` | function | A real SQLite session |
| `engine` | session | The test engine |
| `mock_cache` | function | `MockCacheService` in place of a cache |
| `make_k` | function | Factory: create a K8s cluster |
| `make_proxy_deployment` | function | Factory: create a proxy deployment |
| `sample_user` / `sample_operator_user` / `sample_viewer_user` | function | Pre-created users |
| `admin_headers` / `operator_headers` / `viewer_headers` | function | **All return `{}`** — see below |

> **The `*_headers` fixtures are no-ops.** They returned JWT headers before
> Phase 3 removed authentication, and were left returning `{}` so that ~1600
> tests did not all need editing. A test that passes with `admin_headers` proves
> nothing about access control — there is none. Avoid them in new tests.

**Unit conftest** adds: `temp_encryption_key`, `mock_settings`.

Component and integration conftests carry no extra fixtures of their own — the
`mock_celery` / `mock_celery_dispatch` pair was removed once Celery was gone and
nothing referenced them.

### Test Patterns

**Unit tests** — No DB, no mocks (or minimal):
```python
class TestProjectSchema:
    def test_valid_project_create(self):
        data = ProjectCreate(name="test", project_type="aws", region="us-west-2")
        assert data.name == "test"
    
    def test_invalid_name_raises(self):
        with pytest.raises(ValidationError):
            ProjectCreate(name="", project_type="aws")
```

**Component tests** — Real DB, mocked externals:
```python
class TestProjectService:
    def test_create_project(self, db, sample_user):
        project = ProjectService.create(db, name="test", owner_id=sample_user.id)
        assert project.name == "test"
        assert project.user_id == sample_user.id
```

**Integration tests** — Full HTTP:
```python
class TestProjectRoutes:
    def test_list_projects(self, client, admin_headers, sample_project):
        response = client.get("/api/projects", headers=admin_headers)
        assert response.status_code == 200
        data = response.json()
        assert len(data["projects"]) >= 1
```

---

## Frontend Tests

### Directory Structure

```
frontend-v2/src/
├── test/                          # Test infrastructure
│   ├── setup.ts                   # MSW server, jest-dom, browser mocks
│   ├── test-utils.tsx             # Custom render with providers
│   ├── test-fixtures.ts           # Shared mock data
│   └── mocks/
│       ├── server.ts              # MSW setupServer
│       └── handlers.ts            # 962-line default API handlers
├── hooks/__tests__/               # 35 hook test files
├── hooks/k8s/__tests__/           # 6 K8s hook tests
├── lib/__tests__/                 # 15 utility tests
├── lib/api/__tests__/             # 17 API client tests
├── schemas/__tests__/             # Schema validation tests
├── stores/__tests__/              # Store tests
├── components/**/__tests__/       # ~132 component tests
└── pages/**/__tests__/            # ~25 page tests
```

### Configuration

In `frontend-v2/vitest.config.ts`:

```typescript
export default defineConfig({
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: './src/test/setup.ts',
    include: ['src/**/*.{test,spec}.{ts,tsx}'],
    coverage: {
      provider: 'v8',
      thresholds: { statements: 25, branches: 15, functions: 15, lines: 25 }
    }
  }
});
```

### Test Infrastructure

**`setup.ts`** — Runs before all tests:
- Imports `@testing-library/jest-dom` matchers
- Starts MSW `server.listen()` before all
- Resets handlers + cleanup after each
- Mocks: `matchMedia`, `ResizeObserver`, `IntersectionObserver`

**`test-utils.tsx`** — Custom `render()`:
```typescript
// Wraps component with QueryClientProvider + MemoryRouter + ThemeProvider
// Intentionally omits NotificationProvider/WebSocketProvider
render(<Component />, { initialRoute: '/some-path' });
```

**`handlers.ts`** — 962 lines of MSW default handlers covering all major API endpoints.

**`test-fixtures.ts`** — Single source of truth for mock data objects.

### Test Patterns

**Hook tests** (`.test.ts`):
```typescript
describe('useProjects', () => {
  it('should fetch projects', async () => {
    const { result } = renderHook(() => useProjects(), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toHaveLength(2);
  });
});
```

**Component tests** (`.test.tsx`):
```typescript
describe('ProjectCard', () => {
  it('renders project name and status', () => {
    render(<ProjectCard project={mockProject} />);
    expect(screen.getByText('My Project')).toBeInTheDocument();
    expect(screen.getByText('Active')).toBeInTheDocument();
  });

  it('calls onDelete when delete button clicked', async () => {
    const onDelete = vi.fn();
    render(<ProjectCard project={mockProject} onDelete={onDelete} />);
    await userEvent.click(screen.getByRole('button', { name: /delete/i }));
    expect(onDelete).toHaveBeenCalledWith(mockProject.id);
  });
});
```

**Page integration tests** — Full page renders with routing and MSW.

---

## CI Pipeline

`.github/workflows/ci.yml` — 9 jobs behind a `changes` filter, gated by
`ci-gate`:

| Job | What it runs |
|---|---|
| `changes` | `dorny/paths-filter` — decides which of the rest run |
| `lint` | ruff (backend) + eslint (frontend) |
| `typecheck-backend` | mypy, then `make openapi-check` and `make api-docs-check` |
| `typecheck-frontend` | tsc |
| `backend-tests` | pytest: unit, component, contract, integration |
| `frontend-tests` | vitest |
| `mcp-tests` | the MCP server's own suite |
| `security-audit` | dependency and image scanning |
| `docker-build` | builds both images, enforces size thresholds, Trivy scan |
| `ci-gate` | the required check — fails if any needed job did |

Path filtering means jobs for unchanged areas are skipped, so `ci-gate` exists to
give branch protection one status to require regardless of what ran.

**Skipped entirely** when only these paths change: `docs/`, `*.md`, `.gitignore`.

Phase 8 cut this from 25 jobs to 10 by removing the suites for subsystems that
no longer exist.

---

## Writing New Tests

### Backend: Adding a New Route Test

1. Identify the route file.
2. Write the test in the appropriate directory:
   - `unit/` for schema validation
   - `component/` for service logic
   - `integration/` for HTTP endpoint behaviour
3. Use existing fixtures — `client`, `db`, and the factories in
   `backend/tests/factories.py`.
4. Follow the naming convention: `test_{unit}_{condition}_{expected}`

> **`admin_headers` and `operator_headers` still exist, and both return `{}`.**
> They were left as no-ops when authentication was removed in Phase 3 so that
> ~1600 tests did not all have to be edited. Do not read them as evidence that
> a route is protected — nothing is. Prefer not to use them in new tests.

```python
# backend/tests/integration/test_routes_new_feature.py
class TestNewFeatureRoutes:
    def test_create_rejects_a_blank_name(self, client):
        response = client.post("/api/new-feature", json={"name": ""})
        assert response.status_code == 422

    def test_create_returns_201(self, client, admin_headers):
        response = client.post(
            "/api/new-feature",
            json={"name": "test"},
            headers=admin_headers
        )
        assert response.status_code == 201
        assert response.json()["name"] == "test"
```

### Frontend: Adding a Hook Test

1. **Read the backend route first** — understand the request/response shape
2. Create `__tests__/useNewFeature.test.ts` next to the hook
3. Set up MSW handler with the real response shape
4. Use the CT-012 contract testing pattern (see below)

```typescript
// src/hooks/__tests__/useNewFeature.test.ts
import { renderHook, waitFor } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { server } from '@/test/mocks/server';
import { createWrapper } from '@/test/test-utils';

describe('useNewFeature', () => {
  it('should fetch features', async () => {
    server.use(
      http.get('*/api/new-feature', () =>
        HttpResponse.json({ features: [{ id: 1, name: 'test' }] })
      )
    );
    const { result } = renderHook(() => useNewFeature(), {
      wrapper: createWrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data.features).toHaveLength(1);
  });
});
```

### Frontend: Adding a Component Test

```typescript
// src/components/feature/__tests__/FeatureCard.test.tsx
import { render, screen } from '@/test/test-utils';
import { FeatureCard } from '../FeatureCard';

describe('FeatureCard', () => {
  it('renders feature name', () => {
    render(<FeatureCard feature={{ id: 1, name: 'Test' }} />);
    expect(screen.getByText('Test')).toBeInTheDocument();
  });

  it('shows loading state', () => {
    render(<FeatureCard feature={null} isLoading />);
    expect(screen.getByRole('progressbar')).toBeInTheDocument();
  });
});
```

---

## Contract Testing (CT-012)

**The most important testing pattern in this project.**

Every frontend hook test that calls an API mutation **MUST** verify the request payload shape matches the backend Pydantic schema. This prevents the most common class of bugs: frontend sends wrong data, MSW returns canned success, test passes, production breaks.

### The Pattern

```typescript
describe('useCreateProject', () => {
  it('sends correct payload shape', async () => {
    // 1. Capture the request body
    let capturedBody: Record<string, unknown> | null = null;
    server.use(
      http.post('*/api/projects', async ({ request }) => {
        capturedBody = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({
          // 2. Return the REAL backend response shape
          project: { id: 1, name: capturedBody?.name, status: 'active' },
          message: 'Project created',
        });
      })
    );

    // 3. Call the mutation
    const { result } = renderHook(() => useCreateProject(), { wrapper });
    await act(async () => {
      result.current.mutate({ name: 'Test', project_type: 'aws', region: 'us-west-2' });
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    // 4. Assert payload matches backend Pydantic schema
    expect(capturedBody).toMatchObject({
      name: 'Test',
      project_type: 'aws',
      region: 'us-west-2',
    });
    // 5. Assert no accidental wrapping
    expect(capturedBody).not.toHaveProperty('request');
    expect(capturedBody).not.toHaveProperty('data');
  });
});
```

### Before Writing ANY Hook Test

1. Find the backend route file + line number
2. Read the Pydantic request model (check both `backend/schemas/` and inline in routes)
3. Read the actual return dict shape from the route handler
4. Write MSW handlers that return the REAL response shape
5. Capture `request.json()` in MSW and assert payload matches backend schema

---

## Common Gotchas

### Backend

- **SQLite vs PostgreSQL differences**: Tests use SQLite in-memory. Some PostgreSQL features (JSON operators, `ILIKE`, array columns) need special handling. The `conftest.py` engine uses `StaticPool` for performance.

- **ServiceRegistry resets between tests**: The root `conftest.py` resets `ServiceRegistry` after each test to prevent state leakage between tests.

- **`full` marker tests require Docker**: Tests marked `@pytest.mark.full` need the full Docker Compose stack running. They use `requests.Session` (not `TestClient`).

- **Background work is synchronous in tests**: there is no broker and no worker. `core/background.py` runs on a thread pool; prefer `run_sync()` in tests.

- **Factory sequence counters**: `factories.py` uses `_counters` dict for unique names. The counter persists across tests in the same session.

### Frontend

- **MSW handlers reset after each test**: `setup.ts` calls `server.resetHandlers()` in `afterEach`. Per-test overrides via `server.use()` are temporary.

- **Radix focus-scope flaky in CI**: `dispatchEvent` TypeError from `@radix-ui/react-focus-scope` when dialogs unmount. Fix: `vi.useFakeTimers({ shouldAdvanceTime: true })` + `vi.runOnlyPendingTimers()` in `afterEach`.

- **Custom render omits side-effect providers**: `test-utils.tsx` intentionally omits `NotificationProvider` and `WebSocketProvider` to avoid side effects in tests.

- **`waitFor` timeout**: Default timeout is 1000ms. For slow async operations, increase: `waitFor(() => ..., { timeout: 5000 })`.

### General

- **Dev environment is a liar**: 4,200 tests pass in dev but the production container might not even start. Dev compose mounts tools (git, tofu, helm) that the slim production image doesn't have. Tests never catch import errors or container startup failures. The ONLY proof is production site loading.

- **Lazy imports for CLI deps**: The slim API Docker target has no git/tofu. Services that import these at module level crash the API on startup. Use lazy imports inside functions.

---

## Keeping This Document Current

This document should be updated when:

- A new test directory or category is added
- Test configuration (pyproject.toml, vitest.config.ts) changes materially
- The test count crosses a major milestone (e.g., 5,000 tests)
- New testing patterns or conventions are established
- CI pipeline structure changes

> **Agent rule:** When adding new test infrastructure, patterns, or significantly changing test counts, update this file in the same commit.

### Verifying Test Counts

```bash
# Backend test files
find backend/tests -name "test_*.py" | wc -l

# Frontend test files
find frontend-v2/src -name "*.test.ts" -o -name "*.test.tsx" | wc -l

# Run counts
make test-backend 2>&1 | tail -1     # "X passed" line
npm test -- --run 2>&1 | tail -5     # vitest summary
```
