"""
Cluster Management Service — DB and business logic for Kubernetes cluster management.

Extracted from routes/k8s/clusters.py to separate HTTP handling from domain logic.

Covers cluster CRUD for clusters added by hand. Contexts that come from the
operator's own kubeconfig go through ``cluster_discovery_service`` instead.

The ``refresh_kubeconfig`` action that used to live here shelled out to
``aws eks update-kubeconfig``; the API image has no CLI tools (Phase 4), and a
locally-discovered cluster re-reads its kubeconfig on every discovery sweep, so
there was nothing left for it to do.
"""

import base64
import logging
from typing import Any

import yaml

from core.encryption import encrypt_value
from core.errors import BadRequestError, ConflictError
from models import KubernetesCluster
from services.base_service import BaseService
from services.kubeconfig_normalizer import NormalizationSource, normalize_kubeconfig
from services.platform_context_service import PlatformContextService

logger = logging.getLogger(__name__)


class ClusterManagementService(BaseService):
    """Service layer for Kubernetes cluster management operations."""

    @staticmethod
    def _kubeconfig_default_context(kubeconfig_yaml: str | None) -> str | None:
        """Pick the kubeconfig's current-context (or first listed context)."""
        if not kubeconfig_yaml:
            return None
        try:
            cfg = yaml.safe_load(kubeconfig_yaml)
        except Exception:
            return None
        if not isinstance(cfg, dict):
            return None
        current = cfg.get("current-context")
        if current:
            return current
        contexts = cfg.get("contexts") or []
        if contexts and isinstance(contexts[0], dict):
            return contexts[0].get("name")
        return None

    def create_cluster(self, cluster_data) -> dict[str, Any]:
        """Register a Kubernetes cluster from a kubeconfig."""

        # Decode kubeconfig
        try:
            kubeconfig_yaml = base64.b64decode(cluster_data.kubeconfig).decode('utf-8')
        except Exception as e:
            raise BadRequestError(f"Invalid base64 kubeconfig: {e}")

        # Parse kubeconfig
        try:
            kubeconfig_dict = yaml.safe_load(kubeconfig_yaml)
            context = cluster_data.context
            if not context:
                context = kubeconfig_dict.get("current-context")
                if not context and kubeconfig_dict.get("contexts"):
                    context = kubeconfig_dict["contexts"][0]["name"]

            # Find API server — match the selected context's cluster if possible
            api_server = None
            ctx_cluster_name = None
            for ctx_entry in kubeconfig_dict.get("contexts", []):
                if ctx_entry.get("name") == context:
                    ctx_cluster_name = ctx_entry.get("context", {}).get("cluster")
                    break
            for cl_entry in kubeconfig_dict.get("clusters", []):
                if ctx_cluster_name and cl_entry.get("name") == ctx_cluster_name:
                    api_server = cl_entry.get("cluster", {}).get("server")
                    break
            # Fallback to first cluster if context match failed
            if not api_server and kubeconfig_dict.get("clusters"):
                api_server = kubeconfig_dict["clusters"][0].get("cluster", {}).get("server")
        except Exception as e:
            raise BadRequestError(f"Invalid kubeconfig YAML: {e}")

        # Validate and normalize portability (raises KubeconfigUnportableError → 422)
        kubeconfig_yaml = normalize_kubeconfig(
            kubeconfig_yaml, source=NormalizationSource.MANUAL_UPLOAD
        )

        kubeconfig_encrypted = encrypt_value(kubeconfig_yaml)

        # Duplicate name check — cluster names are unique across the instance.
        existing = self.db.query(KubernetesCluster).filter(
            KubernetesCluster.name == cluster_data.name,
        ).first()
        if existing:
            raise ConflictError("cluster", f"Cluster '{cluster_data.name}' already exists")

        # Default cloud_provider to 'on-prem' if not specified — gives the platform
        # detection something to work with instead of leaving it as 'unknown'.
        # Subsequent scans can refine this (e.g. detect OpenShift via CRDs).
        cloud_provider_value = cluster_data.cloud_provider or "on-prem"

        cluster = KubernetesCluster(
            name=cluster_data.name,
            context=context,
            api_server=api_server,
            kubeconfig_encrypted=kubeconfig_encrypted,
            cloud_provider=cloud_provider_value,
            region=cluster_data.region,
            default_namespace=cluster_data.default_namespace,
            status="active"
        )

        PlatformContextService.apply_cluster_context(cluster)

        self.db.add(cluster)
        self.db.flush()
        self.db.refresh(cluster)

        context = PlatformContextService.serialize_cluster_context(cluster)
        return {
            "id": cluster.id, "name": cluster.name, "context": cluster.context,
            "api_server": cluster.api_server, "cloud_provider": cluster.cloud_provider,
            "detected_platform_profile": context.detected_platform_profile,
            "detected_platform_provider": context.detected_platform_provider,
            "platform_capabilities": context.platform_capabilities,
            "platform_constraints": context.platform_constraints,
            "region": cluster.region, "default_namespace": cluster.default_namespace,
            "status": cluster.status
        }

    def list_all_clusters(self) -> dict[str, Any]:
        """List all Kubernetes clusters."""
        from routes.k8s._shared import serialize_cluster

        clusters = (
            self.db.query(KubernetesCluster)
            .all()
        )
        result = [serialize_cluster(c) for c in clusters]
        return {"clusters": result, "count": len(result)}

    def get_cluster_details(self, cluster_id: int) -> dict[str, Any]:
        """Get cluster details."""
        cluster = self._get_cluster(cluster_id)
        context = PlatformContextService.serialize_cluster_context(cluster)
        return {
            "id": cluster.id, "name": cluster.name, "context": cluster.context,
            "api_server": cluster.api_server, "cloud_provider": cluster.cloud_provider,
            "detected_platform_profile": context.detected_platform_profile,
            "detected_platform_provider": context.detected_platform_provider,
            "platform_capabilities": context.platform_capabilities,
            "platform_constraints": context.platform_constraints,
            "region": cluster.region, "default_namespace": cluster.default_namespace,
            "status": cluster.status, "version": cluster.version,
            # ADR-478/494: release FK ids — deployable = intent; running = observed by scan.
            "running_release_id": cluster.running_release_id,
            "last_synced_at": cluster.last_synced_at.isoformat() if cluster.last_synced_at else None,
            "created_at": cluster.created_at.isoformat() if cluster.created_at else None,
            "updated_at": cluster.updated_at.isoformat() if cluster.updated_at else None
        }

    def update_cluster(self, cluster_id: int, cluster_data) -> dict:
        """Update cluster configuration."""
        from routes.k8s._shared import serialize_cluster
        cluster = self._get_cluster(cluster_id)

        if cluster_data.name is not None:
            existing = self.db.query(KubernetesCluster).filter(
                KubernetesCluster.name == cluster_data.name,
                KubernetesCluster.id != cluster_id,
            ).first()
            if existing:
                raise ConflictError("cluster", f"Cluster '{cluster_data.name}' already exists")
            cluster.name = cluster_data.name

        if cluster_data.kubeconfig is not None:
            try:
                kubeconfig_yaml = base64.b64decode(cluster_data.kubeconfig).decode('utf-8')
            except Exception as e:
                raise BadRequestError(f"Invalid base64 kubeconfig: {e}")
            # Validate and normalize portability (raises KubeconfigUnportableError → 422)
            kubeconfig_yaml = normalize_kubeconfig(
                kubeconfig_yaml, source=NormalizationSource.MANUAL_UPLOAD
            )
            cluster.kubeconfig_encrypted = encrypt_value(kubeconfig_yaml)

        if cluster_data.cloud_provider is not None:
            cluster.cloud_provider = cluster_data.cloud_provider
        if cluster_data.region is not None:
            cluster.region = cluster_data.region
        if cluster_data.context is not None:
            cluster.context = cluster_data.context
        if cluster_data.default_namespace is not None:
            cluster.default_namespace = cluster_data.default_namespace
        if getattr(cluster_data, "enabled_prerequisites", None) is not None:
            from services.scanner.recommendations import (
                KNOWN_PREREQUISITE_IDS,
                LOCKED_PREREQUISITE_IDS,
            )
            requested = list(cluster_data.enabled_prerequisites)
            unknown = set(requested) - set(KNOWN_PREREQUISITE_IDS)
            if unknown:
                raise BadRequestError(
                    f"Unknown prerequisite IDs: {sorted(unknown)}. "
                    f"Allowed: {sorted(KNOWN_PREREQUISITE_IDS)}"
                )
            normalized = sorted(set(requested) | set(LOCKED_PREREQUISITE_IDS))
            cluster.enabled_prerequisites = normalized

        PlatformContextService.apply_cluster_context(cluster)

        self.db.flush()
        self.db.refresh(cluster)

        return serialize_cluster(cluster)

    def delete_cluster(self, cluster_id: int) -> dict[str, Any]:
        """Delete cluster configuration."""
        cluster = self._get_cluster(cluster_id)
        cluster_name = cluster.name

        # tmfifo IP release is handled by the KubernetesCluster before_delete
        # mapper event in models/kubernetes.py (ADR-424 finding B) — no
        # per-caller wiring needed here.
        self.db.delete(cluster)
        self.db.flush()
        return {"message": f"Cluster '{cluster_name}' deleted successfully"}
