# bnkscope — a troubleshooting/monitoring-only fork of bnk-forge

**Status:** in progress — Phase 0 and Phase 1 landed · **Branch:** `feat/bnkscope`
**Target repo:** `github.com/mwiget/bnkscope` (private) · **Date:** 2026-08-23

> `bnk-forge` grew from "look at my BNK cluster" into a deployment platform:
> OpenTofu pipelines, module catalogs, blueprints, fleets, RBAC, benchmarks, DPU
> provisioning. This plan strips it back to the one job that made it useful in an
> incident — **look at the cluster, understand what's wrong** — and folds in
> [`tmmscope`](../../tmmscope) for real-time TMM telemetry.
>
> Same move `tmmscope` already made once: *"Bundling a full Prometheus + Grafana
> stack into bnk-forge bloated a troubleshooting tool with an observability
> platform."* This applies that reasoning to the rest of the platform.

---

## 1. Target shape

| | bnk-forge today | bnkscope |
|---|---|---|
| Purpose | build + deploy + operate | **observe + diagnose** |
| Deploy target | multi-user server, docker-compose, 30 services | **one laptop, `bnkscope up`** |
| Clusters | fleets, projects, policies, targeting | **flat auto-populated list** |
| Auth | JWT, users, roles, audit trail | **none** (localhost-bound) |
| Mutations | OpenTofu apply/destroy, Helm, promotion | **read-only + narrow break-glass** |
| Telemetry | none (extracted to tmmscope) | **tmmscope embedded** |

Everything that writes infrastructure goes. Everything that reads it stays.

### Progress

| Phase | Status | LOC removed | Running total |
|---|---|---:|---:|
| 0 Baseline | ✅ done | — | 622,964 |
| 1 Pipeline | ✅ done | 255,733 | **367,346** |
| 2 Fleet / operators / benchmarks / DPU | ✅ done | 134,878 | **224,983** |
| 3 Auth + SSH | ✅ done | 18,515 | **185,869** |
| 4 Runtime collapse | ✅ done | 13,745 | **172,124** |
| 5 Cluster autodiscovery | ✅ done | −958 (net **added**) | **173,082** |
| 6 UI reshape | ✅ done | −663 (net **added**) | **173,745** |
| 7 tmmscope | ✅ done | −1,883 (net **added**) | **175,628** |
| 8 Package | ✅ done | 38 | **175,590** |

**419,405 LOC removed — 70.5% of the baseline.** The counter was never the
point after Phase 4; what it measured well was the first three phases, and what
matters now is in the per-phase notes below.

---

## 2. Measured mass (tracked code, `t193/` scratch dir excluded)

```
backend        345,310    frontend-v2    240,832    scripts   12,374
mcp-server       9,155    bnk-operator     6,659    tests      5,460
bin              1,072    vm-bnk-forge       302
                                          ─────────────────────────
                                          TOTAL   ~621,000 LOC
```

Structural counters that drive build time and cognitive load:

| Counter | Today |
|---|---|
| Backend Python source files | 617 |
| Backend test files | 466 |
| Frontend `.ts/.tsx` files | 846 |
| Frontend test files | 292 |
| Alembic migrations | 152 |
| DB tables | 80 |
| FastAPI routers registered in `main.py` | 67 |
| OpenAPI paths | 533 |
| docker-compose services | 30 |
| CI jobs | 25 |
| Generated API types (`api-generated.ts`) | 43,368 lines |

### 2.1 Bucketed by feature area

Every `.py/.ts/.tsx` file under `backend/`, `frontend-v2/src/`, `mcp-server/` was
assigned to exactly one bucket by path (first-match rules). Numbers are ±10% —
the point is the ratio, not the third digit.

| Bucket | src | test | total | Verdict |
|---|---:|---:|---:|---|
| modules / catalog / blueprints / stacks / helm / registry | 60,258 | 42,874 | **103,132** | remove |
| DPU / DPF / bare-metal / BlueField / rshim | 35,326 | 10,765 | **46,091** | remove |
| OpenTofu / execution engine / workspaces / state | 24,750 | 6,958 | **31,708** | remove |
| projects | 19,039 | 10,020 | **29,059** | remove |
| fleet / operators | 15,840 | 10,044 | **25,884** | remove |
| auth / users / audit / credentials / secrets | 11,818 | 11,177 | **22,995** | remove |
| benchmarks | 13,608 | 7,972 | **21,580** | remove |
| discovery / scanner | 12,384 | 7,226 | **19,610** | *mostly* remove (keep the probe) |
| proxy migration / CIS translate | 9,118 | 6,184 | **15,302** | remove |
| snapshots / promotion / runbooks / backup | 6,648 | 4,202 | **10,850** | remove |
| celery tasks / notifications / alerts | 8,801 | 1,858 | **10,659** | remove |
| BNK upgrade / licensing | 5,517 | 3,414 | **8,931** | remove |
| cloud auth / SSH / tunnels / F5 devices / TMOS | 2,756 | 5,977 | **8,733** | remove (SSH tunnel: see §6) |
| drift | 3,287 | 2,320 | **5,607** | remove |
| **k8s core** (resources, clusters, CRDs, topology, pods, exec, logs) | 15,109 | 3,629 | **18,738** | **keep** |
| **BNK / TMM** (health, topology, tmm_debug, qkview, gateways) | 15,506 | 374 | **15,880** | **keep** |
| **system / core / db / utils** | 7,294 | 0 | **7,294** | **keep** |
| **observability / reachability / LLM logs** | 4,752 | 785 | **5,537** | **keep** |
| shared (UI kit, lib, generated types, layout, schemas) | 104,482 | 82,923 | **187,405** | shrinks proportionally |
| | | | **594,995** | |

---

## 3. How much comes out

| | LOC |
|---|---:|
| Unambiguous removals (buckets marked *remove*) | **~362,000** |
| Shared code that dies with them (generated types ~35k of 43k, unused UI kit, `lib/`, layout, their tests) | **~120,000** |
| Keep buckets | ~47,000 |
| Kept slice of shared code | ~30,000 |

**Estimate: ~480,000 LOC removed (≈ 78% of the tracked codebase) before a single
line of tmmscope is added.** tmmscope adds back **~4,200 lines of Go** (2 binaries
+ a webhook + dashboard assets).

Landing zone: **~90,000–110,000 LOC**, ~150 backend source files, ~200 frontend
files, **one** initial migration instead of 152, ~15 DB tables instead of 80.

Not counted above, but also going: ~40 docs under `docs/` (DPU_*, MCP_*, SPRINT_*,
BENCHMARK_*, DEPLOY-00*), the 62KB `Makefile` (→ ~5KB), `helm/`, `bnk-operator/`
(6,659 LOC — the fleet agent), `Dockerfile.agent`, `upgrade.sh` (20KB),
`docker-compose.{adr424,local,dev,test,override}.yml`.

---

## 4. Does it cut build time and UI clutter?

**Build — yes.** Measured at Phase 0 ([`BNKSCOPE_BASELINE.md`](BNKSCOPE_BASELINE.md)):
cold build of all 7 images **340s**, warm frontend rebuild **37s**, images
**5.06 GB**, CI **27m 12s wall / 46m 14s compute**, initial JS payload **5.09 MB
raw / 1.33 MB gz**. The drivers being removed:

| Driver | Today | After |
|---|---|---|
| Backend image `tooling-deps` stage | downloads + installs `tofu`, `helm`, `kubectl`, `aws-cli v2`, `oras`, `infracost`, `docker-ce-cli`, `llmtop` | `kubectl` only (or nothing — the Python `kubernetes` client suffices) |
| Images built | api, worker, beat, frontend, mcp, proxy, agent (7) | api, frontend (2) |
| Compose services started | 30 | 3 (api, frontend/static, tmmscope-stack) |
| Python deps | 32 direct (celery, boto3, google-auth, python-hcl2, gitpython, alembic, passlib, slowapi…) | ~15 |
| `tsc` + `vite build` input | 846 files, incl. a 43k-line generated types file | ~200 files, ~8k types |
| Test suite | 466 backend + 292 frontend files across 25 CI jobs | ~100 + ~60, ~6 CI jobs |
| Migration CI | 3 dedicated Postgres migration jobs over 152 revisions | none (SQLite, schema created from models) |

The two heaviest images — `forge-agent` (1.61 GB, 83s, compiles `crick` from
source for benchmarks) and `celery-worker` (1.46 GB, 49s) — are both deleted
outright. Together with `celery-beat` they are **3.73 GB of the 5.06 GB** and
**172s of the 340s** cold build.

Frontend is the slowest *warm* rebuild at 37s, and 76% of its initial payload is
Monaco — pulled in for config editing that Phase 1 deletes (see baseline §7).

**UI — yes, dramatically.** Sidebar today: 5 sections, 16 entries. After:

```
  Clusters          ← flat auto-populated list, replaces Fleet + Kubernetes + Projects
  BNK Health        ← health dashboard, topology, gateways, traffic flow
  TMM Live          ← tmmscope Grafana dashboard, embedded
  Diagnostics       ← tmm_debug (tmctl/configview/bdt_cli), logs, exec, events, qkview
  AI Gateway        ← LLM observability / Loki request analytics
```

Gone from the UI: Command Center, Catalog, Blueprints, Access Methods, Projects,
Operations Log, Fleet, Infrastructure, Benchmarks, MCP Server, Users, System.
Also gone: the project-selector context that currently gates *every* cluster
view — a cluster is just a cluster.

---

## 5. Phases

Each phase is independently mergeable and ends with a green build. Order is
chosen so the biggest, least-entangled chunks go first.

### Phase 0 — Baseline ✅ **done 2026-08-23**
- ✅ Branch `feat/bnkscope` off `staging` @ `4a52ed4`; freeze declared — no
  further merges from `staging`.
- ✅ [`docs/BNKSCOPE_BASELINE.md`](BNKSCOPE_BASELINE.md): cold + warm build
  timings per service, image sizes, CI per-job wall-clock, frontend bundle
  analysis, 22 structural counters.
- ✅ `scripts/loc-report.py` with `--json` / `--compare`; baseline snapshot at
  `docs/bnkscope/loc-baseline.json`. Every later phase reports
  `./scripts/loc-report.py --compare docs/bnkscope/loc-baseline.json`.
- ✅ `scripts/bnkscope-baseline-build.sh` — reproducible cold/warm build timing.
- ✅ Target repo `github.com/mwiget/bnkscope` created (private).

### Phase 1 — Amputate the pipeline ✅ **done 2026-08-23 — 255,733 LOC (43.0%)**

**Measured:** tracked code 622,964 → 367,346 · OpenAPI paths 533 → 318 · routers
67 → 43 · DB tables 80 → 50 · backend source files 617 → 461 · frontend files
846 → 586 · `api-generated.ts` 43,368 → 26,930 · initial JS payload 5.09 MB →
4.61 MB raw / 1.33 → 1.20 MB gz (Monaco still dominates; Phase 6 removes it).

Verification: `pytest` 3,478 passed / 0 failed · `vitest` 1,695 passed / 0
failed · `tsc` clean · `docker compose build backend frontend` green ·
`bnkscope-dangling-imports.py` 0.

**Three reclassifications, all in the same direction** — these deploy *through*
the pipeline and cannot outlive it, so they moved from Phase 2 into Phase 1:
proxy deploy/migration/CIS-translate, the BNK upgrade workflow, and the
bare-metal + DPU deployment UI. The pipeline's Celery task layer went too.

**Deliberately kept** (deleting them would have silently changed behaviour in a
phase that is meant only to delete):

- `services/bnk_version.py` — extracted from the deleted upgrade service.
  Choosing an upgrade target was deployment; knowing which BNK version is
  running is diagnosis. The scanner reads Helm release secrets straight from the
  k8s API, so that signal survives without `helm_service`.
- `services/ssh_kubeconfig_fetch.py` — deleted in error on a stale docstring
  reference, restored.
- `credentials_service` + a widened `Project` stub — EKS/GKE/IBM token minting
  for the k8s core still resolves through the project's credential template.

**One addition:** `POST /api/k8s/clusters` (project-less). Cluster creation
previously required a project id that can no longer be obtained, so without it
"Add Cluster" would have been a dead button for four phases.

`Dashboard.tsx` was removed rather than gutted — projects, modules, drift and
the task log were most of it. `/` redirects to `/kubernetes` until Phase 6.

Known gap: `error-handling.integration.test.tsx` lost its API-error and
network-timeout cases with the Projects page.

<details>
<summary>Original plan for this phase</summary>

The single biggest cut, and the most self-contained: nothing in the monitoring
path imports it.

Remove: `services/execution/`, `tasks/opentofu_tasks.py`, `_tofu_helpers.py`,
`workspace_manager`, `state_viewer`/`state_parser`/`state_decryption`,
`routes/project_*` (8 routers), `routes/module_*`, `routes/blueprint_catalog`,
`routes/stacks`, `routes/registry`, `routes/helm`, `routes/drift`,
`routes/config_export`, `routes/config_promotion`, `routes/snapshots`,
`routes/usecase_artifacts`, `routes/project_orchestration`, `routes/runbooks`,
plus `models/{project,module,stack,blueprint_catalog,drift,…}` and the FE
`pages/{Projects,ProjectDetailV2,Modules,Catalog,Stacks}`,
`components/{modules,catalog,stacks,helm,presets,projects,deployments,drift,execution,snapshots,runbooks,secrets}`.

**The one real entanglement:** `KubernetesCluster.project_id` +
`cluster_auto_registration_service` (clusters are today created as a *side
effect* of a module apply). Phase 5 replaces that path; Phase 1 just makes
`project_id` nullable-and-ignored.

**Verify:** `pytest backend/tests/unit backend/tests/component -k "k8s or bnk or tmm"` green; UI loads Kubernetes + F5 BNK pages.

</details>

### Phase 2 — Drop fleets, operators, benchmarks, provisioning ✅ **done 2026-08-23 — 134,878 LOC**

**Measured:** tracked code 367,346 → 224,983 (−390,611 from baseline, 65.6%) ·
OpenAPI paths 318 → 153 · routers 43 → 25 · DB tables 50 → 18 · backend source
files 461 → 322 · frontend files 586 → 483 · `api-generated.ts` 26,930 → 11,664.

Verification: `pytest` 2,175 passed / 0 failed · `vitest` 1,421 passed / 0
failed · `tsc` clean · `docker compose build backend frontend` green ·
`bnkscope-dangling-imports.py` 0.

**The forced change:** cloud credentials moved from the project onto the
cluster. `KubernetesCluster` gains `credential_template_id` and
`cloud_credentials_encrypted`; `credentials_service` and
`credential_refresh_service` resolve against a cluster. Without it the k8s core
would have lost EKS/GKE/IBM token minting when the Project stub went. This is
Phase 5 work pulled forward by necessity. `project_id` is off the cluster and
names are unique instance-wide.

**Kept deliberately:**

- **DPF** (`routes/k8s/dpf.py`, `services/dpf/`) — read-only DPU inventory and
  health fetched via kubeconfig, exactly like F5 BNK data. That is monitoring;
  DPU *provisioning* is not, and it went.
- **qkview**, stripped to its ephemeral-curl-pod path (decision 1). The
  operator-dispatch layer went; `qkview_service` never used it.
- `ibm_cloud_service` — IBM IAM token exchange for ROKS cluster access, deleted
  in error and restored.
- The credential-template and SSH-credential **delete guards**, re-pointed at
  clusters rather than dropped — they stop you deleting a credential still in
  use.
- Cluster-level SSH tunnels. Only the project-level credential fallback and its
  jumphost hop went; tunnels themselves go in Phase 3 (decision 2).

Reachability now probes every cluster directly over its kubeconfig — the
operator-heartbeat probe mode is gone with the agent.

<details>
<summary>Original plan for this phase</summary>

- **Fleets** → `routes/fleet.py` (2,633 lines), `routes/operators/`,
  `fleet_targeting`/`fleet_policy`/`fleet_bulkop`, `pages/Fleet.tsx` (3,398
  lines — the largest page in the repo).
- **Operators** → the whole `bnk-operator/` agent, `operator_ws`,
  `operator_polling`, `operator_registry`. *Consequence:* qkview and licensing
  lose their preferred transport (see §6).
- **Benchmarks** → 7 FE pages, `routes/benchmarks.py`, `Dockerfile.agent`,
  `forge-agent` compose service, `aiperf`.
- **DPU/DPF/bare-metal** → `modules/bare_metal/`, `services/bare_metal/`,
  `rshim_service` (2,004), `dpu_*`, `bluefield_images`, `bf_conf_templates`,
  `routes/dpus*`, FE `components/{dpu,bare-metal,infrastructure}`.
- **Proxy migration / CIS translate** → `proxy_deploy_service` (2,600),
  `proxy_translate_cis_service` (1,694), `proxy_migration_service`,
  `proxy_discovery_service`, FE `ProxyMigrationWizard`.
- **BNK upgrade / config promotion** → `bnk_upgrade*`, `BNKUpgradePanel`.

**Verify:** `main.py` router list down to ~15; UI has no dead nav entries.

</details>

### Phase 3 — Delete auth ✅ **done 2026-08-23 — 18,515 LOC**

**Measured:** tracked code 224,983 → 206,468 · scanned buckets 204,384 →
185,869 (−409,126 from baseline, **68.8%**) · OpenAPI paths 153 → 130 · routers
25 → 21 · DB tables 18 → 14 · backend source files 322 → 299 · frontend files
483 → 460 · `api-generated.ts` 11,664 → 9,919 · Python deps 32 → 27.

Verification: `pytest` 1,700 passed / 0 failed · `vitest` 1,346 passed / 0
failed · `tsc` clean · `docker compose build backend frontend` green ·
`bnkscope-dangling-imports.py` 0.

**Loopback is the access control, and it had to be fixed before this was safe.**
The backend runs with `network_mode: host`, so removing auth while still binding
`0.0.0.0` would have put an unauthenticated API — with pod exec and log
streaming over every registered kubeconfig — on the network. `backend/Dockerfile`
now binds `127.0.0.1` (`BNKSCOPE_API_HOST` overrides), `API_HOST` defaults to
match, and the README leads with the posture. `ENCRYPTION_KEY` stays: kubeconfigs
and cloud credentials are still encrypted at rest.

**SSH went too** (decision 2): tunnels, the credential store, kubeconfig-fetch-
over-SSH, and the six `ssh_*` cluster columns. `ClusterConfigDialog` was
rewritten rather than patched — 78 of its references were SSH machinery. What
survives is name / kubeconfig / context / provider / region / namespace, keeping
the `KUBECONFIG_UNPORTABLE` inline-error path.

**Two incidental behaviours made explicit rather than silently lost:**

- The deleted audit helper called `log_from_request`, which flushed the session
  as a side effect — the SSO poll/refresh paths were relying on that to persist
  their own writes. Both now flush explicitly.
- Per-user notification scoping is gone; there is one local user.

**A method note worth keeping.** The first pass at removing auth-asserting tests
matched anything mentioning 401/403 and deleted 189 tests — including tests of
the *error taxonomy* that legitimately assert `UnauthorizedError.status_code ==
401`. Reverted and redone against `assert <response>.status_code == 40[13]`
only, which removed 81. The span helper behind it also had to be fixed twice:
once because a test that is the last method in a class ran to EOF and took the
rest of the file, once because multi-line signatures broke the body detection.

<details>
<summary>Original plan for this phase</summary>

Localhost-only tool ⇒ no users, no JWT, no roles, no audit trail.

- Remove `routes/auth.py`, `core/auth_middleware.py`, `core/audit_middleware.py`,
  `routes/audit.py`, `models/user`, `pages/{Login,UserManagement}`,
  `components/auth/`, `stores/authStore`, `RoleGuard`/`AuthGuard`, `slowapi`
  rate limiting, `passlib`/`bcrypt`/`python-jose`/`PyJWT`.
- Every route currently has `Depends(require_viewer|require_operator|require_admin)` —
  mechanical strip. **This is the phase with the widest blast radius** (touches
  nearly every route file), so it goes *after* the big deletions, when there are
  ~15 route files left instead of 67.
- Bind the API to `127.0.0.1` and say so loudly in the README. Kubeconfigs are
  still encrypted at rest — `core/encryption.py` stays.

**Verify:** `curl localhost:8000/api/clusters` with no token returns data; bind
address asserted in a test.

</details>

### Phase 4 — Collapse the runtime ✅ **done 2026-08-23 — 13,745 LOC**

The one phase that changed *operational* shape rather than deleting features.
LOC is the least of what it did: **13 containers → 2** (plus an opt-in `mcp`
profile), **API image 843 MB → 587 MB**, **cold start to healthy: 6 s**.

| | before | after |
|---|---|---|
| compose services | 13 | 2 (+1 profile) |
| Dockerfile targets | 6 | 3 (`api`, `test`, plus the shared bases) |
| API image | 843 MB | **587 MB** |
| Alembic revisions | 152 | 0 — schema from ORM models |
| CI jobs | 24 | 17 |
| backend tests | 1,628 | **1,665** |

**What replaced what**

| went | came |
|---|---|
| Celery + Redis broker/backend, 2 workers, beat | `core/background.py` — a 4-thread pool with `submit()` / `run_sync()`, plus the APScheduler instance that was already there |
| `backend/tasks/` | `backend/jobs/` — same functions, called directly |
| Redis cache | `core/cache.py` — `OrderedDict` + lock, per-entry TTL, bounded at 2,048 entries |
| Redis maintenance-mode key with an EXPIRE | `core/maintenance.py` — module flag + lock; **the 10-minute TTL stayed**, because the failure it guards (a restore that dies without clearing the flag) did not go away with the storage |
| Redis pub/sub → WebSocket | `bind_event_loop()` + `broadcast_sync()` over `asyncio.run_coroutine_threadsafe` |
| Postgres + 152 Alembic revisions | SQLite with WAL, `busy_timeout=30000`, `foreign_keys=ON`; `Base.metadata.create_all` at startup |
| `pg_dump` / `psql` backup | tar.gz of a `sqlite3.Connection.backup()` snapshot + the passphrase-wrapped Fernet key |
| docker-socket-proxy ×2, nginx proxy, forge-agent | nothing — they existed for the pipeline |

**Three real bugs the phase surfaced, none of which LOC counting would have found:**

1. `SystemService.get_health()` returned `{"errors": [], "total": 0}` — a
   `get_recent_errors` body grafted onto it during the Phase 1 restore. Every
   test that touched the endpoint mocked `SystemService` out ("to avoid
   Redis/Celery dependencies"), so a 500 on the app's own health endpoint was
   invisible to 1,600 green tests and only appeared when the container came up
   and its healthcheck failed. Both tests now run the real service.
2. `BackupService` passed a `str` to `wrap_fernet_key` (which takes `bytes`) and
   wrote its returned `dict` with `write_text`. Every backup would have raised
   `TypeError`. There were no backup tests at all — the old ones went with
   `pg_dump`. There are 19 now.
3. `verify_post_upgrade` still asked Alembic for a head revision, which could
   only ever return `skip`, permanently pinning the verdict to `degraded`. It
   now checks that every table the models declare is actually present.

**Also fixed, from the same "the image and the code disagree" family:** the
health endpoint pinged Redis, `backend_health_service` cached through Redis,
the frontend polled a `/api/system/queue-metrics` endpoint that no longer
exists, and `ServiceHealth` still carried `workers` / `active_tasks`.

**Ports are configurable now** (`BNKSCOPE_API_PORT`, `BNKSCOPE_UI_PORT`), which
was not in the plan. It got added because `docker compose up` on the dev box
collided with the running bnk-forge stack on 8000 — under `network_mode: host`
bnkscope shares the port space with everything else, so a fixed port is a bug.
This is also the auto-port negotiation Phase 8 wants, arriving early.

**Verify (all met):** `docker compose up` starts the stack; the backend is
healthy in **6 s**; a fresh volume bootstraps with no manual step; nginx proxies
`/api` through to it; 1,665 backend + 1,343 frontend tests green; ruff clean;
`tsc --noEmit` clean.

**Two things this phase pushed onto later phases, deliberately:**

- **`exec:` kubeconfigs are now unresolvable.** `kubeconfig_normalizer`
  accepts `aws`, `aws-iam-authenticator`, `gke-gcloud-auth-plugin` and
  `kubelogin`, on the basis that *the worker image* shipped them. The worker is
  gone and the API image has no CLI tools at all — which is most of the
  843 → 587 MB. So an EKS kubeconfig with `exec: aws eks get-token` validates
  and then fails at connect time. **Phase 5 must decide**: bake the plugins back
  into the image (~100 MB for the aws CLI alone), narrow the allowlist and tell
  the user to supply a bearer token, or resolve exec auth on the host side. It
  matters most in Phase 5 because walking `~/.kube/config` on a real laptop
  turns up exactly these kubeconfigs.
- **`dist/` is stale.** The registry-install package still describes postgres,
  redis and celery services. Phase 8 owns it (`bnkscope up|down|status`), so it
  was left alone rather than half-rewritten.

<details>
<summary>Original plan for this phase</summary>

- **Postgres → SQLite** at `~/.config/bnkscope/bnkscope.db`. ~15 tables, no
  concurrent writers, no HA. Delete all 152 Alembic migrations and
  `alembic/` entirely; create schema from SQLAlchemy metadata at startup
  (`Base.metadata.create_all`), version it with a single `schema_version` row.
- **Celery + Redis + beat + 2 workers + container-reaper → gone.** What actually
  needs to be async in a monitoring tool: reachability probes (already an
  asyncio scheduler in `services/reachability/`) and WebSocket log/exec streams
  (already asyncio). `tasks/` disappears; `websocket_service`'s Redis pub/sub
  becomes an in-process asyncio broadcast.
- **Both `docker-socket-proxy` services → gone** (they existed to let workers
  spawn OpenTofu containers).
- **`proxy/` (nginx) and `mcp/` → optional.** MCP server stays as an opt-in
  profile with a read-only tool subset (see §6).
- `startup_steps.py`: 16 steps → ~3 (db, reachability, cluster autodiscovery).

**Verify:** `docker compose up` starts 3 containers; cold start under 10s; a
fresh `~/.config/bnkscope` bootstraps with no manual step.

</details>

### Phase 5 — Clusters become a flat, self-populating list ✅ **done 2026-08-23**

**The only phase that adds code.** +958 LOC net: ~2,080 lines of discovery and
its tests in, ~1,100 lines of dead project/SSH/refresh plumbing out. Counting
lines was never the point here — the point is that a cluster list you have to
type in is the wrong shape for a tool running on the machine that already talks
to those clusters.

**How it works.** On startup and every 10 minutes, `services/kubeconfig_discovery`
reads `$KUBECONFIG` / the mounted `~/.kube/config`, merges the files the way
`kubectl` does, and turns each context into a *self-contained* single-context
kubeconfig — every `certificate-authority: /path`, `client-key: /path` and
`tokenFile:` read off disk and inlined. `services/cluster_discovery_service`
then probes each one through the same `load_kubeconfig` a registered cluster
uses, so EKS and GKE contexts get their native token minting rather than being
reported as unreachable.

**The registration rule (decision, settled 2026-08-23): probe everything,
register what has BNK on it.** A laptop has a dozen contexts — a kind cluster,
two staging clusters, somebody's demo. Registering all twelve buries the two
that matter. So a context with an `f5-bnk` / `f5-operator` / `f5-utils`
namespace registers itself; everything else is listed as a candidate with a
one-click **Add**, and anything that cannot be adopted says plainly why.
(`default` is deliberately *not* a marker namespace — every cluster has one.)

Discovery is idempotent, matched on **context name, not cluster name**: renaming
a cluster in the UI must not make the next sweep register a duplicate. A known
cluster that goes unreachable is marked, never deleted — VPN down is not the
same as cluster gone, and dropping the row would drop its history.

**exec-auth resolved, and smaller than Phase 4 feared.** `_base.py` already
minted EKS tokens via boto3 SigV4-presigned STS and GKE tokens via google-auth —
written precisely because the slim API image has no CLI. What was missing was
the operator's own credentials reaching the container. So (decision 1a):

  `~/.kube`, `~/.aws`, `~/.config/gcloud` are mounted **read-only**, and boto3 /
  google-auth resolve them through their own credential chains.

The image stays at 587 MB — no AWS CLI. `_generate_gcp_token_from_adc()` was
added so a locally-discovered GKE context works off `gcloud auth
application-default login` rather than requiring a service-account key.

`kubelogin` (AKS) left `SUPPORTED_EXEC_COMMANDS`. There is no Python equivalent,
so accepting it meant accepting a kubeconfig that validates and then fails at
connect time with a vague error. It is now rejected up front, with the fix in
the message (`kubectl create token <serviceaccount>`).

**Two security notes, both deliberate.** The mounts mean an unauthenticated API
can read your cloud credentials — which is why the loopback bind matters more
from here on, and why the compose header and README both say so. And Docker
creates a missing bind-mount source as a **root-owned directory in your home**,
which it did once during this work; `make ensure-host-dirs` now runs ahead of
`up` / `deploy` / `install` to make sure that cannot happen.

**Where the line falls between "deploy" and "configure".** Phase 6 removed
"Deploy BNK" and the adaptive deployment plan from the cluster view, and a
later pass removed the node-readiness probe with them — all of that installs
BNK *onto* a cluster. **F5 BNK → Build → Configuration Builder stays.** It
configures what an already-running TMM serves: gateways, listeners, routes,
backends. That is day-2 operation of a live cluster, not deployment, and it is
squarely what a troubleshooting tool is for. bnkscope does not put BNK there;
once it is there, telling it what to do is in scope.

**Deleted, all dead by earlier phases:** `refresh_kubeconfig` (shelled out to
`aws eks update-kubeconfig` — impossible in a CLI-free image, and a discovered
cluster re-reads its kubeconfig every sweep), `/api/projects/{id}/k8s/clusters`,
`rewrite_kubeconfig_for_tunnel`, `K8sClusterList` (430 lines, orphaned when
projects went), `AddClusterFlowDialog`, the `project_id` + five `ssh_*` fields
that outlived their columns in `ClusterSummary`/`ClusterDetailResponse`, and the
SSH branch in `ClusterStatusBadge`.

**A found bug worth recording:** the manual kubeconfig form had been unreachable
from the UI since Phase 2 — `K8sClusterList` was its only host, and nothing
rendered `K8sClusterList`. There was no way to add a cluster at all. The new
`AddClusterDialog` puts discovery first and the form behind a deliberate click.

**Where the plan was wrong.** It said strip `KubernetesCluster` "from 30+ columns
to ~10". The real count in bnk-forge was 22, and it is 23 now — Phases 1–3 took
`project_id` and the `ssh_*` columns, but Phase 2 *added* `credential_template_id`
and `cloud_credentials_encrypted` when credential resolution moved off Project.
Of the columns the plan listed for deletion, `platform_*` and
`enabled_prerequisites` feed the scan view (kept), and `running_release_id`
records the *observed* BNK version, which is monitoring data, not deploy intent.
Deleting them to hit a column count would have removed working features.

**Verify (met):** `docker compose down -v` then `up` — API healthy in **6 s**,
the machine's kube context discovered, probed (v1.31), correctly reported as
having no BNK footprint, and adoptable in one call. Re-running discovery leaves
one row, not two. 1,720 backend + 1,328 frontend tests green.

<details>
<summary>Original plan for this phase</summary>

Replaces fleets *and* projects as the organizing concept.

- On startup and on demand, walk `$KUBECONFIG` / `~/.kube/config` contexts,
  probe each (`/version` + "does namespace `f5-bnk` exist"), and register every
  reachable one. Same discovery posture `tmmscope inject --context` already
  assumes.
- Keep manual add (paste/upload a kubeconfig) for clusters not in the local
  file.
- Strip `KubernetesCluster` from 30+ columns to ~10: `name`, `context`,
  `api_server`, `version`, `kubeconfig_encrypted`, `default_namespace`,
  `status`, `last_seen_at`, `discovered_namespaces`, `meta_data`. Drop
  `project_id`, `ssh_*` (7 columns), `deployable_release_id`,
  `running_release_id`, `enabled_prerequisites`, `platform_*`.
- Reachability (`services/reachability/`) stays and becomes the cluster list's
  live status column — it's already a circuit-breaker-backed async probe
  scheduler, which is exactly right here.

**Verify:** delete the DB, start bnkscope, and every kube context on the box
shows up with a live/unreachable badge inside 5 seconds.

</details>

### Phase 6 — Reshape the UI ✅ **done 2026-08-23**

LOC is again the wrong yardstick (+663 net — a home page and a syntax
highlighter in, a nav and a brand system out). The number that matters:

| | Phase 0 | now |
|---|---|---|
| initial JS payload | 5,210 KB raw / 1,362 KB gz | **730 KB / 216 KB** |
| eagerly-loaded chunks | 8 | 6 |
| sidebar entries | 16 across 5 sections | 4 lenses + 2 utility |
| frontend tests | — | 1,365 (+21) |

**Monaco: −86% of the initial payload.** It was 3.8 MB of the 4.5 MB the
browser fetched before rendering a pixel, for an editor most sessions never
open. Two changes got it out:

- `components/k8s/MonacoEditor.tsx` loads it behind a dynamic import. The eager
  bootstrap in `main.tsx` was not gratuitous — it kept `@monaco-editor/react`
  from fetching Monaco off jsDelivr, which fails on the air-gapped networks BNK
  clusters live on. That requirement survives: the lazy chunk configures the
  same locally bundled copy. Nothing is fetched from a CDN.
- The `vendor-monaco` entry in `manualChunks` had to go too. A manualChunks
  entry pins its modules into a named chunk that the entry graph then preloads,
  which is precisely what kept it eager after the import was already dynamic.

**`components/ui/CodeBlock.tsx`** replaced Monaco for *reading* — an iRule, a
YAML fragment — at zero dependency: line numbers plus a single anchored regex
pass per line for YAML/TCL/JSON. Its tests are mostly one property, because it
is the one that matters: **the rendered text is the input text, exactly.** A
highlighter that drops a character is worse than none when someone is reading
it to decide what is wrong with a cluster.

**Sidebar: 16 entries across 5 collapsible sections → 4 flat lenses.**
Clusters · BNK Health · CNF Resources · AI Gateway. System and MCP moved to a
quiet footer group — backup/restore has to stay reachable, but it is not what
the tool is for. The per-section collapse state and its localStorage key went
with the sections.

**Command Center**, `/` — rebuilt around the only question bnkscope exists to
answer: *is anything wrong right now, and where?* Clusters sort by trouble, not
by name, and "unknown" outranks "healthy" — something we cannot see is more
interesting than something we can see is fine. Unread errors and warnings sit
above the list. With nothing registered it hands over to the discovery panel
rather than showing an empty grid.

**The mark is wired**: favicon set, `manifest.webmanifest` added with the
maskable icon, and the mark inlined in a 34px app-bar slot with the beam sweep
on mount (`.beam` + `pathLength="100"`, guarded by `prefers-reduced-motion`).
It has to be inlined rather than `<img>`-loaded because an `<img>`-hosted SVG is
style-isolated and the sweep is CSS on a path inside it — so `build.py` now
mirrors its output to `src/assets/icons/` for Vite's `?raw` import, alongside
the `public/` copies the favicon uses. Byte-identical; still generated, still
never hand-edited.

**Also removed, all dead:** the whole `__BRAND__` switching system
(`brand.ts`, `BrandLogo`/`F5Logo`/`ForgeLogo`, `config.js`, the
`99-brand-config.sh` nginx entrypoint) — bnkscope has one brand; the breadcrumb
trail, which named the bnk-forge section a page belonged to and has no
hierarchy left to describe; `SSHConnectivityBadge` + `useSSHConnectivity`
(orphaned in Phase 3); and the bnk-forge favicon and logo.

**`ProcessMetricsBar` moved rather than went.** A row of numbers ticking every
five seconds on every page is exactly the ambient clutter this phase was
removing, but "is the tool itself the problem?" is a fair question for
something running on the operator's own laptop. It is now a card on
System → Monitor that polls only while that page is open.

**Two bugs found on the way:**

1. The MSW handler for `/api/system/process-metrics` returned an invented
   `{processes, total_cpu_percent}` shape that matched no schema. Nothing
   consumed it, so it never failed — until something did. Corrected to
   `ProcessMetricsResponse`.
2. Wiring the discovery panel into the cluster page's empty state made it mount
   during the list's initial load, firing a full kubeconfig sweep on every page
   mount. Gated on `isLoading`.

The `error-handling.integration.test.tsx` cases that Phase 1 orphaned (they
exercised the Projects page) are re-pointed at the home page — the right target,
since a tool for diagnosing broken things must not render a blank screen when it
is itself broken.

<details>
<summary>Original plan for this phase</summary>

### Phase 6 — Reshape the UI (5 nav entries)
- Rewrite `Sidebar.tsx` to the 5 entries in §4; delete `DataPrefetcher` project
  logic, drift badges, task-count badges, `ProcessMetricsBar`.
- **Wire the bnkscope mark** (landed 2026-08-23, `frontend-v2/public/icons/`).
  `index.html` still points at the bnk-forge favicon; the exact `<link>` block
  and the manifest `icons` array (including `purpose=maskable`) are in
  `scripts/bnkscope-icon/README.md`. The icon sits in a 34px square slot at the
  top-left of the app bar; its beam path carries `class="beam"` and
  `pathLength="100"`, so a `stroke-dashoffset` 100 → 0 animation sweeps the
  trace on mount. The SVGs are generated — edit `build.py` and re-run, never
  hand-edit an `.svg`.
- **Rebuild the home page.** Phase 1 deleted `Dashboard.tsx` and pointed `/` at
  `/kubernetes`; the bnkscope Command Center is built here.
- **Drop Monaco.** Swap `F5iRuleViewer` to a read-only syntax highlighter and
  remove `@monaco-editor/react` + `monaco-editor` — 3.73 MB of the 4.61 MB
  initial payload (see baseline §7).
- Cluster is selected once, globally (a header dropdown), instead of being
  routed through a project.
- Regenerate `api-generated.ts` from the shrunken OpenAPI spec. Phase 5 already
  regenerated it once (the cluster schemas changed), so this is a re-run, not a
  first pass.

</details>
- Prune `components/ui/` and `lib/` to what still imports; delete
  `react-joyride`, `@monaco-editor/react` (config editing is gone),
  `@dagrejs/dagre`+`reactflow` **only if** the topology viewers go — they
  don't, so these stay.

**Verify:** `vite build` bundle size and build time vs the Phase-0 baseline,
committed to the same doc.

</details>

> **Note on `react-joyride` and `@monaco-editor/react`.** The original plan
> deleted both. `@monaco-editor/react` stayed: resource create/edit is a real
> capability for a troubleshooting tool, and lazy-loading it captured the whole
> payload win without removing the feature. Reading, which is the common case,
> no longer touches it at all.

### Phase 7 — Integrate tmmscope ✅ **done 2026-08-23**

+1,883 LOC, none of it Go. The plan budgeted ~4.2k for vendoring tmmscope's
code; nothing was vendored, because tmmscope's *contract* turned out to be
enough.

**The upstream blocker was already fixed.** The plan's item 5 said Grafana's
`allow_embedding` / `X-Frame-Options` needed an upstream change to tmmscope.
It does not: `compose.tmpl.yaml` already sets `GF_SECURITY_ALLOW_EMBEDDING` and
anonymous viewer, and the running Grafana returns no `X-Frame-Options`.
Verified against the live stack before writing anything. **No tmmscope change
was needed or made.**

**Read-only orchestration, and the reason.** The plan had bnkscope shelling out
to `tmmscope up`, `down`, `inject` and `eject`. It does none of those:
`tmmscope up` needs the Docker socket and `tmmscope inject` shells out to
`kubectl`, so honouring the plan meant putting a root-equivalent socket and
~75 MB of CLI into a container with no authentication in front of it —
undoing a chunk of Phase 4 to gain a button. So:

  read   ``~/.config/tmmscope/endpoints.json`` (mounted `:ro`) → is it up, on
         which ports; **and Prometheus** → which clusters are streaming *now*
  write  nothing. Every state-changing action is shown as a copy-able command
         to run on the host.

That second read is the one that matters. "Is this cluster injected?" is
answered by asking Prometheus whether it holds `f5tmm_up` series for the
cluster's label — evidence, not a config file's claim, and it needs no binary,
no kubectl and no socket.

**Joining the two tools needed real care.** They share no identifier:
`tmmscope inject --cluster` names the `cluster=` label freely. bnkscope matches
on the conventions it can — the kube context, **the half after the `@`** in a
`user@cluster` context, the cluster name, the discovered namespaces — and
returns nothing rather than guessing, because a wrong match points the
dashboard at a *different* cluster's telemetry. When that finds nothing, the UI
offers the streaming labels and the operator binds one; the binding is
remembered on the cluster row.

**TMM Live** (`/tmm-live`, fifth nav entry) embeds the dashboard in kiosk mode,
scoped with `var-cluster`, sandboxed and `no-referrer` — same machine, still a
separate origin. Four states, each with the right next action: stack down →
`tmmscope up`; streaming → the dashboard; streaming under an unrecognised name
→ a label picker; not streaming → `tmmscope inject`, with the ephemeral-vs-
`--permanent` warning the plan asked for.

**Validated against real clusters, which changed the design.** The user pointed
out `tmmlbctl cluster list` shows two: `infra` (this host's `~/.kube/config`)
and `dpu-cplane-tenant1`, a Kamaji tenant actually running BNK and actually
streaming TMM telemetry. Testing against both found three things:

1. **Phase 5's BNK detection was wrong.** It matched *namespace names*
   (`f5-bnk` / `f5-operator` / `f5-utils`). On the real cluster the `f5-tmm`
   pods live in **`dpf-operator-system`** — a namespace that also exists on DPF
   clusters carrying no BNK — while the control plane sits in `f5-cne-core`,
   which was not in the set at all. Any namespace list is either too narrow or
   too broad. It now matches **pods by label**, reusing the chart-sourced hints
   already in `bnk_pod_discovery._LABEL_HINTS`
   (`app in (f5-tmm,flo,f5-cne-controller,f5ingress-f5ingress)` plus the
   `app.kubernetes.io/name` variants) — two API calls, namespace-agnostic.
   Verified: the BNK cluster reports `f5-tmm` ×2 and `f5ingress-f5ingress`;
   `infra` correctly reports nothing.
2. **A Kamaji tenant cluster is invisible to Phase 5 discovery.** Its
   kubeconfig is a secret inside `infra`, not a context in `~/.kube/config`, so
   discovery cannot see it. Manual add works — the kubeconfig has inline client
   certs and is portable. Worth knowing: local-kubeconfig discovery covers what
   is in the file, and hosted control planes are not.
3. The `user@cluster` context convention is what actually joins the two tools
   here: context `kubernetes-admin@dpu-cplane-tenant1` ↔ label
   `dpu-cplane-tenant1`. Auto-matched, no binding needed.

**A bug the tests caught:** the theme passthrough fell back to *light* for any
unrecognised value, while the parameter's own default is dark — so a bad theme
string would have rendered a light dashboard inside a dark UI.

**Verify (met):** against the live stack and both real clusters — status reads
the negotiated ports, Prometheus reports `dpu-cplane-tenant1` streaming, the
generated iframe URL returns 200 with no framing restrictions, and the cluster
auto-matches with no manual binding. 1,772 backend + 1,375 frontend tests green.

**Not done, deliberately:** `tmmlbctl cluster register` posts to bnk-forge under
a `--project`, which bnkscope no longer has. That integration is broken against
bnkscope and the fix belongs in `tmmlbctl`, not here.

<details>
<summary>Original plan for this phase</summary>

### Phase 7 — Integrate tmmscope (adds ~4.2k LOC Go)
`tmmscope` is already standalone and already has a clean contract
(`~/.config/tmmscope/endpoints.json`). **Do not absorb it — orchestrate it.**

1. **Vendor the binary, not the code.** `bnkscope` ships/depends on `tmmscope`
   and calls it: `tmmscope endpoint --json` to discover, `tmmscope up` to start
   the stack, `tmmscope inject --context <ctx> --yes` per cluster.
2. **New backend module** `services/tmmscope/` (~300 lines): reads the
   discovery file, shells out to the binary, exposes
   `GET /api/tmmscope/status`, `POST /api/tmmscope/{up,down}`,
   `POST /api/clusters/{id}/tmmscope/{inject,eject}`.
3. **"TMM Live" page** embeds `grafana/d/tmm-realtime` in an iframe scoped to
   `cluster=<name>` (the label `tmmscope inject` already stamps), with
   inject/eject buttons and a clear ephemeral-vs-`--permanent` warning
   mirroring tmmscope's own confirmation semantics.
4. **Cross-link from diagnostics:** a TMM pod in the Diagnostics view gets a
   "scope this" action; the BNK Health dashboard's TMM component links straight
   to the live dashboard.
5. Grafana's `X-Frame-Options` / `allow_embedding` must be set in tmmscope's
   provisioning — **an upstream change to `tmmscope`**, small but real.

**Verify:** from a cold machine — `bnkscope up`, cluster auto-appears, click
"TMM Live", inject, and see counters move within 30s.

</details>

### Phase 8 — Package and document ✅ **done 2026-08-23**

**`./bnkscope up`.** A single bash entry point mirroring tmmscope's CLI shape,
because the two run side by side and an operator should not have to remember
which one takes `--purge` and which takes `-v`:

```
bnkscope up [--no-build] · down [--purge] · status · open · logs · endpoint
```

Ports are negotiated, not assumed — the plan's "so the two never collide". It
wants 8080/8000, walks upward when taken, and **persists** the choice so a
running stack keeps its ports across re-runs. Verified on this machine, where a
full bnk-forge stack already holds both: it landed on 8083/8001, and a second
`up` kept them. `bnkscope endpoint` publishes them the way tmmscope publishes
its own, so nothing downstream has to guess.

`up` also creates `~/.kube`, `~/.aws`, `~/.config/{gcloud,tmmscope}` **as the
user** first — Docker would otherwise create a missing bind-mount source as a
root-owned directory inside `$HOME`, which it did once during Phase 5.

**regcachectl pull-through.** `up` detects a running `regcache-dockerhub` by
reading its published port from `docker port` (the same cross-tool contract
tmmscope uses — container name plus in-container port, not a shared library)
and builds base images through it. Cold start on this machine: **11 seconds**.
`BNKSCOPE_REGISTRY_CACHE=auto|on|off`.

Two bugs found doing it, both only visible against a real cache:

1. `resolve_registry_cache` printed its status line to *stdout*, which is the
   function's return channel — the message ended up inside the image reference
   and the build failed with `invalid reference format`.
2. Official Docker Hub images need the `library/` path segment when pulled
   through a mirror. tmmscope never hit this because both its images
   (`prom/prometheus`, `grafana/grafana`) are namespaced; bnkscope's `python`
   and `node` are not. The digest pins are what make the rewrite safe — a
   mirror can serve a different path, never different bytes.

**CI: 25 jobs → 10** (7 that gate, plus `changes`, `ci-gate`, and an advisory
MCP job). The old pipeline split the backend suite across five jobs staged in
four dependent phases. That was right when the suite was slow and half of it
needed a live Postgres; it runs in **12 seconds** now, so five runners each
paying ~40s of checkout and pip-install saved nothing, and the staging meant a
typo in an integration test was not reported until three phases in. One job per
toolchain, all in parallel.

**README rewritten** around the one story — *something is wrong with a BNK
cluster* — with the security posture, the four read-only mounts, and the
`exec:` kubeconfig rules stated up front rather than buried.

**Docs: 70 files → 21.** Everything describing a removed subsystem (DPU deploy,
benchmarks, bare-metal discovery, CI runner modules) and every bnk-forge-era
planning artefact (sprints, roadmaps, strategy, release checklists) moved to
`docs/archive/`, which the plan asked for. ADRs stay where they are, as history.

**Deleted rather than half-fixed:**

- **`dist/`** (1,200 lines) — a registry-install package still describing
  postgres, redis and celery, for images bnkscope does not publish. The install
  story is `git clone && ./bnkscope up`; shipping a broken installer is worse
  than shipping none.
- `push-customer-build`, its multiarch twin, and `scripts/ibm_cloud_bnk_forge.sh`
  — they paired with the `dist/` `.env` that just went.
- `scripts/get_dpu_pwd.sh` — imports `models.bare_metal`, deleted in Phase 2.

**Retargeted rather than deleted:** `docker-bake.hcl` and
`publish-signed-images.sh` went from 7 images to 3 (`api`, `frontend`, `mcp`).
Signing what you publish is worth keeping even when you publish nothing yet.

**A real piece of drift, found by shellcheck's cousin:** `models.__all__` listed
**93 names, 46 of which no longer existed** — `Project`, `BenchmarkRun`,
`BareMetalHost`, `DriftCheck` and forty-odd others, deleted across Phases 1–2
with their modules but never removed from the barrel. Nothing imported them so
nothing failed; `from models import *` would have. Now 47, all real.

**Verify (met):** from a clean state — `./bnkscope down --purge`, then
`./bnkscope up` builds and starts in **11s**, negotiates around an occupied
8080/8000, serves every route, and `bnkscope status` lists the real BNK cluster.
1,772 backend + 1,375 frontend tests green; ruff, tsc and shellcheck clean.

**Not done:** the squash-export to `github.com/mwiget/bnkscope` (§6 decision 5).
Nothing has been pushed anywhere — that is the standing instruction, and the
export is one command when you want it.

<details>
<summary>Original plan for this phase</summary>

### Phase 8 — Package and document
- `bnkscope up|down|status` wrapper (mirror tmmscope's CLI shape and its
  auto-port negotiation so the two never collide).
- `regcachectl` pull-through detection for bnkscope's own images, same as
  tmmscope does — the fleet is already there.
- README rewritten around one story: *"something is wrong with a BNK cluster."*
- CI: 25 jobs → ~6 (lint, typecheck ×2, unit ×2, docker build).
- Delete `docs/` entries for removed subsystems; keep ADRs as history under
  `docs/archive/`.

</details>

---

## 6. Decisions — **settled 2026-08-23**

1. **qkview: keep. Licensing: drop.** qkview keeps only its ephemeral-curl-pod
   path (the `bnk-operator` transport dies with Phase 2) — it is the single most
   valuable artifact in a real F5 support case and the fallback already exists.
   `routes/licensing.py`, `LicensingPanel.tsx`, `LicenseStatusCard.tsx` go.

2. **SSH tunnels: delete.** `ssh_tunnel_manager`, `services/ssh/`, and the 7
   `ssh_*` cluster columns go. On a laptop the operator's own `~/.kube/config`
   and their own `ssh -L` cover it. Reclaims ~8k LOC.

3. **MCP server: keep a read-only subset** (~2k of 9,155 LOC) as an opt-in
   compose profile. `iac_operations.py` (841) and `cluster_management.py` (834)
   die with Phase 1; what survives is cluster health, resource reads, and
   `tmctl`. An AI agent that can query a sick cluster is squarely on-mission.

4. **Recovery + rollouts: keep, behind an explicit confirm.** These are the
   *only* sanctioned mutations besides qkview creation — the "narrow break-glass"
   exception to read-only. Everything else is a read.

5. **New repo: `github.com/mwiget/bnkscope`, created private 2026-08-23.**
   Supersedes the branch-then-export recommendation. The end state shares almost
   nothing with `staging` and the two will never merge again; a fresh repo avoids
   dragging 152 migrations and 48k lines of markdown history along, and puts
   bnkscope next to `tmmscope` and `regcachectl` where it belongs. Work continues
   on `feat/bnkscope` here through the deletion phases (where `git log` still has
   value for tracing *why* something went), then squash-exports.

---

## 7. Risks

| Risk | Mitigation |
|---|---|
| `Depends(require_*)` is threaded through nearly every route — Phase 3 is a wide mechanical edit | Do it after Phase 1+2 cut the route count 67 → ~15 |
| Deleting Alembic loses any upgrade path from an existing bnk-forge install | Accepted — bnkscope is a *new local tool*, not an upgrade. State it in the README. |
| `KubernetesCluster.project_id` FK cascades into most k8s queries | Phase 1 nulls it; Phase 5 drops the column and the joins together |
| Frontend `components/k8s/` (35,913 LOC) mixes keep and remove in one directory | Split it explicitly in Phase 6: `k8s/` (browse) vs `bnk/` (diagnose) vs `build/` (delete) |
| tmmscope Grafana iframe embedding needs an upstream tmmscope change | Small; land it in `tmmscope` before Phase 7 starts |
| `bnk-operator` deletion silently breaks qkview | Decision 6.1 must be settled before Phase 2 |

---

## 8. Effort

Phases 1–3 are deletion, which is fast and verifiable. Phases 4–5 are the real
engineering (SQLite migration, removing Celery, cluster autodiscovery). Phase 7
is small because tmmscope already did the hard part.

| Phase | Shape | Rough effort |
|---|---|---|
| 0 Baseline | measure | 0.5 d |
| 1 Pipeline | delete ~200k | 3–4 d |
| 2 Fleet/DPU/bench | delete ~120k | 3–4 d |
| 3 Auth | delete ~23k, wide edit | 2 d |
| 4 Runtime collapse | **build** | 4–5 d |
| 5 Cluster autodiscovery | **build** | 3 d |
| 6 UI reshape | rewrite nav + prune | 3–4 d |
| 7 tmmscope | integrate | 2–3 d |
| 8 Package/docs | polish | 2 d |
| | | **~4–5 weeks** |
