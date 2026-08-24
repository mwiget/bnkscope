"""Canonical MCP tool catalog for MCP governance/productization.

Slice 11 compatibility/deprecation policy (lightweight, enforced):
- Full coverage for governed modules:
  system, cluster_management, helm, config_management, iac_operations, bnk_operations
- Lifecycle metadata is mandatory on every entry:
  `stability`, `since_version`, `deprecated`, `replacement_tool`
- Deprecated tools remain callable during a documented compatibility window;
  removal must be an explicit follow-up change (never silent).
- If `replacement_tool` is set, it must reference a real, different tool.

The catalog is intentionally not full-server coverage yet. Tests enforce that covered
modules stay fully cataloged and that all catalog entries stay URL-audit aligned.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum


class ToolRiskClass(str, Enum):
    """Simple risk classes for MCP productization/safety workflows."""

    READ_ONLY = "read_only"
    MUTATING = "mutating"
    DESTRUCTIVE = "destructive"


class ToolAuthExpectation(str, Enum):
    """Allowed auth expectation vocabulary for catalog governance."""

    VIEWER = "viewer"
    OPERATOR = "operator"
    ADMIN = "admin"
    CLUSTER_OWNER = "cluster_owner"
    MODULE_OWNER = "module_owner"
    PROJECT_OWNER = "project_owner"
    AUTHENTICATED = "authenticated"


class ToolStability(str, Enum):
    """Lightweight lifecycle stability markers for MCP consumers."""

    EXPERIMENTAL = "experimental"
    STABLE = "stable"
    INTERNAL = "internal"


@dataclass(frozen=True)
class ToolCatalogEntry:
    """Single MCP tool catalog entry."""

    tool_name: str
    module: str
    http_method: str
    backend_path_template: str
    auth_expectation: str
    risk_class: ToolRiskClass
    uses_query_params: bool
    uses_json_body: bool
    tier: str
    stability: ToolStability
    since_version: str
    deprecated: bool
    replacement_tool: str | None
    notes: str


HIGH_RISK_TOOL_CATALOG: tuple[ToolCatalogEntry, ...] = (
    # ------------------------------------------------------------------
    # System (full module coverage in governed scope)
    # ------------------------------------------------------------------
    ToolCatalogEntry(
        tool_name="system_health",
        module="system",
        http_method="GET",
        backend_path_template="/api/system/health",
        auth_expectation="admin",
        risk_class=ToolRiskClass.READ_ONLY,
        uses_query_params=False,
        uses_json_body=False,
        tier="tier1",
        stability=ToolStability.STABLE,
        since_version="pre-2.10.71",
        deprecated=False,
        replacement_tool=None,
        notes="Admin-only system health route under /api/system router-level auth dependency.",
    ),
    ToolCatalogEntry(
        tool_name="system_settings",
        module="system",
        http_method="GET",
        backend_path_template="/api/settings",
        auth_expectation="admin",
        risk_class=ToolRiskClass.READ_ONLY,
        uses_query_params=False,
        uses_json_body=False,
        tier="tier1",
        stability=ToolStability.STABLE,
        since_version="pre-2.10.71",
        deprecated=False,
        replacement_tool=None,
        notes="Admin-only settings view.",
    ),
    # ------------------------------------------------------------------
    # Cluster management (full module coverage in governed scope)
    # ------------------------------------------------------------------
    ToolCatalogEntry(
        tool_name="list_clusters",
        module="cluster_management",
        http_method="GET",
        backend_path_template="/api/k8s/clusters",
        auth_expectation="viewer",
        risk_class=ToolRiskClass.READ_ONLY,
        uses_query_params=False,
        uses_json_body=False,
        tier="tier1",
        stability=ToolStability.STABLE,
        since_version="pre-2.10.71",
        deprecated=False,
        replacement_tool=None,
        notes="Global cluster inventory endpoint.",
    ),
    ToolCatalogEntry(
        tool_name="get_cluster",
        module="cluster_management",
        http_method="GET",
        backend_path_template="/api/k8s/clusters/{cluster_id}",
        auth_expectation="viewer",
        risk_class=ToolRiskClass.READ_ONLY,
        uses_query_params=False,
        uses_json_body=False,
        tier="tier1",
        stability=ToolStability.STABLE,
        since_version="pre-2.10.71",
        deprecated=False,
        replacement_tool=None,
        notes="Cluster detail payload.",
    ),
    ToolCatalogEntry(
        tool_name="list_namespaces",
        module="cluster_management",
        http_method="GET",
        backend_path_template="/api/k8s/clusters/{cluster_id}/namespaces",
        auth_expectation="viewer",
        risk_class=ToolRiskClass.READ_ONLY,
        uses_query_params=False,
        uses_json_body=False,
        tier="tier1",
        stability=ToolStability.STABLE,
        since_version="pre-2.10.71",
        deprecated=False,
        replacement_tool=None,
        notes="Namespace list wrapper over KubernetesService.list_namespaces.",
    ),
    ToolCatalogEntry(
        tool_name="list_resources",
        module="cluster_management",
        http_method="GET",
        backend_path_template="/api/k8s/clusters/{cluster_id}/resources/{resource_type}",
        auth_expectation="viewer",
        risk_class=ToolRiskClass.READ_ONLY,
        uses_query_params=True,
        uses_json_body=False,
        tier="tier1",
        stability=ToolStability.STABLE,
        since_version="pre-2.10.71",
        deprecated=False,
        replacement_tool=None,
        notes="Optional namespace query param only when provided.",
    ),
    ToolCatalogEntry(
        tool_name="get_resource",
        module="cluster_management",
        http_method="GET",
        backend_path_template="/api/k8s/clusters/{cluster_id}/resources/{resource_type}/{name}/describe",
        auth_expectation="viewer",
        risk_class=ToolRiskClass.READ_ONLY,
        uses_query_params=True,
        uses_json_body=False,
        tier="tier1",
        stability=ToolStability.STABLE,
        since_version="pre-2.10.71",
        deprecated=True,
        replacement_tool="describe_resource",
        notes=(
            "Deprecated alias of describe_resource; kept callable for compatibility. "
            "Use describe_resource for new consumers. Planned removal no earlier than v2.12."
        ),
    ),
    ToolCatalogEntry(
        tool_name="get_pod_logs",
        module="cluster_management",
        http_method="GET",
        backend_path_template="/api/k8s/clusters/{cluster_id}/pods/{pod_name}/logs",
        auth_expectation="viewer",
        risk_class=ToolRiskClass.READ_ONLY,
        uses_query_params=True,
        uses_json_body=False,
        tier="tier1",
        stability=ToolStability.STABLE,
        since_version="pre-2.10.71",
        deprecated=False,
        replacement_tool=None,
        notes="namespace required; container/tail_lines optional query params.",
    ),
    ToolCatalogEntry(
        tool_name="describe_resource",
        module="cluster_management",
        http_method="GET",
        backend_path_template="/api/k8s/clusters/{cluster_id}/resources/{resource_type}/{name}/describe",
        auth_expectation="viewer",
        risk_class=ToolRiskClass.READ_ONLY,
        uses_query_params=True,
        uses_json_body=False,
        tier="tier1",
        stability=ToolStability.STABLE,
        since_version="pre-2.10.71",
        deprecated=False,
        replacement_tool=None,
        notes="Same backend route as get_resource; richer describe semantics.",
    ),
    ToolCatalogEntry(
        tool_name="get_cluster_events",
        module="cluster_management",
        http_method="GET",
        backend_path_template="/api/k8s/clusters/{cluster_id}/events",
        auth_expectation="viewer",
        risk_class=ToolRiskClass.READ_ONLY,
        uses_query_params=True,
        uses_json_body=False,
        tier="tier1",
        stability=ToolStability.STABLE,
        since_version="pre-2.10.71",
        deprecated=False,
        replacement_tool=None,
        notes="MCP sends limit and optional namespace query params.",
    ),
    ToolCatalogEntry(
        tool_name="get_node_metrics",
        module="cluster_management",
        http_method="GET",
        backend_path_template="/api/k8s/clusters/{cluster_id}/top/nodes",
        auth_expectation="viewer",
        risk_class=ToolRiskClass.READ_ONLY,
        uses_query_params=False,
        uses_json_body=False,
        tier="tier1",
        stability=ToolStability.STABLE,
        since_version="pre-2.10.71",
        deprecated=False,
        replacement_tool=None,
        notes="Node top metrics.",
    ),
    ToolCatalogEntry(
        tool_name="get_pod_metrics",
        module="cluster_management",
        http_method="GET",
        backend_path_template="/api/k8s/clusters/{cluster_id}/top/pods",
        auth_expectation="viewer",
        risk_class=ToolRiskClass.READ_ONLY,
        uses_query_params=True,
        uses_json_body=False,
        tier="tier1",
        stability=ToolStability.STABLE,
        since_version="pre-2.10.71",
        deprecated=False,
        replacement_tool=None,
        notes="Optional namespace query param.",
    ),
    # Platform mutation/recovery
    # Cluster CRUD (extended)
    # Resource lifecycle (apply/update/patch/delete/label/annotate)
    # Deployment rollouts
    ToolCatalogEntry(
        tool_name="rollout_history", module="cluster_management", http_method="GET",
        backend_path_template="/api/k8s/clusters/{cluster_id}/deployments/{deployment_name}/rollout/history",
        auth_expectation="viewer", risk_class=ToolRiskClass.READ_ONLY,
        uses_query_params=True, uses_json_body=False,
        tier="tier1", stability=ToolStability.STABLE, since_version="3.1",
        deprecated=False, replacement_tool=None,
        notes="kubectl rollout history equivalent; namespace required query param.",
    ),
    ToolCatalogEntry(
        tool_name="rollout_status", module="cluster_management", http_method="GET",
        backend_path_template="/api/k8s/clusters/{cluster_id}/deployments/{deployment_name}/rollout/status",
        auth_expectation="viewer", risk_class=ToolRiskClass.READ_ONLY,
        uses_query_params=True, uses_json_body=False,
        tier="tier1", stability=ToolStability.STABLE, since_version="3.1",
        deprecated=False, replacement_tool=None,
        notes="kubectl rollout status equivalent.",
    ),
    # Node ops
    # Tunnels
    # ------------------------------------------------------------------
    # Helm (full module coverage in governed scope)
    # ------------------------------------------------------------------
    # Helm mutating
    # ------------------------------------------------------------------
    # Config management (full module coverage in governed scope)
    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # BNK operations (full module coverage in governed scope)
    # ------------------------------------------------------------------
    ToolCatalogEntry(
        tool_name="bnk_data",
        module="bnk_operations",
        http_method="GET",
        backend_path_template="/api/k8s/clusters/{cluster_id}/f5bnk/data",
        auth_expectation="viewer",
        risk_class=ToolRiskClass.READ_ONLY,
        uses_query_params=True,
        uses_json_body=False,
        tier="tier1",
        stability=ToolStability.STABLE,
        since_version="pre-2.10.71",
        deprecated=False,
        replacement_tool=None,
        notes="Unified BNK data endpoint with optional namespace query filter.",
    ),
    ToolCatalogEntry(
        tool_name="bnk_gateway_topology",
        module="bnk_operations",
        http_method="GET",
        backend_path_template="/api/k8s/clusters/{cluster_id}/f5bnk/gateway-topology",
        auth_expectation="viewer",
        risk_class=ToolRiskClass.READ_ONLY,
        uses_query_params=False,
        uses_json_body=False,
        tier="tier1",
        stability=ToolStability.STABLE,
        since_version="pre-2.10.71",
        deprecated=False,
        replacement_tool=None,
        notes="GatewayClass→Gateway→HTTPRoute→backend topology view.",
    ),
    ToolCatalogEntry(
        tool_name="bnk_health",
        module="bnk_operations",
        http_method="GET",
        backend_path_template="/api/k8s/clusters/{cluster_id}/f5bnk/health",
        auth_expectation="viewer",
        risk_class=ToolRiskClass.READ_ONLY,
        uses_query_params=False,
        uses_json_body=False,
        tier="tier1",
        stability=ToolStability.STABLE,
        since_version="pre-2.10.71",
        deprecated=False,
        replacement_tool=None,
        notes="BNK health analysis derived from unified data fetch.",
    ),
    ToolCatalogEntry(
        tool_name="bnk_policy_associations",
        module="bnk_operations",
        http_method="GET",
        backend_path_template="/api/k8s/clusters/{cluster_id}/f5bnk/policy-gateway-associations",
        auth_expectation="viewer",
        risk_class=ToolRiskClass.READ_ONLY,
        uses_query_params=False,
        uses_json_body=False,
        tier="tier1",
        stability=ToolStability.STABLE,
        since_version="pre-2.10.71",
        deprecated=False,
        replacement_tool=None,
        notes="Policy attachment graph for gateways/routes.",
    ),
    ToolCatalogEntry(
        tool_name="a2a_discover_agents",
        module="bnk_operations",
        http_method="GET",
        backend_path_template="/api/k8s/clusters/{cluster_id}/f5bnk/a2a/agents",
        auth_expectation="viewer",
        risk_class=ToolRiskClass.READ_ONLY,
        uses_query_params=True,
        uses_json_body=False,
        tier="tier1",
        stability=ToolStability.STABLE,
        since_version="pre-2.10.71",
        deprecated=False,
        replacement_tool=None,
        notes="Optional probe=true query triggers backend service probing for agent cards.",
    ),
    ToolCatalogEntry(
        tool_name="tmm_list_pods",
        module="bnk_operations",
        http_method="GET",
        backend_path_template="/api/k8s/clusters/{cluster_id}/tmm-debug/pods",
        auth_expectation="viewer",
        risk_class=ToolRiskClass.READ_ONLY,
        uses_query_params=False,
        uses_json_body=False,
        tier="tier1",
        stability=ToolStability.STABLE,
        since_version="pre-2.10.71",
        deprecated=False,
        replacement_tool=None,
        notes="List TMM pods and debug-container availability.",
    ),
    ToolCatalogEntry(
        tool_name="tmm_configview",
        module="bnk_operations",
        http_method="POST",
        backend_path_template="/api/k8s/clusters/{cluster_id}/tmm-debug/configview",
        auth_expectation="viewer",
        risk_class=ToolRiskClass.READ_ONLY,
        uses_query_params=False,
        uses_json_body=True,
        tier="tier1",
        stability=ToolStability.STABLE,
        since_version="pre-2.10.71",
        deprecated=False,
        replacement_tool=None,
        notes="Structured configview inspection by pod/namespace.",
    ),
    ToolCatalogEntry(
        tool_name="bnk_recovery_status",
        module="bnk_operations",
        http_method="GET",
        backend_path_template="/api/k8s/clusters/{cluster_id}/recovery/status",
        auth_expectation="operator",
        risk_class=ToolRiskClass.READ_ONLY,
        uses_query_params=False,
        uses_json_body=False,
        tier="tier1",
        stability=ToolStability.STABLE,
        since_version="pre-2.10.71",
        deprecated=False,
        replacement_tool=None,
        notes="Recovery preflight checks are operator-gated under recovery router.",
    ),
    # ------------------------------------------------------------------
    # IaC operations (full module coverage in governed scope)
    # ------------------------------------------------------------------
    # Module execution (init/deploy/cancel/retry; plan/apply/destroy elsewhere)
    # Module diagnostics
    # Stack template introspection + instance lifecycle
    # Task tracking (apply/destroy/deploy return task_ids — these track them)
    # Project secrets
    # ------------------------------------------------------------------
    # Cloud authentication (new governed module in 3.1)
    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # Diagnostics & Fleet (full module coverage in governed scope)
    # ------------------------------------------------------------------
    ToolCatalogEntry(
        tool_name="qkview_list",
        module="diagnostics_fleet",
        http_method="GET",
        backend_path_template="/api/qkview/list",
        auth_expectation="viewer",
        risk_class=ToolRiskClass.READ_ONLY,
        uses_query_params=True,
        uses_json_body=False,
        tier="tier1",
        stability=ToolStability.STABLE,
        since_version="pre-2.10.71",
        deprecated=False,
        replacement_tool=None,
        notes="Lists available QKView files for a cluster (require_viewer).",
    ),
    ToolCatalogEntry(
        tool_name="qkview_status",
        module="diagnostics_fleet",
        http_method="GET",
        backend_path_template="/api/qkview/{qkview_id}/status",
        auth_expectation="viewer",
        risk_class=ToolRiskClass.READ_ONLY,
        uses_query_params=True,
        uses_json_body=False,
        tier="tier1",
        stability=ToolStability.STABLE,
        since_version="pre-2.10.71",
        deprecated=False,
        replacement_tool=None,
        notes="Polls QKView job status (require_viewer).",
    ),
    ToolCatalogEntry(
        tool_name="cluster_connectivity",
        module="diagnostics_fleet",
        http_method="GET",
        backend_path_template="/api/k8s/clusters/{cluster_id}/connectivity",
        auth_expectation="viewer",
        risk_class=ToolRiskClass.READ_ONLY,
        uses_query_params=False,
        uses_json_body=False,
        tier="tier1",
        stability=ToolStability.STABLE,
        since_version="pre-2.10.71",
        deprecated=False,
        replacement_tool=None,
        notes="Probes connectivity to a single cluster (require_viewer).",
    ),
    ToolCatalogEntry(
        tool_name="cluster_connectivity_batch",
        module="diagnostics_fleet",
        http_method="GET",
        backend_path_template="/api/k8s/clusters/connectivity",
        auth_expectation="viewer",
        risk_class=ToolRiskClass.READ_ONLY,
        uses_query_params=False,
        uses_json_body=False,
        tier="tier1",
        stability=ToolStability.STABLE,
        since_version="pre-2.10.71",
        deprecated=False,
        replacement_tool=None,
        notes="Probes connectivity to all clusters in parallel (require_viewer).",
    ),
    ToolCatalogEntry(
        tool_name="dpf_detect",
        module="diagnostics_fleet",
        http_method="GET",
        backend_path_template="/api/k8s/clusters/{cluster_id}/dpf/detect",
        auth_expectation="viewer",
        risk_class=ToolRiskClass.READ_ONLY,
        uses_query_params=False,
        uses_json_body=False,
        tier="tier1",
        stability=ToolStability.STABLE,
        since_version="pre-2.10.71",
        deprecated=False,
        replacement_tool=None,
        notes="Detects DPF CRDs on a cluster (require_viewer).",
    ),
    ToolCatalogEntry(
        tool_name="dpf_data",
        module="diagnostics_fleet",
        http_method="GET",
        backend_path_template="/api/k8s/clusters/{cluster_id}/dpf/data",
        auth_expectation="viewer",
        risk_class=ToolRiskClass.READ_ONLY,
        uses_query_params=False,
        uses_json_body=False,
        tier="tier1",
        stability=ToolStability.STABLE,
        since_version="pre-2.10.71",
        deprecated=False,
        replacement_tool=None,
        notes="Gets DPF data including DPU devices and services (require_viewer).",
    ),
    ToolCatalogEntry(
        tool_name="dpf_health",
        module="diagnostics_fleet",
        http_method="GET",
        backend_path_template="/api/k8s/clusters/{cluster_id}/dpf/health",
        auth_expectation="viewer",
        risk_class=ToolRiskClass.READ_ONLY,
        uses_query_params=False,
        uses_json_body=False,
        tier="tier1",
        stability=ToolStability.STABLE,
        since_version="pre-2.10.71",
        deprecated=False,
        replacement_tool=None,
        notes="Gets DPF health status for a cluster (require_viewer).",
    ),
    ToolCatalogEntry(
        tool_name="list_alert_channels",
        module="diagnostics_fleet",
        http_method="GET",
        backend_path_template="/api/alert-channels",
        auth_expectation="viewer",
        risk_class=ToolRiskClass.READ_ONLY,
        uses_query_params=False,
        uses_json_body=False,
        tier="tier1",
        stability=ToolStability.STABLE,
        since_version="pre-2.10.71",
        deprecated=False,
        replacement_tool=None,
        notes="Lists configured alert channels (require_viewer).",
    ),
)


GOVERNED_MODULES: tuple[str, ...] = (
    "system",
    "cluster_management",
    "bnk_operations",
    "diagnostics_fleet",
)


# Keep this explicit and stable for docs/tests/CI policy checks.
ALLOWED_AUTH_EXPECTATIONS: tuple[str, ...] = tuple(expectation.value for expectation in ToolAuthExpectation)
ALLOWED_TOOL_STABILITY: tuple[str, ...] = tuple(stability.value for stability in ToolStability)


def get_high_risk_tool_catalog() -> list[dict[str, object]]:
    """Return catalog entries as plain dictionaries for JSON serialization/tests."""

    return [asdict(entry) for entry in HIGH_RISK_TOOL_CATALOG]
