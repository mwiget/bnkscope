# tmm-stat-exporter

The sidecar TMM Live injects into `f5-tmm` pods. It reads tmm's tmstat
shared-memory segments directly — no `tmctl`, no cgo, stdlib plus snappy — and
**pushes** the counters to Prometheus via `remote_write` every two seconds.

Pushing rather than being scraped is not a preference. TMM hooks inbound TCP on
its dataplane interfaces, so a sidecar's listening port is unreachable from
outside the pod: a scrape can never arrive. `/metrics` is still served for
debugging from inside the pod's netns.

## Provenance

Forked from [tmmscope](https://github.com/mwiget/tmmscope) at `3948973`
(`cmd/tmm-stat-exporter` + `internal/tmstat`), which is MIT-licensed and by the
same author. `LICENSE` here is that MIT licence, and it governs this directory;
the rest of bnkscope is Apache-2.0.

It was vendored because bnkscope had come to depend on an image it could not
build. Everything else about TMM Live lives here — the injection, the Prometheus
receiver, the dashboards — and the one piece doing the actual measuring was
built somewhere else, from a repository heading for the archive.

What was left behind: the `tmmscope` CLI, the webhook and its
`MutatingWebhookConfiguration`, the ovs-doca exporter, and `internal/promwrite`
(the exporter carries its own copy of the remote_write encoder in
`remotewrite.go`).

## Build

```sh
make exporter-test     # go test ./...
make exporter-image    # local single-arch image, tmm-stat-exporter:dev
```

Release builds are multi-arch and go through `docker-bake.hcl` with everything
else — see the `exporter` target there.

## Where it is used

`backend/services/tmmscope_inject_service.py` pins the image and builds the
ephemeral-container spec: non-root (65532), read-only rootfs, every capability
dropped, `/var/tmstat` mounted read-only. The DSSM client cert is mounted only
when the pod already declares it, which is what lets the AI-token counters be
read out of DSSM/Redis. [D-036](../docs/adr/D-036-tmmscope-injection-in-bnkscope.md)
is the reasoning.
