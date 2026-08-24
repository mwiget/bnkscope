"""
Shared helpers, serializers, and Pydantic models used across the k8s route modules.

Extracted from the monolithic kubernetes.py to avoid duplication.
"""

import logging

from pydantic import BaseModel, model_validator

from models import KubernetesCluster
from services.platform_context_service import PlatformContextService
from utils.provider_config import normalize_cloud_provider
from utils.validators import validate_aws_region

logger = logging.getLogger(__name__)

# ============================================================================
# DRY Serialization Helpers
# ============================================================================

def serialize_cluster(cluster: KubernetesCluster) -> dict:
    """Serialize a KubernetesCluster to dict."""
    platform_context = PlatformContextService.serialize_cluster_context(cluster)

    result = {
        "id": cluster.id,
        "name": cluster.name,
        "context": cluster.context,
        "api_server": cluster.api_server,
        "cloud_provider": cluster.cloud_provider,
        "detected_platform_profile": platform_context.detected_platform_profile,
        "detected_platform_provider": platform_context.detected_platform_provider,
        "platform_capabilities": platform_context.platform_capabilities,
        "platform_constraints": platform_context.platform_constraints,
        "region": cluster.region,
        "default_namespace": cluster.default_namespace,
        "status": cluster.status,
        "version": cluster.version,
        "last_synced_at": cluster.last_synced_at.isoformat() if cluster.last_synced_at else None,
        "created_at": cluster.created_at.isoformat() if cluster.created_at else None,
        # Per-cluster prereq selection (NULL → defaults; locked entries are
        # always included in the effective set).
        "enabled_prerequisites": cluster.enabled_prerequisites,
        # Observed BNK release line, set by the discovery scan (ADR-494).
        "running_release_id": cluster.running_release_id,
        # Written by discovery. `has_dpf` is what gates the DPF tab in the UI,
        # so the list endpoint has to carry it — the detail endpoint alone is
        # too late, the tab strip renders from the list.
        "meta_data": cluster.meta_data,
    }
    return result


# ============================================================================
# Pydantic Request Models — Cluster CRUD
# ============================================================================

class ClusterCreateRequest(BaseModel):
    """Request model for creating a Kubernetes cluster configuration."""
    name: str
    kubeconfig: str  # Base64 encoded kubeconfig YAML
    cloud_provider: str | None = None  # aws, azure, gcp, ibm, on-prem, other
    region: str | None = None
    context: str | None = None  # kubectl context name (optional, will auto-detect)
    default_namespace: str | None = "default"

    @model_validator(mode="after")
    def _validate_region(self):
        # Canonicalize provider case so "IBM" == "ibm" everywhere downstream.
        self.cloud_provider = normalize_cloud_provider(self.cloud_provider)
        if self.cloud_provider in {"aws", "eks"}:
            validate_aws_region(self.region, field_name="region")
        return self

class ClusterUpdateRequest(BaseModel):
    """Request model for updating a Kubernetes cluster configuration."""
    name: str | None = None
    kubeconfig: str | None = None  # Base64 encoded kubeconfig YAML
    cloud_provider: str | None = None
    region: str | None = None
    context: str | None = None
    default_namespace: str | None = None
    # Per-cluster prereq selection — list of prereq IDs (e.g.
    # ["cert-manager", "multus", "storage"]). Pass an empty list to disable
    # all optional prereqs; pass None to leave the cluster's setting alone.
    enabled_prerequisites: list[str] | None = None

    @model_validator(mode="after")
    def _validate_region(self):
        # Canonicalize provider case so "IBM" == "ibm" everywhere downstream.
        self.cloud_provider = normalize_cloud_provider(self.cloud_provider)
        if self.cloud_provider in {"aws", "eks"}:
            validate_aws_region(self.region, field_name="region")
        return self

# ============================================================================
# Pydantic Request Models — Resource Operations
# ============================================================================

class ResourceCreateRequest(BaseModel):
    """Request model for creating a Kubernetes resource."""
    resource_yaml: str  # YAML definition of the resource
    namespace: str | None = None
    dry_run: bool = False

class ResourceUpdateRequest(BaseModel):
    """Request model for updating a Kubernetes resource."""
    resource_yaml: str  # YAML definition of the resource
    namespace: str | None = None
    dry_run: bool = False

class ResourceDeleteRequest(BaseModel):
    """Request model for deleting a Kubernetes resource."""
    namespace: str | None = None
    dry_run: bool = False

class ScaleDeploymentRequest(BaseModel):
    """Request model for scaling a deployment."""
    replicas: int
    namespace: str

class ResourcePatchRequest(BaseModel):
    """Request model for patching a Kubernetes resource."""
    patch_data: dict
    namespace: str | None = None
    patch_type: str = "strategic"  # strategic, merge, or json

class LabelResourceRequest(BaseModel):
    """Request model for labeling a resource."""
    labels: dict
    namespace: str | None = None
    overwrite: bool = False

class AnnotateResourceRequest(BaseModel):
    """Request model for annotating a resource."""
    annotations: dict
    namespace: str | None = None
    overwrite: bool = False

# ============================================================================
# Pydantic Request Models — Cluster Scanner
# ============================================================================

class AdaptiveModuleRequest(BaseModel):
    """Request model for adaptive module selection."""
    template_slug: str | None = None         # Stack template to plan for (e.g., "f5-bnk-2.2")
    module_paths: list[str] | None = None    # Or an explicit list of module paths
    sizing_profile: str | None = None        # "lab" applies #387 part C NON-PRODUCTION f5-tmm sizing overrides
