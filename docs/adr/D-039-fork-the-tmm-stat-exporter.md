# D-039: Fork the tmm-stat-exporter into this repository

**Status:** Accepted
**Date:** 2026-08-27
**Extends:** [D-036](D-036-tmmscope-injection-in-bnkscope.md)

---

## Context & Problem Statement

D-036 moved injection into bnkscope and, in its "What this does *not* absorb"
section, deliberately kept the exporter out:

> **The exporter and webhook images.** They are built from the tmmscope repo and
> are the thing doing the actual work. This retires the CLI from the workflow,
> not the dependency.

That left an odd shape. Everything about TMM Live is here — the injection, the
Prometheus receiver, the vendored dashboards, the delivery diagnostics that read
the exporter's own log lines — except the program doing the measuring, which is
built somewhere else from a repository that is being archived.

An archived repository is not immediately broken: the GHCR package stays
pullable and `ghcr.io/mwiget/tmm-stat-exporter:latest` keeps working. But
nothing can rebuild it. No Go toolchain bump, no CVE patch, no fix for a bug we
find while looking at a customer's cluster — and `:latest` on an image nobody
can rebuild is a slow leak, not a stable pin.

The cost of taking it is small, which is what makes this easy. The exporter is
~1,950 lines of Go with one third-party dependency (`golang/snappy`) and no cgo.
`internal/tmstat` is the substantial half: a from-scratch reader for tmm's
`TMSS` shared-memory segment format, validated byte-for-byte against `tmctl`,
with its own test corpus.

## Decision

**Fork `cmd/tmm-stat-exporter` and `internal/tmstat` into `tmm-stat-exporter/`,
and build and publish the image from here.**

- Its own Go module (`github.com/mwiget/bnkscope/tmm-stat-exporter`) — the only
  Go in a Python and TypeScript repository, so it shares no toolchain with
  anything above it and is not part of `make test`.
- `docker-bake.hcl` gains an `exporter` target in the default group; release
  builds it multi-arch, signs it, and attaches an SBOM with the other three.
- `ci.yml` runs `go vet`, `go test` and a Docker build on any change under
  `tmm-stat-exporter/`. Not advisory, unlike the MCP job: this image runs inside
  the operator's TMM pods, so a broken build is found by someone else's cluster.

### What was left behind

The `tmmscope` CLI, the webhook and its `MutatingWebhookConfiguration`, the
ovs-doca exporter, and `internal/promwrite` — the exporter carries its own copy
of the remote_write encoder in `remotewrite.go`, so the shared package was only
ever for the ovs exporter.

### The pin moves once the name exists

`EXPORTER_IMAGE` kept naming `ghcr.io/mwiget/tmm-stat-exporter:latest` in the
commit that landed this ADR: repointing a pinned image at a tag that is not
there turns every injection into an `ImagePullBackOff`, for anyone who upgrades
in the window, on clusters that were streaming fine.

**Done in v0.1.2.** v0.1.1 published `ghcr.io/mwiget/bnkscope-tmm-stat-exporter`
for `linux/amd64` and `linux/arm64`, and the pin now names it.

The tag stays `:latest` rather than tracking bnkscope's own version. Deriving it
from `VERSION` would mean a working tree whose version has not been released yet
injects a tag that does not exist — and an `ImagePullBackOff` inside TMM's pod
is a poor way to find that out. The two are coupled only through the
remote_write contract, which belongs to Prometheus rather than to either of
them.

### Licence

tmmscope is MIT and by the same author; bnkscope is Apache-2.0. The MIT licence
travels with the forked directory (`tmm-stat-exporter/LICENSE`) and governs it.
`NOTICE` records both this fork and the earlier `telemetry/` copy.

## Consequences

- bnkscope can rebuild every part of its own telemetry path. The remaining
  dependency on tmmscope is historical, not operational.
- A second toolchain to keep current: Go 1.26, one CI job, one `go.mod`.
- The fork will drift from upstream, and that is the point — but the divergence
  is now ours to manage rather than something to re-sync. `tmm-stat-exporter/README.md`
  records the commit it was taken from (`3948973`).
- Publishing an image that runs in customer clusters raises the stakes on the
  signing path; the exporter is in `IMAGES` in `scripts/publish-signed-images.sh`
  for that reason.
- Found while wiring the bake target: `docker buildx bake --push default` with
  no `-f` also reads `docker-compose.yml`, which requires
  `BNKSCOPE_GRAFANA_PASSWORD` and fails during parsing — before any target is
  considered. The release job and `make push-images` now pass
  `-f docker-bake.hcl`. This was pre-existing and would have failed the next
  release regardless of this ADR.
