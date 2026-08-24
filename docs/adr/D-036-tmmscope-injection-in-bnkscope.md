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
