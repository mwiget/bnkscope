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

Retention is 24h on purpose: this is a live-monitoring window, not a long-term
store, and it means a destroyed cluster cleans itself up.

## Updating the dashboards

These are copies. When tmmscope's change, re-copy them rather than editing here,
so the two do not drift:

```sh
cp ~/git/tmmscope/internal/assets/files/grafana/dashboards/*.json telemetry/grafana/dashboards/
```

The `tmm-stat-exporter` image is still built from the tmmscope repo — that is
the part doing the actual work, and vendoring the dashboards does not change it.
