"""
NICo service constants — how the NVIDIA Infra Controller is found and dialled.

NICo publishes no CRDs. Its whole model — tenants, VPCs, VIP prefixes, network
segments, load balancers — lives behind the Forge gRPC API on ``nico-api``,
backed by Postgres and Vault. So unlike DPF (``services/dpf``), which reads
Kubernetes objects, this package finds the *deployment* through the Kubernetes
API and then reads the *inventory* over gRPC.
"""

# nico-api's own pod label (Helm chart `nico-api`). The namespace varies by
# install shape, so detection is by label across all namespaces — same rule the
# BNK/DPF footprint probe uses.
NICO_API_LABEL = "app.kubernetes.io/name=nico-api"

# The namespace nico-api is deployed into by `tmmlbctl nico deploy`. Used only
# as the fallback when the pod probe finds nothing (an unreachable pod list
# should not stop the endpoint lookup).
DEFAULT_NAMESPACE = "nico-system"

# The Service that fronts the Forge gRPC API, and its in-cluster port. TLS is
# validated against this SNI whatever address we actually dial — the cert is
# minted for the in-cluster name.
NICO_SERVICE = "nico-api"
NICO_GRPC_PORT = 1079

# Endpoint discovery is by *selector*, not by name: an install can front the
# same pods with more than one Service, and the routable one is not the one
# named `nico-api`. A vanilla NICo site has both
#
#     nico-api           ClusterIP      <none>          1079/TCP
#     nico-api-external  LoadBalancer   10.100.50.240   443:31306/TCP
#
# and only the second is reachable from outside the cluster. So every Service
# in the namespace whose selector matches the nico-api pod is a candidate, and
# `NICO_SERVICE` survives only as the tie-break when two rank equally.
#
# Ranked best-first. An operator-supplied address outranks everything (they
# know what they built); a port-forward is last because it costs an apiserver
# session per fetch and a direct address does not.
ENDPOINT_PREFERENCE = ("override", "loadbalancer", "nodeport", "portforward")

# `cluster.meta_data` key holding an operator-supplied `host:port` for the
# Forge API — their own `ssh -L` or `kubectl port-forward`, or an address only
# they can know about. Lives in meta_data rather than a column for the same
# reason the tmmscope label binding does: no migration for one optional string.
FORGE_ENDPOINT_KEY = "nico_forge_endpoint"

# cert-manager Secret holding the mTLS client cert `tmmlbctl nico deploy` mints.
# Without it there is no way into the Forge API and the inventory stays empty.
ADMIN_CERT_SECRET = "tmm-lb-admin-cert"

# Env var on the nico-api Deployment that selects the admin web UI's auth mode.
# Unset means carbide's default, which is no authentication at all.
WEB_AUTH_ENV = "CARBIDE_WEB_AUTH_TYPE"

# LB providers: the operators that consume NICo and realize what it holds.
# `nico-lb-provider-tmm` (tmm-lb-nico) polls Forge for LoadBalancerServices and
# renders Gateway/L4Route/Pool CRDs into the Kamaji tenant cluster.
PROVIDER_LABEL = "app=nico-lb-provider-tmm"

# Deployment env vars worth surfacing for a provider — they say which gateway
# class it claims, which VIP range it hands out, and which tenant cluster it
# writes to.
PROVIDER_ENV_KEYS = (
    "GATEWAY_CLASS",
    "VIP_CIDR",
    "NICO_ENDPOINT",
    "TENANT_SECRET_NAME",
    "TENANT_SECRET_NAMESPACE",
)

# The stores a NICo site runs on, found by label in their own namespaces. None
# is part of NICo itself, and one of them being down is the usual reason a
# healthy-looking nico-api answers nothing.
#
# `selectors` are tried in order and the first that matches wins, because the
# obvious label is not the one these charts use and both earlier guesses were
# wrong on a vanilla install:
#
#   * NICo's database is the `nico-pg-cluster` Zalando/spilo cluster — the one
#     the `nico-system.nico.nico-pg-cluster.credentials` Secret feeds to
#     nico-api's DATASTORE_*. A vanilla site *also* runs an unrelated standalone
#     `postgres` StatefulSet labelled `app=postgres`, which is what the previous
#     probe matched and reported as NICo's. `app=postgres` survives only as the
#     fallback for an install with no operator.
#   * Vault's Helm chart labels its pods `app.kubernetes.io/name=vault`. The
#     previous `app=vault` matched nothing, so a Vault with an unready or sealed
#     member reported as a healthy dependency with zero pods.
#
# `pod_labels` are surfaced per pod, because for these two the state that
# matters is published as a label rather than inferable from readiness: Vault
# advertises its seal/init/active state and version, spilo advertises which
# member is primary.
DEPENDENCIES = (
    {
        "name": "postgres",
        "namespace": "postgres",
        "selectors": ("application=spilo", "app=postgres"),
        "pod_labels": ("cluster-name", "spilo-role"),
    },
    {
        "name": "vault",
        "namespace": "vault",
        "selectors": ("app.kubernetes.io/name=vault", "app=vault"),
        "pod_labels": (
            "vault-active",
            "vault-initialized",
            "vault-sealed",
            "vault-version",
        ),
    },
    # Not dialled by nico-api itself — it is what the site-controller layer
    # (nico-rest's cloud workers, flow) runs its workflows on. Listed because a
    # vanilla site has one and provisioning stalls without it, which is
    # invisible from anywhere else on this page.
    {
        "name": "temporal",
        "namespace": "temporal",
        "selectors": ("app.kubernetes.io/name=temporal",),
        "pod_labels": ("app.kubernetes.io/component",),
    },
)

# How far back a provider's log is read for current complaints. An operator
# that cannot reach NICo re-logs the failure on every resync (30s), so any
# window comfortably longer than that catches a live problem — the window's job
# is to exclude *history*, not to catch failures. Without it, a single
# cold-start blip stayed the last line of an otherwise silent log and read as
# "failing since Tuesday" for as long as the pod lived.
PROVIDER_LOG_WINDOW_SEC = 3600

# Per-call budget for the Forge RPCs. The endpoint is either routable and
# answers in milliseconds, or it is not — a long timeout only stalls the tab.
FORGE_TIMEOUT = 10.0

# Budget for the TCP screen of one candidate endpoint. A NodePort on an
# unrouted lab subnet black-holes rather than refuses, so this is what bounds
# "is this address worth a TLS handshake".
REACH_TIMEOUT = 2.0

# The tunnel adds an apiserver round trip in front of every Forge call, and
# reflection alone walks a 13-file dependency closure. Measured at ~9s for
# schema load plus first call on the reference lab, so the direct-dial budget
# is not enough.
TUNNEL_TIMEOUT = 30.0
