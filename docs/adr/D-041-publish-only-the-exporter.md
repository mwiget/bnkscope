# D-041: Publish only the exporter; build bnkscope from source

**Status:** Accepted
**Date:** 2026-08-28
**Amends:** [D-039](D-039-fork-the-tmm-stat-exporter.md)

---

## Context & Problem Statement

D-039 forked the exporter in and added it to `docker-bake.hcl`'s default group,
so a release published four images: `bnkscope-api`, `bnkscope-frontend`,
`bnkscope-mcp` and `bnkscope-tmm-stat-exporter`. Nothing consumed the first
three. `./bnkscope up` builds from source, always, and there was no documented
way to run a published image at all.

So a pull-based install path was written to close that gap: an overlay pinning
the three services to their GHCR tags, a script that pulled and verified them
before handing off to `bnkscope up --no-build`, and a `make deploy-release`
front door. It worked. Then it was tried from a clean clone, which is the case
it existed for, and the run recreated `bnkscope-prometheus`,
`bnkscope-grafana` and `bnkscope-loki` — three containers the pull path does not
touch.

The reason is in `docker-compose.yml`, and it is not incidental:

```
bnkscope-prometheus  ./telemetry/prometheus/prometheus.yml → /etc/prometheus/prometheus.yml
bnkscope-grafana     ./telemetry/grafana/provisioning      → /etc/grafana/provisioning
bnkscope-grafana     ./telemetry/grafana/dashboards        → /var/lib/grafana/dashboards
bnkscope-backend     ./VERSION                             → /app/VERSION
```

Relative bind mounts resolve against the checkout they were invoked from.
Deploying from a second clone silently re-points a live Prometheus and Grafana
at that clone's files; delete it and the next restart gives you a Prometheus
with no configuration and a Grafana with no datasource and no dashboards.

That is the whole case against. A released image did not remove the need for the
repository — it only removed the build — so "install without the source" was
never actually on offer. What was on offer was a second way to get the same
result, with a failure mode that only appears later, on restart, somewhere else.

## Decision

**`docker-bake.hcl`'s default group is the exporter, and nothing else. bnkscope's
own images are built from source by `./bnkscope up`, on the machine that runs
them, and are not published.**

The exporter stays published because it is different in kind, not in degree: it
is injected into `f5-tmm` pods on the operator's clusters, which have no
checkout and can only get it from a registry. An image that crosses that
boundary is exactly the one worth building multi-arch, signing keylessly, and
attaching an SBOM and provenance to.

Removed with the decision: `docker-compose.release.yml`,
`scripts/deploy-release.sh`, `make deploy-release`, the `BNKSCOPE_COMPOSE_EXTRA`
hook in the CLI, and the README section that offered them.

### What this is not

It is not a claim that shipping bnkscope as an image is wrong. It is a claim
that shipping it as an image *while the configuration stays in the repository*
is half a thing, and the half that is missing is the half that bites. Making the
release path genuinely self-contained means `telemetry/` and `VERSION` becoming
image content, and a dashboard edit becoming a release. That is a real design,
and it is not this one.

## Consequences

- One way to run bnkscope. `./bnkscope up` and `upgrade.sh` were always that
  way; now nothing contradicts them.
- Releases get faster and smaller: one Go binary cross-compiled for two
  architectures, rather than three images with arm64 under QEMU. v0.1.2's
  publish job spent most of its time building images nobody pulled.
- `ghcr.io/mwiget/bnkscope-api`, `-frontend` and `-mcp` still exist at `0.1.2`
  and keep working. They will not be updated, so they should be deleted or left
  to be understood as historical — not left looking current.
- CI still builds all three images. That is unchanged and unrelated: those
  builds exist to catch a broken Dockerfile and to enforce the image-size gates,
  not to produce artifacts.
- The supply-chain surface shrinks to the one image that actually leaves this
  machine, which is where signing was always worth the most.
