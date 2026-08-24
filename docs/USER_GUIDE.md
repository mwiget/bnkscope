# bnkscope — User Guide

Something is wrong with a BNK cluster. This is how you find out what.

bnkscope is read-mostly and single-user. It has no login, no roles and no
concept of a project or a deployment — it reads your kubeconfig and shows you
the cluster. For what it deliberately *cannot* do, see
[What bnkscope will not do](#what-bnkscope-will-not-do) at the end.

- [First run](#first-run)
- [Overview — is anything wrong](#overview--is-anything-wrong)
- [Clusters — every resource](#clusters--every-resource)
- [BNK Health](#bnk-health)
- [TMM Live](#tmm-live)
- [Logs](#logs)
- [CNF Resources](#cnf-resources)
- [AI Gateway](#ai-gateway)
- [System](#system)
- [MCP](#mcp)
- [Keyboard shortcuts](#keyboard-shortcuts)
- [On a phone or tablet](#on-a-phone-or-tablet)
- [What bnkscope will not do](#what-bnkscope-will-not-do)

---

## First run

```bash
./bnkscope up
```

Open the URL it prints. There is no login.

On startup bnkscope reads `~/.kube/config` and probes **every context in it**.
You do not add clusters by hand:

- A cluster running **BNK** or the **NVIDIA DPF operator** registers itself.
  Detection is by *pod labels*, not namespace names — on a real deployment the
  two live on different clusters and the namespaces vary by install shape.
- Everything else is listed with a one-click **Add**.
- A context bnkscope cannot use is listed with the plain reason: an unreadable
  cert path, or an auth plugin it cannot run.

`aws eks get-token`, `aws-iam-authenticator` and `gke-gcloud-auth-plugin`
kubeconfigs all work — bnkscope mints those tokens itself, in Python, and never
runs the binary. **`kubelogin` (AKS) does not work**: there is no Python
equivalent and the image ships no CLI tools. Supply a bearer token instead:

```bash
kubectl create token <serviceaccount>
```

and add the cluster by hand.

If a cluster stops responding later, its tile says so rather than showing stale
data.

---

## Overview — is anything wrong

The home page answers one question: **is anything wrong right now, and where?**

Clusters are sorted **by trouble, not by name**, so the thing you need is at the
top rather than wherever the alphabet put it. Each tile carries reachability,
BNK/DPF presence, and what is currently unhealthy.

---

## Clusters — every resource

A Kubernetes explorer over any registered cluster: pick a cluster and a
namespace, then walk the resource tree.

| Category | Types |
|---|---|
| **Workloads** | Pods, Deployments, StatefulSets, DaemonSets, ReplicaSets |
| **Networking** | Services, Ingresses |
| **Gateway API** | Gateway Classes, Gateways, HTTP/GRPC/TCP/UDP/TLS/L4 Routes, Reference Grants |
| **Config & Storage** | ConfigMaps, Secrets, PVCs |
| **Cluster** | Nodes, Namespaces, CRDs, Storage Classes, Persistent Volumes |
| **cert-manager** | Certificates, Cluster Issuers, Issuers |
| **Helm** | Releases, Chart Browser |

Selecting a resource opens a detail panel with its YAML, events and status.

**What you can do to a pod**, beyond looking at it:

- **Logs** — streamed live over a WebSocket, including previous-container logs
- **Exec** — an interactive shell in the container
- **Restart** — deletes the pod so its controller recreates it
- **Describe / YAML** — the full object

A **DPF** tab appears on a cluster running the NVIDIA DPF operator.

> **Exec and restart are real, and unauthenticated.** Anyone who can reach the
> UI port can use them. See the
> [security posture](../README.md#security-posture-no-authentication-at-all).

---

## BNK Health

The BNK-specific view. The left sidebar is built at runtime from the CRDs the
cluster actually has, so it reflects your install rather than a fixed list.

### Insights

| View | What it answers |
|---|---|
| **Health Dashboard** | Is TMM healthy, and what is degraded |
| **Traffic Flow** | How traffic moves through the gateways |
| **Gateway Topology** | Gateways, listeners, routes and backends as a graph |
| **Policy Gateway Map** | Which policies attach to which gateways |
| **AI Analyzers** | Analyzer runtime metrics and backend health |
| **Upgrade** | Release state, and what an upgrade would change |
| **Diagnostics** | `tmctl`, `configview`, `bdt_cli`, `qkview` — see below |

### Diagnostics

Runs F5's own diagnostic tools inside the TMM pod and shows the output:

- **`tmctl`** — `tmm_stat`, `virtual_server_stat`, `pool_member_stat`,
  `fw_rule_stat`, `rule_stat`, `rst_cause_stat`, `dos_stat`,
  `dns_cache_resolver_stat`, `protocol_inspection_stats`, DOCA flow tables,
  and more
- **`configview`** — the running configuration, by object or UUID
- **`bdt_cli`** — `arp`, `route`, `connection list`, `l2forward`, `check`
- **`qkview`** — collect a support bundle

### Build

**Configuration Builder** and **Policy Builder** generate BNK configuration —
services on TMM — as YAML you can review and copy. They build config; they do
not deploy BNK.

### Resources

Traffic Management (Gateways, routes, Backends), Security (firewall policies and
rule lists, security and network policies, DDoS, address/port lists), Networking
(VLANs, static routes, SNAT pools, egress, iRules), Logging & Telemetry (HSL
publishers, log profiles), System (CNE Instances, BNK Gateway/IPAM, IPAM ranges,
global options, reference grants), and **A2A Protocol** (agent discovery,
templates, iRule library, protocol reference).

---

## TMM Live

Real-time TMM counters — throughput, connections, per-pool-member load, AI token
usage — in Grafana, scoped to the cluster you are looking at.

Prometheus and Grafana come up with `./bnkscope up`. Then, on a cluster that is
not yet streaming, click **Add the exporter**.

### What that does

It adds `tmm-stat-exporter` to every running `f5-tmm` pod as an **ephemeral
container** — the mechanism behind `kubectl debug`. That matters twice:

- **TMM is not restarted.** Ephemeral containers are the one kind you can add to
  a live pod.
- **It works on operator-managed BNK.** A patched Deployment would be reconciled
  away by the operator; a pod's ephemeral containers are not something it
  manages.

The exporter runs non-root with a read-only root filesystem and all capabilities
dropped. It reads the shared `tmstat` segment read-only and pushes outbound. The
image is pinned by bnkscope and is not something a request can choose.

**It is transient.** An ephemeral container does not survive a pod restart, and
nothing re-adds it. Re-inject after a TMM restart.

### Removing it

An ephemeral container cannot be removed from a running pod. The only way to
clear one is to **recreate the TMM pods**, which drops dataplane traffic — so
removal asks you to type the cluster name first, while adding is a single click.
That asymmetry is deliberate.

If you would rather not restart anything, leave it: it disappears on its own at
the pod's next restart.

### Prometheus is reachable from your clusters

Unlike everything else in bnkscope, Prometheus is **not** bound to loopback. The
exporters push to it from inside your clusters, via the host gateway — it has to
be reachable to work at all. It receives metrics and answers queries; it stores
no credentials and can change nothing. Retention is 24 hours.

`./bnkscope up --no-telemetry` skips the stack entirely.

### Already using tmmscope?

[tmmscope](https://github.com/mwiget/tmmscope) still works — if its stack is
running, bnkscope finds and uses it rather than starting its own. Two things stay
CLI-only: `--permanent` injection (both durable modes restart TMM, and one
installs a cluster-scoped webhook with a 10-year CA), and the exporter image
itself, which is built from that repo.

---

## Logs

Everything your clusters have said in the last 24 hours, searchable — the same
window the TMM metrics keep, so a log line and a counter spike can always be put
side by side.

Nothing is injected and nothing is installed. bnkscope pulls the logs through
the Kubernetes API, which is why this is simply on: it uses credentials it
already has. It also means a TMM pod restart does not interrupt it, unlike the
metrics exporter.

### Searching

The filters — cluster, namespace, container, level, time range, and a "contains"
box — compose into a LogQL query, and **that query is shown underneath them**.
Watching the filters write it is the fastest way to learn the language.

When the filters cannot ask your question, **Write LogQL** replaces them
entirely. The labels available are `cluster`, `namespace`, `pod`, `container`
and `level`:

```logql
{cluster="scope", container="f5-tmm"} |= "audit log"
{namespace="dpf-operator-system"} | level="error"
```

A query that does not parse comes back with Loki's own error, so it can be
corrected rather than guessed at.

**Open in Grafana** carries the current query into Grafana Explore, for live
tail and for correlating against the TMM metrics on one timeline.

### What the lines look like

The source — cluster, namespace, pod, container — is printed once per run of
lines rather than on every one, and the cluster and namespace are left off when
a filter has already fixed them. The width belongs to the message.

TMM's syslog envelope is dropped on display:

```
<133>Aug 23 20:52:02 f5-tmm-2lsvg tmm[46]: 01010397:5: throttling.
01010397:5: throttling.
```

The priority, date, host and pid are already shown beside the line. The F5
message id stays — it names the *kind* of event, and is what you search for. The
untouched line is still there on hover.

### Repeats

Most of a 500-line page is the same handful of events restated. Measured on a
live three-cluster estate, 500 lines were 131 distinct events — the rest were
repeats, and the repeats were what you scrolled past to find anything.

So they arrive collapsed: one row per event, showing the **newest** occurrence
and a `×N` count. Hover the count for when the group started and how many pods
it spans. The toolbar says what it did — *131 of 500* — and **Every line**
turns it off; the choice is remembered.

Lines are matched on their *shape*, not their text. Exact matching barely helps
(20% on that sample) because nearly every line carries something that moves — a
timestamp, a byte count, a pod name, a flow cookie. Those are replaced with
placeholders to make the key, so these two are one row:

```
AOF write completed, nwritten: 1024
AOF write completed, nwritten: 4096
```

The shape is only ever a key. The line you read is the newest real one, with
its real values.

What is deliberately **not** collapsed: different F5 message ids, a changed
verdict (`action=drop` vs `action=accept`), and anything from a different
container or cluster. The same event across three TMM replicas *is* one row —
that is the case this helps most — with the pod count on the badge.

---

### Severity

F5 logs numeric syslog severities, inverted (0 is worst), and the `observer`
container uses a different format again. Both are parsed into a `level` label
you can filter on: `emergency`, `alert`, `critical`, `error`, `warning`,
`notice`, `info`, `debug`.

**`unknown` is honest, not broken.** Lines like `SSL profile _grpc_clientssl
loaded successfully` carry no severity at all, so none is invented.

---

## CNF Resources

A read-only browser for F5 custom resources, with navigation built at runtime
from `/crds` rather than a hardcoded list, and status derived from each
resource's own conditions.

---

## AI Gateway

LLM request analytics: an overview with charts and gauges, model rankings, and
provider usage (cost, tokens, latency). A separate **Logs** view lists
individual requests.

---

## System

| Tab | What it is |
|---|---|
| **System Monitor** | API latency, background jobs, resource use. Polls only while the page is open. |
| **Alerts** | Alert channels and their delivery history |
| **Defaults** | Instance-wide defaults |
| **Appearance** | Theme |
| **Backup & Restore** | Snapshot the database and encryption key, and restore one |

---

## MCP

Read-only MCP tools, so an AI agent can query your clusters. It runs with
everything else, bound to loopback:

```bash
./bnkscope up --no-mcp    # if you would rather it did not
```

Every tool is a GET against a route the backend serves. Nothing here writes —
not to your clusters, not to bnkscope's own database. Anything that changes
something lives in the UI, where a person is looking at it.

The page lists the tool catalog and the client setup.

---

## Keyboard shortcuts

Navigation is vim-style — press `G`, then the key:

| | | | |
|---|---|---|---|
| `G` `D` | Overview | `G` `C` | CNF Resources |
| `G` `K` | Clusters | `G` `A` | AI Gateway |
| `G` `B` | BNK Health | `G` `S` | System |
| `G` `T` | TMM Live | `G` `M` | MCP |

`⌘K` opens the command palette; `⌘/` shows this list.

There are deliberately no `⌘`-plus-letter navigation shortcuts: the obvious
choices are Bookmark, Print and Find in every browser.

---

## On a phone or tablet

bnkscope works on a phone, which matters when the thing that broke did so while
you were away from a desk.

- Below 1024px the category tree and detail panel become **drawers** rather than
  columns — the three-pane layout needs 1168px and does not reflow into less.
- Below 768px, **or on any viewport under 500px tall**, the app navigation
  becomes a drawer too. The height rule is what makes a landscape phone behave
  like a phone: rotating one makes it wider without making it roomier.
- A few views — the terminal, the topology graphs, the traffic-flow diagram —
  say what they need instead of drawing something unreadable. **"Show anyway"
  is always offered**, because being told what a tool cannot do is help and
  being prevented is not.

---

## What bnkscope will not do

- **Deploy BNK.** That is [bnk-forge](https://github.com/f5devcentral/bnk-forge).
  The Configuration Builder generates BNK configuration; it does not install it.
- **Manage users.** There are none, and nothing replaces them when you widen
  the bind — see the
  [security posture](../README.md#security-posture-no-authentication-at-all).
  LAN access is for a private lab network or a VPN, nothing else.
- **Write to your machine.** `~/.kube`, `~/.aws`, `~/.config/gcloud` and
  `~/.config/tmmscope` are mounted **read-only**.
- **Run cluster CLI tools.** No `kubectl`, no `aws`, no `gcloud` in the image —
  cloud tokens are minted in Python instead.

---

| | |
|---|---|
| [README](../README.md) | install, commands, security posture |
| [Troubleshooting](TROUBLESHOOTING.md) | when bnkscope itself misbehaves |
| [API reference](API_REFERENCE.md) | the HTTP surface |
| [Development](DEVELOPMENT.md) | build, test, architecture |
