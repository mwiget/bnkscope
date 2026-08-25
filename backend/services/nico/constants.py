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

# Supporting stores NICo cannot run without, found by label in their own
# namespaces. Neither is part of NICo itself; both being down is the usual
# reason a healthy-looking nico-api answers nothing.
DEPENDENCY_PODS = (
    ("postgres", "postgres", "app=postgres"),
    ("vault", "vault", "app=vault"),
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
