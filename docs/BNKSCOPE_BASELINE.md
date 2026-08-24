# bnkscope Phase 0 — measured baseline

**Date:** 2026-08-23 · **Branch:** `feat/bnkscope` · **Frozen at:** `staging` @
`4a52ed4` ("Version derivation and release notes must read commit bodies (→ 4.0.0) (#178)")

Every claim in [`BNKSCOPE_PLAN.md`](BNKSCOPE_PLAN.md) about build time, UI
surface, and code mass is measured here, on this host, at this commit. Later
phases report against these numbers — not against estimates.

**Host:** 28 cores, 188 GB RAM, Docker 29.7.2 / buildx 0.36.1, single-arch
(`linux/amd64`) local builds.

**Freeze:** no further merges from `staging` into `feat/bnkscope` after
`4a52ed4`. Divergence is intentional — the two branches never merge again
(plan §6.5).

---

## 1. Code mass

Tracked files only (`git ls-files`); the untracked `t193/` scratch copy is
excluded.

| | |
|---|---:|
| Tracked files | 2,440 |
| Code (`.py .ts .tsx .go .sh .tf`) | **622,964 LOC** |
| Markdown | 48,563 LOC |
| Git history | 68 commits (squashed public mirror — a squash-export loses little) |

Per component:

| Component | LOC |
|---|---:|
| `backend/` | 345,310 |
| `frontend-v2/` | 240,832 |
| `scripts/` | 12,434 |
| `mcp-server/` | 9,155 |
| `bnk-operator/` | 6,659 |
| `tests/` | 5,460 |
| `bin/` | 1,072 |
| `vm-bnk-forge/` | 302 |

### Bucketed (`./scripts/loc-report.py`)

Snapshot committed at `docs/bnkscope/loc-baseline.json`. Every phase runs
`./scripts/loc-report.py --compare docs/bnkscope/loc-baseline.json`.

| | LOC | share |
|---|---:|---:|
| **KEEP** (k8s core, BNK/TMM, observability, system) | 47,449 | 8% |
| **RM** (pipeline, fleets, operators, auth, benchmarks, DPU, …) | 360,141 | 61% |
| **OTHER** — shared UI kit, `lib/`, generated types | 187,405 | 31% |
| Total scanned (`backend/`, `frontend-v2/src/`, `mcp-server/`) | **594,995** | |

---

## 2. Structural counters

| Counter | Baseline |
|---|---:|
| Backend Python source files | 617 |
| Backend test files | 466 |
| Backend test functions | **9,068** |
| Frontend `.ts/.tsx` files | 846 |
| Frontend test files | 292 |
| Frontend `it()`/`test()` cases | **2,568** |
| MCP test functions | 118 |
| Alembic migrations | 152 |
| DB tables | 80 |
| `app.include_router()` calls | 67 |
| OpenAPI paths | 533 |
| `backend/openapi.json` | 1.66 MB |
| `api-generated.ts` | 43,368 lines |
| Python direct deps | 32 |
| npm deps (prod / dev) | 46 / 25 |
| docker-compose services | 30 |
| docker-compose named volumes | 14 |
| Compose files | 6 |
| Dockerfiles | 8 |
| `Makefile` | 62,447 bytes |
| GitHub workflows | 6 |
| CI jobs (ci.yml) | 25 definitions, 29 executed |
| `docs/*.md` | 141 files |
| ADRs | 37 |

---

## 3. CI wall-clock

Run [`32586328421`](https://github.com/f5devcentral/bnk-forge/actions/runs/32586328421)
(staging, all-green, 2026-08-22):

**27m 12s wall-clock · 46m 14s of billed compute across 29 jobs.**

The ten most expensive jobs — all but one belong to subsystems bnkscope deletes:

| Job | Time | Survives? |
|---|---:|---|
| P3 · Integration Tests · Backend | 787s | shrinks hard |
| P4 · Docker Build + Scan | 329s | 7 images → 2 |
| P2 · Component Tests · Backend | 257s | shrinks hard |
| P1 · Unit Tests · Backend | 234s | shrinks hard |
| P1 · Unit Tests · Frontend | 230s | shrinks hard |
| P2 · Legacy Tests · Backend | 143s | deleted |
| P2 · Migration Upgrade From Released Version (Postgres) | 101s | **deleted** (SQLite) |
| P2 · Build · Frontend | 90s | shrinks |
| P1 · Contract Tests | 80s | shrinks |
| P2 · Migration Round-Trip (Postgres) | 66s | **deleted** (SQLite) |

Three jobs (268s combined) exist solely to exercise 152 Alembic migrations
against Postgres. Phase 4 deletes all three outright.

---

## 4. Local build — cold (`--no-cache`, single-arch)

`docker compose build --no-cache <svc>`, timed per service.

**Method caveat, stated so later phases compare like with like:** `--no-cache`
invalidates every *layer*, but BuildKit `--mount=type=cache` mounts survive it —
`backend/Dockerfile:79,363` (pip) and `frontend-v2/Dockerfile:19` (npm). So
package *downloads* are warm. This is "developer rebuilds from scratch on a
machine they've built on before", not a CI-runner cold start. Every later phase
uses the identical command, so the deltas are valid.

| Service | Cold build | Fate |
|---|---:|---|
| `backend` (api) | 106s | keep |
| `forge-agent` | 83s | **delete** (Phase 2) |
| `celery-worker` | 49s | **delete** (Phase 4) |
| `frontend` | 45s | keep |
| `celery-beat` | 40s | **delete** (Phase 4) |
| `mcp` | 13s | keep (read-only subset) |
| `proxy` | 4s | optional |
| **Total** | **340s (5m 40s)** | → 2 images |

`forge-agent` is the second-slowest image in the stack and exists only for
benchmarks: `aiperf` pulls in `crick`, a C extension that compiles from source
under `build-essential`, which is installed and purged in the same layer.

Build context is 68 MB, of which 35 MB is the untracked `t193/` scratch
directory in the repo root — not in `.dockerignore`. Not a repo defect (it is
local scratch), but it does make these numbers slightly pessimistic.

## 5. Local build — warm rebuild (one source file changed)

The number that actually governs the daily edit loop. A comment line is appended
to `backend/main.py` / `frontend-v2/src/main.tsx`, the service is rebuilt, then
the file is restored with `git checkout --`.

| Service | Warm rebuild |
|---|---:|
| `frontend` | **37s** (`tsc` + `vite build` over 846 files) |
| `celery-worker` | 14s |
| `backend` (api) | 6s |

> `touch`-ing the file measures nothing — BuildKit hashes content, not mtime,
> and returns a 1–2s no-op. The first run of this script made that mistake; the
> script now appends a language-appropriate comment instead.

The frontend's 37s is almost entirely `tsc` + `vite` chewing through 846 files
and a 43,368-line generated types file. It is the slowest thing between an edit
and a running container, and Phase 6 targets it directly.

## 6. Image sizes

| Image | Size | Fate |
|---|---:|---|
| `bnk-forge-agent` | 1.61 GB | **delete** |
| `bnk-forge-worker` | 1.46 GB | **delete** |
| `bnk-forge-api` | 829 MB | keep (shrinks — no tofu/aws-cli/helm) |
| `bnk-forge-beat` | 664 MB | **delete** |
| `bnk-forge-mcp` | 268 MB | keep (subset) |
| `bnk-forge-frontend` | 138 MB | keep |
| `bnk-forge-proxy` | 93.9 MB | optional |
| **Total** | **5.06 GB** | → ~1.1 GB projected |

(Sum of reported sizes; shared base layers mean on-disk usage is lower.)

## 7. Frontend bundle

`dist/` extracted from `bnk-forge-frontend:latest`: **18 MB on disk, 204 JS
chunks, 16.64 MB JS + 0.22 MB CSS.**

### Initial load (entry + `modulepreload` links in `index.html`)

| Chunk | raw | gzip |
|---|---:|---:|
| `vendor-monaco.js` | 3,733 KB | **965 KB** |
| `vendor-ui.js` | 241 KB | 65 KB |
| `vendor-react.js` | 203 KB | 66 KB |
| `index.js` | 164 KB | 44 KB |
| `vendor-monaco.css` | 144 KB | 23 KB |
| `vendor-utils.js` | 112 KB | 40 KB |
| `vendor-forms.js` | 80 KB | 22 KB |
| `index.css` | 71 KB | 13 KB |
| `vendor-query.js` | 42 KB | 13 KB |
| **Total initial load** | **5.09 MB** | **1.33 MB** |

### The Monaco finding

**Monaco is 76% of the initial payload and 71% of the whole `dist/`.**

| | raw |
|---|---:|
| `vendor-monaco.js` (preloaded on *every* page) | 3.73 MB |
| `ts.worker.js` (lazy chunk) | 6.70 MB |
| `css.worker.js` / `html.worker.js` / `json.worker.js` (lazy chunks) | 2.01 MB |
| **Monaco total** | **12.44 MB of 16.64 MB JS** |

Two separate observations, both actionable:

1. **The four language workers (8.71 MB) are dead weight today.**
   `main.tsx` sets `MonacoEnvironment.getWorker()` to return `editor.worker`
   unconditionally — the ts/css/html/json workers are emitted by the
   `import * as monaco from 'monaco-editor'` barrel but never instantiated at
   runtime. They are lazy chunks, so they don't hit initial load, but they are
   half the image.

2. **`vendor-monaco` *is* initial load**, and it exists for four components:
   `YamlEditor`, `ResourceEditDialog`, `ResourceCreateDialog` (all deleted by
   Phase 1 — config editing is a build concern) and **`F5iRuleViewer`, which
   bnkscope keeps.** iRule *viewing* is diagnostic; it does not need an IDE.

   → **Phase 6 task:** swap `F5iRuleViewer` to a read-only syntax highlighter
   and drop `@monaco-editor/react` + `monaco-editor` entirely. Projected initial
   load afterwards: **~1.21 MB raw / ~0.35 MB gz** — a 74% cut, before any of
   the page/route deletions are counted.

`reactflow` + `@dagrejs/dagre` stay: `ResourceTopologyGraph` (keep) uses them.
`DependencyGraphViewer` and `DeploymentPipeline` (delete) are the other users.

---

## 8. Not measured

Stated plainly so no later phase claims an unearned win:

- **Cold `docker compose up` to healthy** — needs a populated `.env`, a seeded
  Postgres volume, and reachable clusters; not reproducible on this host without
  side effects. Phase 4 measures it for both shapes at once.
- **Runtime memory footprint** of the 30-service stack.
- **`pytest` / `vitest` wall-clock locally** — the CI numbers in §3 are the
  comparable figure; local runs need Postgres and Redis.

---

## 9. Reproducing

```bash
./scripts/loc-report.py                                        # bucket table
./scripts/loc-report.py --compare docs/bnkscope/loc-baseline.json
./scripts/bnkscope-baseline-build.sh /tmp/build.tsv            # cold + warm build
gh run view <id> --json jobs -q '.jobs[] | [.name,
  ((.completedAt|fromdate)-(.startedAt|fromdate)|tostring)+"s", .conclusion] | @tsv'
```
