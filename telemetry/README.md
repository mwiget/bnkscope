# telemetry/

Prometheus and Grafana for TMM Live, vendored from
[tmmscope](https://github.com/mwiget/tmmscope) at `3948973`.

Started with `./bnkscope up --telemetry`, or `BNKSCOPE_TELEMETRY=on`.

| file | from |
|---|---|
| `prometheus/prometheus.yml` | `internal/assets/files/prometheus/` |
| `grafana/provisioning/**` | `internal/assets/files/grafana/provisioning/` |
| `grafana/dashboards/*.json` | `internal/assets/files/grafana/dashboards/` |

**Prometheus here is a receiver, not a scraper.** TMM hooks inbound TCP on its
dataplane interfaces, so the `tmm-stat-exporter` sidecars cannot be scraped —
they push outbound to this host via `remote_write`. That is what
`--web.enable-remote-write-receiver` is for, and why there are no
`scrape_configs`.

The one exception is opt-in: `prometheus/scrape.d/*.yml` holds **site scrape
jobs** for things on your own network that *can* be scraped — a DPU's DOCA
Telemetry Service, a load generator's node-exporter. The directory ships
examples only (`*.yml.example`); real files are git-ignored. After adding or
editing one, `docker kill -s HUP bnkscope-prometheus`. The `DPU offload — live`
dashboard (`grafana/dashboards/dpu-offload.json`, not from tmmscope) reads what
`scrape.d/dts.yml.example` produces.

Retention is 24h on purpose: this is a live-monitoring window, not a long-term
store, and it means a destroyed cluster cleans itself up.

## Updating the dashboards

These are copies. When tmmscope's change, re-copy them rather than editing here,
so the two do not drift:

```sh
cp ~/git/tmmscope/internal/assets/files/grafana/dashboards/*.json telemetry/grafana/dashboards/
```

The exporter that fills these dashboards is vendored too, in
`tmm-stat-exporter/` — it was forked from the same commit, for the same reason.
