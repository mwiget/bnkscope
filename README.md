<img src="frontend-v2/public/icons/bnkscope.svg" width="96" align="right" alt="">

# bnkscope

**Something is wrong with a BNK cluster. Find out what.**

bnkscope is a local, single-user tool for troubleshooting and monitoring
F5 BIG-IP Next for Kubernetes. It runs on your laptop, reads your own
kubeconfig, and shows you the cluster.

It does not deploy anything. It has no users, no roles, no pipeline, and no
opinion about how your clusters got there.

```bash
git clone https://github.com/mwiget/bnkscope.git
cd bnkscope
./bnkscope up
```

Open the URL it prints. There is no login.

---

## What happens next

bnkscope reads `~/.kube/config` on startup and probes every context in it.
A cluster running **BNK**, the **NVIDIA DPF operator** or **NICo** registers itself —
detected by pod labels, not namespace names, because on a real deployment they
live on different clusters and the namespaces vary by install shape.
Everything else is listed with a one-click **Add**, or a plain reason it cannot
be added: an unreadable cert path, an auth plugin bnkscope cannot run.

Then:

| | |
|---|---|
| **Overview** | Is anything wrong right now, and where. Clusters sort by trouble, not by name. |
| **Clusters** | Every resource on a cluster — pods, logs, exec, events, YAML. A **DPF** tab appears on a cluster running the NVIDIA DPF operator, and a **NICo** tab on one running the NVIDIA Infra Controller — its tenants, VPCs and tenant load balancer services, read from the Forge API. |
| **BNK Health** | TMM, gateways, traffic flow, and the `tmctl` / `configview` / `bdt_cli` diagnostics. |
| **TMM Live** | Real-time TMM counters in Grafana. One click adds the exporter to a cluster's TMM pods. |
| **Logs** | Every cluster's logs, 24h, searchable. Collected through the Kubernetes API — nothing installed. |
| **CNF Resources** | F5 custom resources and the conditions they report. |
| **AI Gateway** | LLM request analytics and logs. |

---

## Security posture: no authentication at all

> **bnkscope has no login, no users, and no roles. Where it listens is the only
> access control there is.**

By default everything that matters is on loopback: the API on `127.0.0.1:8000`,
and the UI — which proxies `/api` straight through to it — on `127.0.0.1:8080`.
On a laptop, that is a coherent security model: nothing off the machine can
connect.

### `--listen` removes it

`bnkscope up --listen 0.0.0.0` opens the UI to the network deliberately, and
**nothing takes over from the bind address when it does.** There is no password
to add and no token to configure. Anyone who can reach the port has, without
authenticating:

- **A shell in any pod** on any registered cluster, over `/ws/.../exec`
- **Every credential bnkscope holds.** `POST /api/system/backup` returns the
  database *and* the encryption key that decrypts it, wrapped with a passphrase
  the caller chooses. That is every kubeconfig and every stored cloud
  credential, in one request.
- **Cluster surgery** — restart, drain, scale, delete, and `platform-restart`
  on a live BNK cluster
- 135 operations in total, of which 56 change something ([the full list](docs/API_REFERENCE.md))

Traffic is plain HTTP, so all of it — and everything you type into a pod shell —
crosses the network in the clear and can be read or modified in flight.

### Only use it on a network you would trust with all of that

Concretely, one of:

- **A private lab or management network** you control end to end
- **A VPN — Tailscale or WireGuard.** This is the recommended answer, and it is
  the only one that covers *every* port below rather than just the UI. Bind to
  the VPN interface: `bnkscope up --listen 100.x.y.z`
- **An SSH tunnel**, leaving the bind at its loopback default:

  ```sh
  ssh -N -L 8080:localhost:8080 you@the-host
  ```

Do not put it on office wifi, a shared lab VLAN, or anything reachable from a
guest network. There is no second line of defence.

### The other ports

`--listen` governs the UI. These are separate, and two of them **must** accept
connections from your clusters to do their job:

| port | bind | what it is | if a stranger reaches it |
|---|---|---|---|
| UI | follows `--listen` | nginx + `/api` + `/ws` | everything above |
| Grafana | follows `--listen` | dashboards | **reads any dashboard, and queries Loki through its datasource proxy — i.e. every log line from every registered cluster.** Anonymous viewing stays on because TMM Live embeds the dashboard in your browser; requiring a login there would only put a login box inside bnkscope's own page. Admin is a generated password (`bnkscope grafana-password`). |
| Prometheus `9491` | **always `0.0.0.0`** | remote-write receiver | reads your TMM metrics; **can inject fabricated ones** |
| Loki `3100` | loopback | log store | not reachable off-host |
| API `8000` | loopback | FastAPI | not reachable off-host |

Prometheus is open by design — the exporters push *to* it from inside your
clusters, so it cannot be closed without losing the telemetry. If that matters to you, firewall them to your cluster
subnets, or use a VPN and bind to it.

Kubeconfigs and cloud credentials are encrypted at rest (`ENCRYPTION_KEY`) —
which protects the database file on disk, and does not protect it from the
backup endpoint above.

### What it reads from your machine

Four directories, mounted **read-only**. Nothing is ever written back.

| mount | why |
|---|---|
| `~/.kube` | the cluster list itself |
| `~/.aws` | boto3 reads it to mint EKS tokens natively — no AWS CLI in the image |
| `~/.config/gcloud` | the same for GKE, via google-auth |
| `~/.config/tmmscope` | tmmscope's stack, if you already run one instead |

`./bnkscope up` creates any that are missing **as you**, because Docker would
otherwise create them as empty root-owned directories inside your home. That is
why it is the supported entry point rather than a bare `docker compose up`.

### `exec:` kubeconfigs

`aws eks get-token`, `aws-iam-authenticator` and `gke-gcloud-auth-plugin` all
work — bnkscope mints those tokens itself, in Python, and never runs the binary.

**`kubelogin` (AKS) does not.** There is no Python equivalent and the image
ships no CLI tools, so an AKS context is listed with that reason rather than
accepted and then failing at connect time. Supply a bearer token instead
(`kubectl create token <serviceaccount>`) and add the cluster by hand.

---

## Commands

```
bnkscope up [--no-build]     start it; negotiates ports, probes your kubeconfig
           [--listen ADDR]   bind the UI to ADDR instead of 127.0.0.1
           [--no-telemetry]  skip Prometheus + Grafana (they run by default)
           [--no-mcp]        skip the read-only MCP server (loopback, 8081)
bnkscope down [--purge]      stop it (--purge also drops the database and key)
bnkscope status              running state, ports, registered clusters
bnkscope open                open the UI
bnkscope logs [service]      follow container logs
bnkscope endpoint            print the discovery file
bnkscope grafana-password    print Grafana's generated admin password
```

**Ports are negotiated, not assumed.** bnkscope wants 8080 and 8000, but under
host networking it shares the port space with everything else on the machine.
When a port is taken it walks upward and *persists* the choice, so a running
stack keeps its ports across re-runs — and reverts to the default once that
frees up again, unless you asked for a specific port, in which case it stays
put. Read them back with `bnkscope endpoint` rather than hard-coding them: the
same contract tmmscope publishes, for the same reason.

```bash
./bnkscope up --listen 0.0.0.0           # reach it from another machine (see the warning above)
BNKSCOPE_UI_PORT=9090 ./bnkscope up      # ask for a specific port
BNKSCOPE_REGISTRY_CACHE=on ./bnkscope up # require the regcachectl pull-through cache
```

---

## TMM Live

Real-time TMM counters: `f5tmm_up`, throughput, connections, per-pool-member
load, and AI token usage. bnkscope runs the whole path.

```bash
./bnkscope up                # Prometheus + Grafana come up with it
```

Then open **TMM Live**, pick a cluster, and click **Add the exporter**. That
injects `tmm-stat-exporter` into the cluster's `f5-tmm` pods as an **ephemeral
container** — no TMM restart, and it works on operator-managed BNK, where a
patched Deployment would just be reconciled away.

It is transient by construction: an ephemeral container does not survive a pod
restart, and nothing re-adds it. That is the honest shape for a troubleshooting
tool, and the page says so rather than letting you find out.

Removing it is deliberately harder than adding it. An ephemeral container cannot
be taken out of a running pod, so clearing one means **recreating the TMM pods**,
which drops dataplane traffic — a typed confirmation, not a click.
[D-036](docs/adr/D-036-tmmscope-injection-in-bnkscope.md) has the reasoning.

**Prometheus is not loopback-only**, unlike everything else here: the exporters
push to it from inside your clusters, through the host gateway. It receives
metrics and answers queries — it holds no credentials and can change nothing.
`--no-telemetry` skips the whole stack.

### Coming from tmmscope

[tmmscope](https://github.com/mwiget/tmmscope) is where this came from, and it
still works — if its stack is up, bnkscope finds and uses it instead of starting
its own. Nothing here needs it installed, though: the injection is a Kubernetes
API call bnkscope makes itself, the Prometheus and Grafana configuration is
vendored in `telemetry/`, and the exporter is built from `tmm-stat-exporter/` in
this repository.

What stays over there is `--permanent` injection. Both durable modes restart
TMM, and the webhook mode installs a cluster-scoped
`MutatingWebhookConfiguration` with a 10-year self-signed CA — neither belongs
behind a button in a troubleshooting tool.

## Architecture

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
                            │
                            │ tmm-stat-exporter pushes (remote_write)
                            ▼
                  ┌────────────────────────┐
                  │ prometheus ◀── grafana │  TMM Live · 24h window
                  └────────────────────────┘
```

Two containers, plus a third exposing read-only MCP tools for an AI agent on
loopback (`./bnkscope up --no-mcp` skips it), and four more for telemetry —
prometheus, grafana, loki and alloy. No database server, no message broker, no
worker pool, no reverse proxy — a single-user tool watching a handful of
clusters needs none of them.

`network_mode: host` is used so the backend can reach clusters on your own
networks without Docker's bridge iptables getting between it and your VPN
routes. On macOS and WSL2 that does not do what it says, so `bnkscope up`
switches to a bridge overlay that publishes to `127.0.0.1` only.

---

## Development

```bash
make dev-setup        # backend venv + frontend deps
make quick-check      # lint + types + openapi freshness (~15s)
make test             # everything
make test-docker      # the same, in containers — no local venv or Node needed
```

The Makefile is the source of truth; CI runs the same targets.

| | |
|---|---|
| [User guide](docs/USER_GUIDE.md) | every page, and what it answers |
| [Troubleshooting](docs/TROUBLESHOOTING.md) | when bnkscope itself misbehaves |
| [Cloud authentication](docs/CLOUD_AUTH.md) | EKS, GKE, AKS, and AWS SSO |
| [API reference](docs/API_REFERENCE.md) | the HTTP surface (generated) |
| [Development guide](docs/DEVELOPMENT.md) | build, test, architecture |
| [Testing](docs/TESTING.md) | suites, fixtures, what is covered |
| [ADRs](docs/adr/) | why things are the way they are |
| [How bnkscope came from bnk-forge](docs/BNKSCOPE_PLAN.md) | the eight phases, and what each one measured |
| [All docs](docs/README.md) | the index — including which documents are bnk-forge-era records |

---

## Where this came from

bnkscope is a fork of **[bnk-forge](https://github.com/f5devcentral/bnk-forge)**
with the deployment platform removed. bnk-forge is the larger tool — OpenTofu
pipelines, module catalogs, blueprints, fleets, RBAC, DPU provisioning — and
most of the code here started there. **bnk-forge deploys BNK; bnkscope looks at
it.** If you need to stand a cluster up rather than diagnose one, go use
bnk-forge; it is the right tool and this is not a replacement for it.

The reduction was done in eight phases, each measured;
[`docs/BNKSCOPE_PLAN.md`](docs/BNKSCOPE_PLAN.md) records all of them, including
the parts of the plan that turned out to be wrong. This repository's git history
begins at bnk-forge's own initial public release commit, so the lineage is in
the record rather than only in prose.

bnkscope is not maintained by the bnk-forge authors — please report issues here,
not there.

---

## License

Apache License 2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE), which carries
the bnk-forge attribution.

- [Contributing](CONTRIBUTING.md) — workflow, ADRs, code style
- [Code of Conduct](CODE_OF_CONDUCT.md)
- [Security policy](SECURITY.md) — how to report a vulnerability
