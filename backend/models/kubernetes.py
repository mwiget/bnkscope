"""Kubernetes cluster and F5 BNK networking models."""

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from database import Base
from models.enums import ClusterStatus


class KubernetesCluster(Base):
    """Kubernetes cluster configuration and connection info."""
    __tablename__ = "kubernetes_clusters"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False, unique=True, index=True)
    context = Column(String(255), nullable=False)  # kubectl context name
    api_server = Column(String(500))
    version = Column(String(50))
    status = Column(String(50), default=ClusterStatus.ACTIVE)
    last_synced_at = Column(DateTime(timezone=True))
    meta_data = Column(JSON)  # Additional cluster metadata

    kubeconfig_encrypted = Column(Text, nullable=True)  # Base64 encoded encrypted kubeconfig
    cloud_provider = Column(String(50))  # aws, azure, gcp, on-prem
    region = Column(String(100))  # Cloud region
    # Cloud credentials used to mint EKS/GKE tokens. These lived on the owning
    # project until fleets/projects were removed (bnkscope Phase 2); credential
    # resolution is now per-cluster.
    credential_template_id = Column(Integer, ForeignKey("cloud_credential_templates.id"), nullable=True)
    cloud_credentials_encrypted = Column(Text, nullable=True)  # legacy inline blob
    default_namespace = Column(String(255), default="default")

    # PLATFORM-CONTEXT-002: detected cluster platform context (additive)
    detected_platform_profile = Column(String(50), nullable=True)
    detected_platform_provider = Column(String(50), nullable=True)
    platform_capabilities = Column(JSON, nullable=True)
    platform_constraints = Column(JSON, nullable=True)

    # Per-cluster opt-in: which prerequisite checks the scanner runs.
    # NULL means "use the global default set". Stored as a list of prereq
    # IDs (e.g. ["cert-manager", "multus", "storage", "gateway-api"]).
    enabled_prerequisites = Column(JSON, nullable=True)

    # Namespaces where BNK/F5 components were actually discovered on this cluster.
    # Written back after each discovery run. NULL / [] = not yet discovered.
    # Used as the fast-path seed for subsequent discovery runs (in addition to
    # the static BNK_NAMESPACES fallback).
    discovered_namespaces = Column(JSON, nullable=True)

    # ADR-494 Phase B: BNK release line currently running on this cluster (set by discovery/scan).
    running_release_id = Column(Integer, ForeignKey("bnk_releases.id", ondelete="SET NULL"), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    credential_template = relationship(
        "CloudCredentialTemplate", back_populates="clusters", foreign_keys=[credential_template_id]
    )

