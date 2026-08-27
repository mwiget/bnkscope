# D-036: Inject the TMM exporter from bnkscope, ephemerally

**Status:** Accepted
**Date:** 2026-08-23
**Amends:** the Phase 7 decision in `docs/BNKSCOPE_PLAN.md` §Phase 7

---

## Context & Problem Statement

Phase 7 integrated tmmscope by reading its discovery file, asking Prometheus
what was streaming, and embedding the dashboard. Anything that *changed* state
was printed as a command for the operator to run on the host. The stated reason:

> `tmmscope up` needs the Docker socket and `tmmscope inject` needs `kubectl`,
> and neither belongs inside a container with no authentication in front of it.

In practice this makes TMM Live a dead end. A newly added BNK cluster shows up,
is not streaming, and the page's answer is "go to a terminal". The operator has
a working kubeconfig loaded in bnkscope already.

Two of the three clauses in that rationale turn out not to hold.

### `tmmscope inject` does not need kubectl

`tmmscope inject` has three mechanisms, and only one of them is right for BNK:

| mode | mechanism | works on operator-managed BNK? | restarts TMM? |
|---|---|---|---|
| patch | strategic merge on the Deployment | **no** — the operator reconciles it away | yes |
| webhook | `MutatingWebhookConfiguration` + webhook Deployment + self-signed CA, then delete the pods | yes | **yes** |
| **ephemeral** | the `pods/{name}/ephemeralcontainers` subresource | **yes** | **no** |

Ephemeral is tmmscope's own default, precisely because it does not restart TMM.
It is a single Kubernetes API call — `patch_namespaced_pod_ephemeralcontainers`,
present in the client already in our image — against a cluster bnkscope holds an
authenticated client for. The kubectl dependency is an implementation detail of
the Go CLI, not of the operation.

### "No mutations here" was already untrue

bnkscope ships WebSocket **pod exec**, pod restart, deployment rollout restart,
scale, and platform-restart — 30 mutating endpoints under `/k8s`. Anyone who can
reach the UI can already open a root-capable shell inside TMM.

Injecting a **pinned, non-root, read-only-rootfs, all-capabilities-dropped**
sidecar that reads a shared memory segment and pushes outbound is *strictly less*
powerful than the exec endpoint that has been there since before Phase 7.

The security boundary is `--listen`, and it always was. This decision does not
move it.

## Decision

**Add inject and remove to bnkscope, ephemeral mode only, with the exporter
image pinned server-side.**

- `POST   /api/tmmscope/clusters/{id}/injection` — inject
- `DELETE /api/tmmscope/clusters/{id}/injection` — remove
- `GET    /api/tmmscope/clusters/{id}/injection` — per-pod state

Injection adds the exporter as an ephemeral container to every running `f5-tmm`
pod, and is idempotent: a pod already carrying it is skipped, not duplicated.

### The image is not a parameter

`SidecarSpec` is built server-side from a pinned image constant. The request body
carries no image, no command, no volume mounts, no security context.

Accepting an image from the request body would turn "inject" into "run an
arbitrary container inside TMM's pod, with its tmstat segment mounted" — which
*would* be a meaningful expansion of the blast radius, and is the one part of
this that genuinely needs to stay shut.

### Remove is a confirmation, not a click

**Ephemeral containers cannot be removed in place.** The only way to clear one
is to recreate the pod, which drops dataplane traffic.

So the two directions are deliberately asymmetric:

- **inject** — one click. Non-destructive, no restart, reversible by attrition.
- **remove** — a confirmation that says, in words, that it recreates the TMM pods
  and drops traffic.

A troubleshooting tool that makes a traffic-dropping action as easy as a
non-destructive one has mislabelled the risk.

### The host command stays visible

The `tmmscope inject` command remains on the page. Two reasons: it is the escape
hatch when injection fails for a reason bnkscope cannot fix, and it is the only
path to `--permanent` (the patch and webhook modes), which we deliberately do not
implement.

> **Amended 2026-08-27: it does not.** The command is gone from the inject
> panel. Both reasons turned out to be weaker than the cost of printing it.
>
> It is not much of an escape hatch: `tmmscope inject` is a Go binary the
> operator may not have and the page never said where to get it, so the "hatch"
> asked someone whose injection just failed to go install a second tool.
>
> Nor is `--permanent` the only durable path — the cluster builders
> (tmmlitectl/ocibnkctl, DPF's DPUService templates) ship the sidecar in the pod
> template already, and on operator-managed BNK the patch mode is reconciled
> away, so the hint's "the only way to get a durable sidecar" was wrong twice
> over.
>
> What it *did* do reliably was imply that bnkscope needs tmmscope installed to
> stream telemetry. It does not: `bnkscope up` brings its own Prometheus and
> Grafana (`telemetry/`, vendored) and injects through the Kubernetes API. The
> only thing that still comes from tmmscope is the exporter image, which the
> cluster pulls from GHCR.
>
> The commands aimed at a sidecar bnkscope did **not** install are gone for the
> same reason, and a worse one: `tmmscope eject` only undoes `tmmscope inject
> --permanent`. It does nothing for the sidecar a cluster builder shipped in the
> pod template, which is where most permanent exporters come from — so the page
> printed one tool's command for a state several tools can produce.
>
> Those panels now **name the owning workload** instead (`DaemonSet f5-tmm`,
> `Deployment f5-tmm`), resolved from the pod's `ownerReferences` — one hop
> through the ReplicaSet, which is generated and not what anyone edits. That is
> what "remove it where it is defined" was always trying to say, and it is true
> however the sidecar got there. `remove()`'s refusal message names it too.
>
> With no consumer left, `inject_command` and `eject_command` are gone from the
> `/api/tmmscope/clusters/{id}` response, and `TmmLive` prints no `tmmscope`
> command in the injection or removal flow at all. `tmmscope up` remains on the
> "no telemetry stack" panel: bnkscope still uses that stack when it finds it,
> and that is a fallback, not an instruction.

## What this does *not* absorb

- **`tmmscope up`** — Prometheus and Grafana. Needs the Docker socket; that
  clause of the Phase 7 rationale still stands. Increment B moves the stack into
  bnkscope's own compose file instead.
- **The exporter and webhook images.** They are built from the tmmscope repo and
  are the thing doing the actual work. This retires the CLI from the workflow,
  not the dependency.
- **Permanent injection.** Both durable modes restart TMM; the webhook mode also
  installs a cluster-scoped `MutatingWebhookConfiguration` with a 10-year
  self-signed CA. Neither is something a troubleshooting tool should do behind a
  button.

## Consequences

- TMM Live stops being a dead end for a freshly added cluster.
- Injection is transient by construction: it does not survive a pod restart, and
  nothing re-adds it. This is the honest shape for a troubleshooting tool, and it
  must be *said*, not discovered.
- bnkscope gains no CLI tools, no Docker socket, and no new image.
- The remote-write URL derivation (multus gateway → node gateway → the `.1` of
  the `/24`) is reimplemented in Python. It is a heuristic in tmmscope too, and
  it can fail; when it does, say so rather than injecting an exporter that
  silently pushes nowhere.
- The Phase 7 wording "read-only by construction" is no longer accurate for this
  route module and is corrected there.

## References

- `tmmscope`: `internal/inject/ephemeral.go`, `inject.go`, `probe.go`
- Phase 7, `docs/BNKSCOPE_PLAN.md`
- [D-019](D-019-dynamic-by-default.md) — evidence over configuration
