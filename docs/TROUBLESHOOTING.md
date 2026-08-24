# Troubleshooting bnkscope

When bnkscope itself misbehaves. For troubleshooting *your cluster* with
bnkscope, see the [User Guide](USER_GUIDE.md).

Start here — it answers most of what follows:

```bash
./bnkscope status     # running state, ports, registered clusters
./bnkscope logs       # follow both containers
```

- [It will not start](#it-will-not-start)
- [The UI is not where I expected](#the-ui-is-not-where-i-expected)
- [I cannot reach it from another machine](#i-cannot-reach-it-from-another-machine)
- [A cluster is missing or unreachable](#a-cluster-is-missing-or-unreachable)
- [Exec or logs will not open](#exec-or-logs-will-not-open)
- [TMM Live shows nothing](#tmm-live-shows-nothing)
- [Logs are missing or empty](#logs-are-missing-or-empty)
- [The build fails](#the-build-fails)
- [Root-owned directories in my home](#root-owned-directories-in-my-home)
- [Starting over](#starting-over)
- [Reporting a problem](#reporting-a-problem)

---

## It will not start

`./bnkscope up` checks its prerequisites and says which one failed:

| Message | Fix |
|---|---|
| `docker is required but not on PATH` | Install Docker. |
| `docker compose v2 is required` | You have the v1 `docker-compose` binary. Upgrade Docker, or install the compose v2 plugin. |
| `cannot talk to the Docker daemon` | The daemon is not running, or you are not in the `docker` group (`sudo usermod -aG docker $USER`, then log out and back in). |

If the containers start but immediately restart:

```bash
./bnkscope logs backend
```

A backend that exits at import time is almost always a bad `ENCRYPTION_KEY` or
an unreadable database file. `./bnkscope down --purge` drops both and starts
clean — **it deletes your registered clusters and their credentials.**

---

## The UI is not where I expected

**Ports are negotiated, not assumed.** bnkscope wants 8080 and 8000, but under
host networking it shares the port space with everything else on the machine.
When a port is taken it walks upward and *persists* the choice, so a running
stack keeps its ports across re-runs — and reverts to the default once that
frees up again, unless you asked for a specific port, in which case it stays put.

Do not hard-code the port. Read it back:

```bash
./bnkscope status
./bnkscope endpoint     # the discovery file, for scripts
./bnkscope open         # just open it
```

To pin one:

```bash
BNKSCOPE_UI_PORT=9090 ./bnkscope up
```

---

## I cannot reach it from another machine

**By design.** Both binds are loopback: the API on `127.0.0.1:8000` and the UI
on `127.0.0.1:8080`.

```bash
./bnkscope up --listen 0.0.0.0
```

> **This removes the only access control there is.** No token, no password —
> anyone who can reach the port gets a shell in any pod, and one request to
> `POST /api/system/backup` returns every kubeconfig and cloud credential along
> with the key that decrypts them. Traffic is plain HTTP and readable in flight.

Use it only on a network you would trust with all of that — a private lab
network, or a VPN with the bind pointed at the VPN interface:

```bash
./bnkscope up --listen 100.x.y.z      # e.g. a Tailscale address
```

Otherwise leave the bind at its default and tunnel:

```bash
ssh -N -L 8080:localhost:8080 you@the-host
```

Note that `--listen` governs the UI and Grafana. **Prometheus (`9491`) always
binds `0.0.0.0`**, because your clusters push to it — it cannot be closed
without losing telemetry. Firewall it to your cluster subnets if that matters.

Grafana follows `--listen`, and its dashboards stay **anonymously readable** —
TMM Live embeds them in your browser, so a login there would appear inside
bnkscope's own page rather than protecting anything. That means anyone who can
reach the Grafana port can also query Loki through its datasource proxy, which
is every log line bnkscope has collected. Its *admin* account uses a generated
password (`./bnkscope grafana-password`), because a Grafana admin can point a
datasource at anything.

`./bnkscope status` tells you which of the two you are in.

### macOS and WSL2

`network_mode: host` does not do what it says inside Docker Desktop's VM, so
`bnkscope up` detects those platforms and switches to a bridge overlay that
publishes to `127.0.0.1` only. Clusters reachable only over a VPN route on the
host may not be reachable from inside that VM.

---

## A cluster is missing or unreachable

bnkscope probes every context in `~/.kube/config`. A context that does not
appear as an addable cluster is listed with the reason.

**"This context authenticates with `<command>`, which bnkscope cannot run."**
The image ships no CLI tools. `aws`, `aws-iam-authenticator` and
`gke-gcloud-auth-plugin` are fine — those tokens are minted natively in Python.
**`kubelogin` (AKS) is not**, and there is no Python equivalent. Use a bearer
token instead:

```bash
kubectl create token <serviceaccount> --duration=24h
```

and add the cluster by hand.

**Unreadable cert path.** Only `~/.kube` is mounted. A kubeconfig referring to a
certificate, key or `tokenFile` outside it cannot be resolved — bnkscope inlines
what it can reach and reports what it cannot.

**Reachable before, unreachable now.** Usually an expired credential:

- **EKS** — an expired SSO session. `aws sso login` on the host; bnkscope reads
  `~/.aws` read-only and picks up the refreshed cache. Set `AWS_PROFILE` if you
  use a non-default profile.
- **GKE** — `gcloud auth application-default login`.

**Registered, but BNK does not show.** Detection is by pod labels, not namespace
names. bnkscope looks for `app in (f5-tmm,flo,f5-cne-controller,f5ingress-f5ingress)`
and `app.kubernetes.io/name in (f5-lifecycle-operator,f5ingress,dpf-operator)`.
If your install labels its pods differently, the cluster still registers — it
just will not light up the BNK tab.

---

## Exec or logs will not open

Both are WebSockets to `/api/k8s/clusters/{id}/pods/{pod}/exec` and
`.../logs/follow`. If the rest of the UI works and these do not, something
between the browser and nginx is not passing the upgrade — a corporate proxy or
a TLS-terminating middlebox. Test from the host itself to rule the network out.

The pod also has to have a shell. Distroless containers have none; exec fails
with an exec-format or no-such-file error from the cluster, not from bnkscope.

---

## TMM Live shows nothing

Three things have to be true, and the page says which one is not.

**1. The telemetry stack is running.** It comes up with `./bnkscope up` unless
you passed `--no-telemetry`. Check:

```bash
./bnkscope status          # names the Prometheus and Grafana ports
docker logs bnkscope-prometheus --tail 50
```

**2. The cluster is streaming.** Click **Add the exporter** on TMM Live.
bnkscope does not trust a config file for this — it asks Prometheus whether the
`f5tmm_up` series is arriving right now:

```bash
curl -s localhost:9491/api/v1/query?query=f5tmm_up
```

Empty result, injection reported success? Then the exporter is running but its
pushes are not arriving — see *the exporter cannot reach Prometheus* below.

**3. Your browser can reach Grafana.** Grafana publishes a `localhost` URL. When
you view bnkscope from another machine, `localhost` is *your* laptop — bnkscope
rewrites those URLs to the host you typed in the address bar. If it still will
not load, tunnel it:

```bash
ssh -N -L 3000:localhost:3000 you@the-host
```

### "Could not work out how this cluster reaches your Prometheus"

Injection refuses rather than installing an exporter that pushes into the void —
which would look identical to one that was never injected.

bnkscope derives the address from the TMM pod: a multus edge interface's gateway
first, then the pod's node's, taking the `.1` of the `/24`. Both are heuristics.
When neither applies, supply the URL explicitly:

```bash
curl -X POST localhost:8000/api/tmmscope/clusters/1/injection \
  -H 'content-type: application/json' \
  -d '{"remote_write_url":"http://192.168.1.10:9491/api/v1/write"}'
```

### The exporter cannot reach Prometheus

Prometheus is deliberately **not** loopback-bound — the pods push to it. If the
series never arrive, the path from cluster to host is what to check: a host
firewall on the Prometheus port, or a pod network with no route back to the
host.

### It was streaming, and stopped

Most likely the TMM pod restarted. Injection is **ephemeral**: the container does
not survive a pod restart, and nothing re-adds it. Click **Add the exporter**
again.

TMM Live shows this as a partial state when only some pods came back clean.

### Ports moved

Prometheus defaults to 9491 and Grafana to 3000, and both walk upward when taken
— by another tool, or by a tmmscope stack still running. `./bnkscope status`
prints where they landed. bnkscope will not move a *running* stack's ports back;
`./bnkscope down` then `up` reclaims the defaults once they are free.

---

## Logs are missing or empty

Collection is on by default and pulls through the Kubernetes API — nothing is
installed on your clusters, so there is nothing on them to check.

**Nothing at all, and the page says the log store is not running.** Loki and the
collector start with the telemetry stack:

```bash
./bnkscope status
docker logs bnkscope-loki --tail 30
docker logs bnkscope-alloy --tail 30
```

**One cluster missing while others work.** The collector only knows the clusters
bnkscope publishes to it, and only those whose stored kubeconfig it could read:

```bash
docker exec bnkscope-backend ls -l /telemetry/clusters   # one file per cluster
docker logs bnkscope-backend 2>&1 | grep -i "log collector"
```

A cluster whose credentials could not be decrypted or normalised is skipped with
a warning rather than failing the rest. Re-adding the cluster rewrites it.

**It worked, then stopped, on a cloud cluster.** EKS and GKE kubeconfigs carry a
minted token good for about an hour. bnkscope rewrites them every 10 minutes;
if that job is not running, the collector keeps using an expired one and the
symptom is silence:

```bash
docker logs bnkscope-backend 2>&1 | grep -i "log collector config"
```

**Everything is `level=unknown`.** Expected for lines that carry no severity —
TMM logs plenty of those. If lines that clearly *do* have an F5 message id
(`01010397:5:`) are also unknown, the parsing broke; the pipeline is generated
into `/telemetry/config.alloy` and can be read directly.

**Nothing older than a few hours.** Retention is 24h, matching Prometheus. Loki
also refuses entries far outside its window, so a cluster whose clock is badly
skewed will have its logs rejected — `docker logs bnkscope-alloy` reports that
as `entry too far behind`.

---

## The build fails

**Behind a pull-through registry cache.** Official Docker Hub images need the
`library/` prefix through a mirror — `node:20-alpine` resolves, but
`<mirror>/node:20-alpine` does not; it has to be `<mirror>/library/node:20-alpine`.
bnkscope handles this when it detects the cache. Control it explicitly:

```bash
BNKSCOPE_REGISTRY_CACHE=off ./bnkscope up    # ignore the cache
BNKSCOPE_REGISTRY_CACHE=on  ./bnkscope up    # fail if it is not running
```

**Behind a TLS-intercepting proxy.** See
[D-035](adr/D-035-docker-netskope-tls-interception.md).

To skip the build entirely and use what you already have:

```bash
./bnkscope up --no-build
```

---

## Root-owned directories in my home

`./bnkscope up` creates `~/.kube`, `~/.aws`, `~/.config/gcloud` and
`~/.config/tmmscope` **as you** before starting the stack, because Docker would
otherwise create the missing ones as empty root-owned directories inside your
home. That is why it is the supported entry point rather than a bare
`docker compose up`.

If a bare `docker compose up` already did this:

```bash
sudo chown -R "$USER:$USER" ~/.aws ~/.config/gcloud
```

---

## Starting over

```bash
./bnkscope down            # stop, keep the database
./bnkscope down --purge    # stop and drop the database and encryption key
```

`--purge` deletes every registered cluster and its stored credentials. Your
kubeconfig is untouched — everything is mounted read-only — so the next
`./bnkscope up` rediscovers your clusters from scratch.

---

## Reporting a problem

```bash
./bnkscope status
docker logs --tail 200 bnkscope-backend
docker logs --tail 200 bnkscope-frontend
docker version
```

(`./bnkscope logs` follows the stream, which is what you want while watching and
not what you want while capturing.)

> **Redact before sharing.** Logs can contain cluster names, API server URLs and
> namespace names.

Issues: <https://github.com/mwiget/bnkscope/issues>
