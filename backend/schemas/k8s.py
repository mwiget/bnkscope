"""
Pydantic schemas for the Kubernetes domain.

Request schemas (ClusterCreateRequest, ResourceCreateRequest, etc.) are
defined in routes/k8s/_shared.py. This file adds RESPONSE schemas.
"""

import re
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from models.enums import ConnectivityStatus

# Compiled at module load — used by CreateMigrationRequest.validate_kubectl_resources.
# Requires "kind/name" (slash mandatory) optionally followed by one namespace token
# (whitespace-separated).  Rejects leading dashes (kubectl flags), embedded newlines,
# and shell metacharacters.
_KUBECTL_RESOURCE_RE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*([ \t]+[A-Za-z0-9][A-Za-z0-9._-]*)?\Z",
    re.ASCII,
)

class PlatformCapabilities(BaseModel):
    secondary_networks: bool | None = None
    network_attachment_definitions: bool | None = None
    sriov: bool | None = None
    hugepages: bool | None = None
    gateway_api: bool | None = None
    openshift_routes: bool | None = None
    scc: bool | None = None
    machine_config: bool | None = None
    operator_framework: bool | None = None
    cloud_load_balancer: bool | None = None

class PlatformConstraints(BaseModel):
    managed_control_plane: bool | None = None
    cluster_lifecycle_external: bool | None = None
    operator_required_for_networking: bool | None = None
    privileged_workloads_require_platform_security_binding: bool | None = None
    direct_node_package_mutation_not_supported: bool | None = None

# =============================================================================
# Cluster Responses
# =============================================================================

class BnkClusterConfigSummary(BaseModel):
    id: int
    cluster_id: int
    tmfifo_pool_cidr: str = "192.168.100.0/22"
    join_transport: str = "rshim"
    control_plane_host_id: int | None = None
    # Current membership (ADR-424 #4): IDs of hosts/DPUs whose
    # kubernetes_cluster_id == cluster_id. Lets the member dialog seed its
    # selection from real membership instead of re-applying the B-all default
    # on every open (which silently steals members from sibling clusters).
    host_ids: list[int] = Field(default_factory=list, description="IDs of hosts currently in this cluster")
    dpu_ids: list[int] = Field(default_factory=list, description="IDs of DPUs currently in this cluster")

class ClusterSummary(BaseModel):
    """Single cluster in list response."""
    id: int
    name: str
    context: str | None = None
    api_server: str | None = None
    version: str | None = None
    status: str = "active"
    cloud_provider: str | None = None
    detected_platform_profile: str = "unknown"
    detected_platform_provider: str | None = None
    platform_capabilities: PlatformCapabilities = Field(default_factory=PlatformCapabilities)
    platform_constraints: PlatformConstraints = Field(default_factory=PlatformConstraints)
    region: str | None = None
    default_namespace: str = "default"
    enabled_prerequisites: list[str] | None = None
    # Written by discovery; `has_dpf` gates the DPF tab.
    meta_data: dict[str, Any] | None = None
    bnk_config: BnkClusterConfigSummary | None = None
    node_count: int | None = None
    # ADR-478/494: release FK ids — deployable = intent (set at deploy time);
    # running = observed (set by discovery scan). Both nullable.
    running_release_id: int | None = None
    last_synced_at: str | None = None
    created_at: str | None = None
    updated_at: str | None = None

class ClusterListResponse(BaseModel):
    """Response for GET /api/k8s/clusters."""
    clusters: list[ClusterSummary]
    count: int | None = None

class ClusterDetailResponse(BaseModel):
    """Response for GET /api/k8s/clusters/{id}."""
    id: int
    name: str
    context: str | None = None
    api_server: str | None = None
    version: str | None = None
    status: str = "active"
    cloud_provider: str | None = None
    detected_platform_profile: str = "unknown"
    detected_platform_provider: str | None = None
    platform_capabilities: PlatformCapabilities = Field(default_factory=PlatformCapabilities)
    platform_constraints: PlatformConstraints = Field(default_factory=PlatformConstraints)
    region: str | None = None
    default_namespace: str = "default"
    enabled_prerequisites: list[str] | None = None
    meta_data: dict[str, Any] | None = None
    # ADR-478/494: release FK ids — deployable = intent (set at deploy time);
    # running = observed (set by discovery scan). Both nullable.
    running_release_id: int | None = None
    last_synced_at: str | None = None
    created_at: str | None = None
    updated_at: str | None = None

class ClusterCreateResponse(BaseModel):
    """Response for POST /api/k8s/clusters — returns the created cluster."""
    id: int
    name: str
    context: str | None = None
    api_server: str | None = None
    cloud_provider: str | None = None
    detected_platform_profile: str = "unknown"
    detected_platform_provider: str | None = None
    platform_capabilities: PlatformCapabilities = Field(default_factory=PlatformCapabilities)
    platform_constraints: PlatformConstraints = Field(default_factory=PlatformConstraints)
    region: str | None = None
    default_namespace: str = "default"
    status: str = "active"

# ============================================================================
# Local kubeconfig discovery
# ============================================================================

class DiscoveryCandidate(BaseModel):
    """One context from the operator's kubeconfig, and what discovery did with it."""

    context: str
    api_server: str | None = None
    cloud_provider: str = "on-prem"
    auth_method: str = "anonymous"
    source_path: str
    # reachable | unreachable | unusable. "unusable" means the probe never ran:
    # the context references a file bnkscope cannot read, or an exec plugin it
    # cannot execute. `detail` says which.
    state: str
    registered: bool = False
    cluster_id: int | None = None
    has_bnk: bool = False
    # The DPF operator is on this cluster. On a real deployment that is a
    # *different* cluster from the BNK one — the infra cluster that provisions
    # the Kamaji tenant BNK runs on.
    has_dpf: bool = False
    # Which F5/DPF components were actually found, by label.
    components: list[str] = Field(default_factory=list)
    version: str | None = None
    detail: str | None = None

class DiscoveryResponse(BaseModel):
    """Response for GET/POST /api/k8s/discovery."""

    candidates: list[DiscoveryCandidate] = Field(default_factory=list)
    found: int = 0
    registered: int = 0

class DiscoveryAdoptRequest(BaseModel):
    """Register one context by name.

    Only the name travels: the kubeconfig is re-read from the host on every
    call, so a client cannot inject credentials through this endpoint.
    """

    context: str = Field(min_length=1, max_length=253)

class ClusterOperationResponse(BaseModel):
    """Generic response for cluster mutations (delete)."""
    success: bool = True
    message: str | None = None
    cluster_id: int | None = None

class ClusterConnectionTestResponse(BaseModel):
    """Response for POST /api/k8s/clusters/{id}/test."""
    success: bool
    message: str
    cluster_name: str | None = None
    version: str | None = None
    api_server: str | None = None
    cloud_provider: str | None = None
    region: str | None = None
    status_code: int | None = None

# =============================================================================
# Namespace / Node Responses
# =============================================================================

class NamespaceInfo(BaseModel):
    """Single namespace."""
    name: str
    status: str | None = None
    labels: dict[str, str] | None = None
    created_at: str | None = None

class NamespaceListResponse(BaseModel):
    """Response for GET /api/k8s/clusters/{id}/namespaces."""
    namespaces: list[NamespaceInfo]
    count: int | None = None
    cluster_id: int

class NodeCountResponse(BaseModel):
    """Response for GET /api/k8s/clusters/{id}/nodes/count."""
    node_count: int
    cluster_id: int

# =============================================================================
# Resource Responses
# =============================================================================

class ResourceListEnvelope(BaseModel):
    """Typed envelope for GET /api/k8s/clusters/{id}/resources/{type}."""

    resources: list[dict[str, Any]]
    count: int
    resource_type: str
    namespace: str | None = None
    cluster_id: int
    info: str | None = None

class ResourceDescribeEnvelope(BaseModel):
    """Typed envelope for GET /api/k8s/clusters/{id}/resources/{type}/{name}/describe."""

    name: str
    namespace: str | None = None
    kind: str
    api_version: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    spec: dict[str, Any] = Field(default_factory=dict)
    status: dict[str, Any] = Field(default_factory=dict)
    conditions: list[dict[str, Any]] = Field(default_factory=list)
    events: list[dict[str, Any]] = Field(default_factory=list)
    relationships: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)
    cluster_id: int
    resource_type: str
    resource_name: str

class PodLogsResponse(BaseModel):
    """Typed response for GET /api/k8s/clusters/{id}/pods/{name}/logs."""

    logs: str
    pod_name: str
    namespace: str
    cluster_id: int
    container: str | None = None

class ClusterEventsResponse(BaseModel):
    """Typed response for GET /api/k8s/clusters/{id}/events."""

    events: list[dict[str, Any]]
    count: int
    cluster_id: int
    namespace: str | None = None
    resource_type: str | None = None
    resource_name: str | None = None
    event_type: str | None = None

class PodTopResponse(BaseModel):
    """Typed response for GET /api/k8s/clusters/{id}/top/pods."""

    available: bool
    metrics: list[dict[str, Any]] | None = None
    error: str | None = None
    cluster_id: int
    namespace: str | None = None
    sort_by: str | None = None

class NodeTopResponse(BaseModel):
    """Typed response for GET /api/k8s/clusters/{id}/top/nodes."""

    available: bool
    metrics: list[dict[str, Any]] | None = None
    error: str | None = None
    cluster_id: int
    sort_by: str | None = None

class PodRestartResponse(BaseModel):
    """Typed response for POST /api/k8s/clusters/{id}/pods/{name}/restart."""

    success: bool
    message: str
    pod_name: str
    namespace: str
    cluster_id: int

# =============================================================================
# Scan / Adaptive Module Responses
# =============================================================================

class ClusterScanEnvelope(BaseModel):
    """Typed envelope for POST /api/k8s/clusters/{id}/scan."""

    cluster_id: int
    cluster_name: str
    cluster_info: dict[str, Any]
    prerequisites: dict[str, Any]
    bnk_install: dict[str, Any]
    recommendations: list[dict[str, Any]]
    enabled_prerequisites: list[str] = Field(default_factory=list)
    scan_metadata: dict[str, Any]
    platform_context: dict[str, Any] | None = None

# =============================================================================
# HugePages Deploy (Recommendation Action)
# =============================================================================

class HugePagesDeployRequest(BaseModel):
    """Request body for POST /api/k8s/clusters/{id}/recommendations/hugepages/deploy.

    ``size`` drives the per-node 2Mi page count via the F5 BNK sizing table
    (small=1536, medium=3072, large=6144, max=12288).
    """
    size: Literal["small", "medium", "large", "max"]
    namespace: str = Field(default="kube-system", max_length=253)
    image: str | None = Field(
        default=None,
        description=(
            "Override for the tuner container image. Defaults to the "
            "BNK_FORGE_HUGEPAGES_IMAGE env var, then busybox:1.36.1. "
            "Airgapped clusters should point this at a mirrored image."
        ),
        max_length=512,
    )

class HugePagesDeployResponse(BaseModel):
    """Response for the HugePages deploy action."""
    success: bool
    job_name: str
    namespace: str
    size: str
    page_count: int
    memory_gib_per_node: float
    target_node_count: int
    target_nodes: list[str]
    image: str
    message: str

# =============================================================================
# Node Readiness Probe (issue #387 part A — detection only)
# =============================================================================

class NodeReadinessProbeRequest(BaseModel):
    """Request body for POST /api/k8s/clusters/{id}/node-readiness/probe."""
    namespace: str = Field(default="kube-system", max_length=253)
    image: str | None = Field(
        default=None,
        description=(
            "Override for the probe container image. Defaults to the "
            "BNK_FORGE_NODEPROBE_IMAGE env var, then busybox:1.36.1. "
            "Airgapped clusters should point this at a mirrored image."
        ),
        max_length=512,
    )

class NodeCniPlugins(BaseModel):
    """Presence of the CNI delegate plugins F5 BNK's data plane requires."""
    macvlan: bool = False
    host_device: bool = False
    ipvlan: bool = False

class NodeReadinessResult(BaseModel):
    """Per-node CNI/core_pattern/hugepages readiness, from the privileged probe."""
    node: str
    cni_plugins: NodeCniPlugins
    cni_ok: bool
    core_pattern: str | None = None
    core_pattern_ok: bool
    hugepages_2mi: str | None = None
    hugepages_ok: bool

class NodeReadinessProbeResponse(BaseModel):
    """Response for POST /api/k8s/clusters/{id}/node-readiness/probe."""
    cluster_id: int
    job_name: str
    is_kind: bool
    is_local: bool
    nodes: list[NodeReadinessResult]
    all_ready: bool
    message: str

# =============================================================================
# Resource Type Catalog
# =============================================================================

class ResourceTypeCatalogItem(BaseModel):
    """Single supported resource type from core.k8s_resource_registry."""

    key: str
    kind: str
    api_group: str
    api_version: str
    plural: str
    namespaced: bool
    display_name: str
    description: str
    category: str

class ResourceTypeCatalogResponse(BaseModel):
    """Typed response for GET /api/k8s/resource-types."""

    resource_types: list[ResourceTypeCatalogItem]
    count: int

# =============================================================================
# Tunnel Responses
# =============================================================================

# =============================================================================
# Connectivity Probe Responses
# =============================================================================

class ConnectivityIcmpResult(BaseModel):
    """ICMP ping result."""
    reachable: bool = False
    latency_ms: float | None = None

class ConnectivityTcpResult(BaseModel):
    """TCP port probe result."""
    open: bool = False
    connect_ms: float | None = None
    port: int | None = None

class ConnectivityK8sApiResult(BaseModel):
    """K8s API /version probe result."""
    accessible: bool = False
    version: str | None = None
    status_code: int | None = None

class ClusterConnectivityResponse(BaseModel):
    """Response for GET /api/k8s/clusters/{id}/connectivity."""
    cluster_id: int
    cluster_name: str
    api_server: str | None = None
    status: ConnectivityStatus  # Canonical: connected | reachable | partial | unreachable | unknown
    message: str
    suggestion: str | None = None
    icmp: ConnectivityIcmpResult
    tcp: ConnectivityTcpResult
    k8s_api: ConnectivityK8sApiResult
    checked_at: str

class ConnectivitySummary(BaseModel):
    """Summary counts for batch connectivity check (canonical vocabulary)."""
    total: int = 0
    connected: int = 0
    reachable: int = 0
    partial: int = 0
    unreachable: int = 0
    unknown: int = 0

class BatchConnectivityResponse(BaseModel):
    """Response for GET /api/k8s/clusters/connectivity."""
    results: list[ClusterConnectivityResponse]
    summary: ConnectivitySummary

# =============================================================================
# CRD Discovery (D-018)
# =============================================================================

class CRDInfo(BaseModel):
    """Single discovered CRD, optionally enriched with static registry metadata."""

    name: str
    """<plural>.<group> — stable identity key consumed by P2 CNF dashboard."""
    kind: str
    plural: str
    group: str
    version: str | None = None
    namespaced: bool = False
    display_name: str | None = None
    category: str | None = None
    source: str = "discovered"
    """'discovered' | 'registry-enriched'"""

class CrdListEnvelope(BaseModel):
    """Response for GET /api/k8s/clusters/{cluster_id}/crds."""

    crds: list[CRDInfo]
    count: int
    cluster_id: int
    group_filter: list[str] | None = None
    info: str | None = None
    """Non-null only for the reachable-but-empty case (no error, just no matches)."""

# =============================================================================
# Topology (D-018 P4)
# =============================================================================

class TopologyNode(BaseModel):
    """A single node in the topology graph (Service, Pod, or owning workload)."""

    id: str
    """Stable unique id: f"{kind}/{namespace}/{name}"."""
    kind: str
    """Pod | Service | Deployment | StatefulSet | DaemonSet"""
    name: str
    namespace: str
    uid: str | None = None
    severity: str = "unknown"
    """healthy | degraded | unhealthy | unknown"""
    meta: dict[str, Any] = Field(default_factory=dict)
    """Free meta bag: phase, ready_replicas, replicas, container_count, etc."""

class TopologyEdge(BaseModel):
    """A directed edge in the topology graph."""

    id: str
    source: str
    """id of the source TopologyNode."""
    target: str
    """id of the target TopologyNode."""
    kind: str
    """'selects' (Service→Pod, animated) | 'owns' (Workload→Pod, static)."""

class TopologyGraphResponse(BaseModel):
    """Response for GET /api/k8s/clusters/{cluster_id}/topology."""

    nodes: list[TopologyNode]
    edges: list[TopologyEdge]
    cluster_id: int
    namespace: str
    info: str | None = None
    """Non-null when results are truncated or namespace-cardinality guard fires."""

# =============================================================================
# Proxy Translation (D-021 P2)
# =============================================================================

# =============================================================================
# Proxy Migration (D-021 P3)
# =============================================================================

class CreateMigrationRequest(BaseModel):
    """Request body for POST /api/k8s/clusters/{id}/proxies/migrate.

    Caller must have already run the translate endpoint to get combined_yaml.
    """

    source_descriptor: dict[str, Any] = Field(
        description=(
            "Descriptor of the source proxy "
            "(proxy_type, source_kind, class_name, namespace, gateway_name, gateway_namespace, etc.)"
        ),
    )
    combined_yaml: str = Field(
        description="Multi-doc YAML from the translate endpoint (combined_yaml field).",
    )
    project_id: int | None = Field(
        default=None,
        description="Optional project scope.",
    )
    teardown_info: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Optional old-proxy teardown hint. Keys: helm_release, helm_namespace, "
            "kubectl_resources (list of 'kind/name namespace' strings). "
            "If omitted, teardown step is surfaced as a manual action."
        ),
    )

    @field_validator("teardown_info", mode="before")
    @classmethod
    def validate_kubectl_resources(cls, v: Any) -> Any:
        """Validate teardown_info.kubectl_resources elements are safe 'kind/name [namespace]' strings.

        Rejects leading dashes (e.g. --all), empty strings, and any token that
        doesn't match the expected kind/name format to prevent kubectl flag injection.
        """
        if not isinstance(v, dict):
            return v
        resources = v.get("kubectl_resources")
        if resources is None:
            return v
        if not isinstance(resources, list):
            raise ValueError("teardown_info.kubectl_resources must be a list of strings")
        for item in resources:
            if not isinstance(item, str):
                raise ValueError(
                    f"teardown_info.kubectl_resources element must be a string, got {type(item).__name__!r}"
                )
            stripped = item.strip()
            if not stripped:
                raise ValueError(
                    "teardown_info.kubectl_resources contains an empty string — each element must be 'kind/name [namespace]'"
                )
            if not _KUBECTL_RESOURCE_RE.match(stripped):
                raise ValueError(
                    f"teardown_info.kubectl_resources element {stripped!r} is not a valid 'kind/name [namespace]' "
                    "token. Elements must not start with '-' or contain shell metacharacters."
                )
        return v

# =============================================================================
# CIS Translation (D-023 P3)
# =============================================================================

